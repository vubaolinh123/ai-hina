from __future__ import annotations

import argparse
import json
import os
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .error_log import redact_for_log


ROOT = Path(__file__).resolve().parents[5]
_ALLOWED_RECORD_FIELDS = (
    "timestamp",
    "level",
    "component",
    "operation",
    "errorCode",
    "message",
    "correlationId",
    "sessionId",
    "turnId",
    "exceptionType",
    "buildCommit",
    "contractVersion",
    "runtimeProfile",
    "context",
)


def collect_error_report(
    log_paths: list[Path],
    output_path: Path,
    *,
    max_records: int = 100,
    build_commit: str | None = None,
) -> dict[str, Any]:
    if not 1 <= max_records <= 1_000:
        raise ValueError("max_records must be between 1 and 1000")
    records: list[dict[str, Any]] = []
    invalid_lines = 0
    for path in sorted(set(log_paths)):
        if not path.is_file():
            continue
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                invalid_lines += 1
                continue
            if not isinstance(value, dict) or value.get("level") not in {"error", "fatal"}:
                continue
            record = {
                key: redact_for_log(value[key], key)
                for key in _ALLOWED_RECORD_FIELDS
                if key in value
            }
            record["sourceLog"] = path.name
            records.append(record)
    records.sort(key=lambda item: str(item.get("timestamp", "")))
    records = records[-max_records:]
    report = {
        "schemaVersion": "1.0",
        "generatedAt": datetime.now(UTC).isoformat(),
        "buildCommit": build_commit or _git_commit(),
        "recordCount": len(records),
        "invalidLinesSkipped": invalid_lines,
        "records": records,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return report


def _git_commit() -> str:
    environment_commit = os.environ.get("HINA_BUILD_COMMIT")
    if environment_commit:
        return environment_commit
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
    except (OSError, subprocess.CalledProcessError):
        return "unknown"
    return result.stdout.strip()


def main() -> int:
    parser = argparse.ArgumentParser(description="Collect bounded redacted Hina error records.")
    parser.add_argument("--log", type=Path, action="append")
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "var" / "reports" / "hina-error-report.json",
    )
    parser.add_argument("--max-records", type=int, default=100)
    args = parser.parse_args()
    log_paths = args.log or sorted((ROOT / "var" / "logs").glob("*.jsonl"))
    report = collect_error_report(
        [path.resolve() for path in log_paths],
        args.output.resolve(),
        max_records=args.max_records,
    )
    print(
        json.dumps(
            {
                "status": "ok",
                "output": str(args.output.resolve()),
                "recordCount": report["recordCount"],
                "invalidLinesSkipped": report["invalidLinesSkipped"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
