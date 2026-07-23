from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def main() -> int:
    lock_path = ROOT / "third_party" / "code.lock.json"
    data = json.loads(lock_path.read_text(encoding="utf-8"))
    errors: list[str] = []

    if data.get("schema_version") != "1.0":
        errors.append("code.lock.json schema_version must be 1.0")
    components = data.get("components")
    if not isinstance(components, list):
        errors.append("code.lock.json components must be an array")
        components = []

    required = {
        "name",
        "source_url",
        "revision",
        "license_spdx",
        "source_hash",
        "destination_paths",
        "modifications",
    }
    for index, component in enumerate(components):
        if not isinstance(component, dict):
            errors.append(f"component {index} must be an object")
            continue
        missing = required - set(component)
        if missing:
            errors.append(f"component {index} missing fields: {sorted(missing)}")

    required_registries = (
        ROOT / "ml" / "models" / "manifests" / "README.md",
        ROOT / "assets" / "manifests" / "README.md",
        ROOT / "third_party" / "THIRD_PARTY_NOTICES.md",
    )
    for path in required_registries:
        if not path.is_file():
            errors.append(f"missing registry: {path.relative_to(ROOT)}")

    if errors:
        print("Provenance validation failed:")
        for error in errors:
            print(f"- {error}")
        return 1
    print(f"Provenance validation passed ({len(components)} imported components)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
