from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
ARTIFACT_DIR = ROOT / "artifacts" / "verification" / "M00"
OUTPUT = ARTIFACT_DIR / "artifact-manifest.json"


def git_value(*args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return result.stdout.strip()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    files = []
    for path in sorted(ARTIFACT_DIR.iterdir()):
        if not path.is_file() or path == OUTPUT:
            continue
        files.append(
            {
                "path": path.relative_to(ROOT).as_posix(),
                "sha256": sha256(path),
                "bytes": path.stat().st_size,
            }
        )
    manifest = {
        "schema_version": "1.0",
        "module_id": "M00",
        "generated_at": datetime.now(UTC).isoformat(),
        "commit_sha": git_value("rev-parse", "HEAD"),
        "tree_hash": git_value("write-tree"),
        "files": files,
    }
    OUTPUT.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(f"Wrote {OUTPUT.relative_to(ROOT)} with {len(files)} entries")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
