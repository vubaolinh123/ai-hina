from __future__ import annotations

import hashlib
import json
import re
import subprocess
import tomllib
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / "artifacts" / "verification" / "M00" / "sbom.cdx.json"
NPM_EVIDENCE = ROOT / "packages" / "contracts" / "npm-license-evidence.v1.json"


def git_sha() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return result.stdout.strip()


def git_timestamp() -> str:
    result = subprocess.run(
        ["git", "show", "-s", "--format=%cI", "HEAD"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return datetime.fromisoformat(result.stdout.strip()).isoformat()


def component_from_lock(entry: dict[str, Any]) -> dict[str, Any]:
    component = {
        "type": "library",
        "name": entry["name"],
        "version": entry["revision"],
        "licenses": [{"license": {"id": entry["license_spdx"]}}],
        "externalReferences": [
            {
                "type": "vcs",
                "url": entry["source_url"],
            }
        ],
        "properties": [
            {
                "name": "hina:source-hash",
                "value": entry["source_hash"],
            }
        ],
    }
    return component


def python_lock_components() -> list[dict[str, Any]]:
    with (ROOT / "uv.lock").open("rb") as handle:
        lock = tomllib.load(handle)
    components = []
    for package in lock.get("package", []):
        source = package.get("source", {})
        if "virtual" in source:
            continue
        name = package["name"]
        version = package["version"]
        components.append(
            {
                "type": "library",
                "name": name,
                "version": version,
                "purl": f"pkg:pypi/{name}@{version}",
                "properties": [
                    {
                        "name": "hina:dependency-scope",
                        "value": "development",
                    }
                ],
            }
        )
    return components


def parse_pnpm_lock() -> dict[str, Any]:
    text = (ROOT / "pnpm-lock.yaml").read_text(encoding="utf-8")
    packages: dict[str, dict[str, Any]] = {}
    snapshots: dict[str, list[str]] = {}
    current_section = ""
    current_key: str | None = None
    in_snapshot_dependencies = False

    for line in text.splitlines():
        if line and not line.startswith(" "):
            current_section = line.rstrip(":")
            current_key = None
            in_snapshot_dependencies = False
            continue
        if current_section == "packages":
            match = re.match(r"^  (.+@[^:]+):$", line)
            if match:
                current_key = match.group(1)
                name, version = split_pnpm_key(current_key)
                packages[current_key] = {"name": name, "version": version, "integrity": ""}
                continue
            integrity = re.search(r"integrity: ([^}]+)", line)
            if current_key is not None and integrity:
                packages[current_key]["integrity"] = integrity.group(1)
        elif current_section == "snapshots":
            match = re.match(r"^  (.+@[^:]+):", line)
            if match:
                current_key = match.group(1)
                snapshots.setdefault(current_key, [])
                in_snapshot_dependencies = False
                continue
            if current_key is not None and re.match(r"^    dependencies:$", line):
                in_snapshot_dependencies = True
                continue
            if in_snapshot_dependencies:
                dep = re.match(r"^      ([^:]+): (.+)$", line)
                if dep:
                    snapshots[current_key].append(f"{dep.group(1)}@{dep.group(2)}")
                    continue
                if line.startswith("    ") and not line.startswith("      "):
                    in_snapshot_dependencies = False
    return {"packages": packages, "snapshots": snapshots}


def split_pnpm_key(key: str) -> tuple[str, str]:
    name, version = key.rsplit("@", 1)
    return name, version


def npm_lock_scopes(lock: dict[str, Any]) -> dict[str, str]:
    roots = parse_pnpm_importer_roots()
    scopes: dict[str, str] = {}
    queue = sorted(roots.items())
    while queue:
        key, scope = queue.pop(0)
        if key in scopes:
            continue
        scopes[key] = scope
        for child in lock["snapshots"].get(key, []):
            queue.append((child, scope))
    return scopes


def parse_pnpm_importer_roots() -> dict[str, str]:
    text = (ROOT / "pnpm-lock.yaml").read_text(encoding="utf-8")
    roots: dict[str, str] = {}
    in_contracts = False
    current_scope: str | None = None
    current_name: str | None = None
    for line in text.splitlines():
        if line == "  packages/contracts:":
            in_contracts = True
            current_scope = None
            current_name = None
            continue
        if in_contracts and line.startswith("  ") and not line.startswith("    ") and line != "  packages/contracts:":
            break
        if not in_contracts:
            continue
        if line == "    dependencies:":
            current_scope = "runtime"
            current_name = None
            continue
        if line == "    devDependencies:":
            current_scope = "build"
            current_name = None
            continue
        name = re.match(r"^      ([^:]+):$", line)
        if name:
            current_name = name.group(1)
            continue
        version = re.match(r"^        version: (.+)$", line)
        if version and current_scope is not None and current_name is not None:
            roots[f"{current_name}@{version.group(1)}"] = current_scope
    return roots


def load_npm_evidence() -> dict[str, Any]:
    return json.loads(NPM_EVIDENCE.read_text(encoding="utf-8"))


def validate_npm_evidence(
    lock: dict[str, Any],
    scopes: dict[str, str],
    evidence: dict[str, Any] | None = None,
) -> dict[str, dict[str, Any]]:
    if evidence is None:
        evidence = load_npm_evidence()
    if evidence.get("schemaVersion") != "1.0":
        raise ValueError("npm license evidence schemaVersion must be 1.0")
    required_fields = {
        "name",
        "version",
        "purl",
        "integrity",
        "licenseSpdx",
        "scope",
        "sourceUrl",
        "licenseEvidence",
        "licenseSha256",
    }
    by_key: dict[str, dict[str, Any]] = {}
    for item in evidence.get("packages", []):
        if not isinstance(item, dict) or set(item) != required_fields:
            raise ValueError("npm license evidence entry fields do not match the reviewed contract")
        if any(not isinstance(item[field], str) or not item[field] for field in required_fields):
            raise ValueError("npm license evidence fields must be non-empty strings")
        key = f"{item.get('name')}@{item.get('version')}"
        if key in by_key:
            raise ValueError(f"duplicate npm license evidence entry: {key}")
        by_key[key] = item
    expected_keys = set(scopes)
    if set(by_key) != expected_keys:
        missing = sorted(expected_keys - set(by_key))
        extra = sorted(set(by_key) - expected_keys)
        raise ValueError(f"npm license evidence mismatch missing={missing} extra={extra}")
    for key, item in by_key.items():
        package = lock["packages"].get(key)
        if package is None:
            raise ValueError(f"npm evidence package is not in pnpm-lock.yaml: {key}")
        if item.get("scope") != scopes[key]:
            raise ValueError(f"npm evidence scope mismatch for {key}: {item.get('scope')} != {scopes[key]}")
        if not package.get("integrity"):
            raise ValueError(f"pnpm lock entry lacks integrity: {key}")
        if item["integrity"] != package["integrity"]:
            raise ValueError(f"npm evidence integrity mismatch for {key}")
        expected_purl = f"pkg:npm/{package['name']}@{package['version']}"
        if item["purl"] != expected_purl:
            raise ValueError(f"npm evidence purl mismatch for {key}")
        if item["scope"] not in {"runtime", "build"}:
            raise ValueError(f"npm evidence scope is invalid for {key}")
        evidence_relative = Path(item["licenseEvidence"])
        if evidence_relative.is_absolute() or ".." in evidence_relative.parts:
            raise ValueError(f"npm licenseEvidence path is unsafe for {key}")
        evidence_path = (ROOT / evidence_relative).resolve()
        if not evidence_path.is_relative_to(ROOT.resolve()) or not evidence_path.is_file():
            raise ValueError(f"npm licenseEvidence file does not exist for {key}: {item['licenseEvidence']}")
        if re.fullmatch(r"[0-9a-f]{64}", item["licenseSha256"]) is None:
            raise ValueError(f"npm licenseSha256 is invalid for {key}")
        actual_license_sha256 = hashlib.sha256(evidence_path.read_bytes()).hexdigest()
        if actual_license_sha256 != item["licenseSha256"]:
            raise ValueError(f"npm licenseSha256 mismatch for {key}")
    return by_key


def npm_lock_components() -> list[dict[str, Any]]:
    lock = parse_pnpm_lock()
    scopes = npm_lock_scopes(lock)
    evidence = validate_npm_evidence(lock, scopes)
    components: list[dict[str, Any]] = []
    for key in sorted(scopes):
        package = lock["packages"][key]
        item = evidence[key]
        components.append(
            {
                "type": "library",
                "name": package["name"],
                "version": package["version"],
                "purl": item["purl"],
                "licenses": [{"license": {"id": item["licenseSpdx"]}}],
                "externalReferences": [
                    {
                        "type": "vcs",
                        "url": item["sourceUrl"],
                    }
                ],
                "properties": [
                    {
                        "name": "hina:dependency-scope",
                        "value": scopes[key],
                    },
                    {
                        "name": "hina:pnpm-integrity",
                        "value": package["integrity"],
                    },
                    {
                        "name": "hina:license-evidence",
                        "value": f"{NPM_EVIDENCE.relative_to(ROOT).as_posix()}#{item['licenseEvidence']}",
                    },
                    {
                        "name": "hina:license-evidence-sha256",
                        "value": item["licenseSha256"],
                    },
                ],
            }
        )
    return components


def main() -> int:
    code_lock = json.loads(
        (ROOT / "third_party" / "code.lock.json").read_text(encoding="utf-8")
    )
    commit = git_sha()
    serial = uuid.uuid5(uuid.NAMESPACE_URL, f"https://github.com/vubaolinh123/ai-hina@{commit}")
    document = {
        "bomFormat": "CycloneDX",
        "specVersion": "1.5",
        "serialNumber": f"urn:uuid:{serial}",
        "version": 1,
        "metadata": {
            "timestamp": git_timestamp(),
            "component": {
                "type": "application",
                "name": "hina-ai",
                "version": "0.0.0",
                "bom-ref": f"hina-ai@{commit}",
                "licenses": [{"license": {"id": "MIT"}}],
                "externalReferences": [
                    {
                        "type": "vcs",
                        "url": "https://github.com/vubaolinh123/ai-hina.git",
                    }
                ],
                "properties": [
                    {
                        "name": "hina:commit-sha",
                        "value": commit,
                    }
                ],
            },
        },
        "components": [
            *[
                component_from_lock(entry)
                for entry in code_lock.get("components", [])
            ],
            *python_lock_components(),
            *npm_lock_components(),
        ],
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(
        json.dumps(document, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(f"Wrote {OUTPUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
