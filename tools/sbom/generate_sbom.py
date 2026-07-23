from __future__ import annotations

import json
import subprocess
import tomllib
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / "artifacts" / "verification" / "M00" / "sbom.cdx.json"


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
