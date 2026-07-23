from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_EVIDENCE = ROOT / "artifacts" / "verification" / "M01" / "repeat-gate-last.json"
PNPM = "pnpm.cmd" if os.name == "nt" else "pnpm"
REQUIRED_RUNS = 20


def git(*args: str) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return completed.stdout.strip()


def tracked_changes() -> str:
    return git("status", "--porcelain", "--untracked-files=no")


def snapshot() -> dict[str, str]:
    return {
        "head": git("rev-parse", "HEAD"),
        "tree": git("rev-parse", "HEAD^{tree}"),
        "trackedStatus": tracked_changes(),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=int, default=REQUIRED_RUNS, help="number of consecutive runs; must be exactly 20")
    parser.add_argument("--evidence", default=str(DEFAULT_EVIDENCE), help="machine-readable ignored evidence path")
    parser.add_argument("--require-clean", action="store_true", help="fail if tracked files are dirty before running")
    parser.add_argument("command", nargs=argparse.REMAINDER, help="optional command after --; defaults to pnpm test:contracts")
    args = parser.parse_args()

    if args.runs != REQUIRED_RUNS:
        print(f"M01 repeat gate requires exactly {REQUIRED_RUNS} runs", file=sys.stderr)
        return 2

    command = args.command
    if command and command[0] == "--":
        command = command[1:]
    if not command:
        command = [PNPM, "test:contracts"]

    evidence: dict[str, Any] = {
        "schemaVersion": "1.0",
        "requiredRuns": REQUIRED_RUNS,
        "requestedRuns": args.runs,
        "command": command,
        "cwd": str(ROOT),
        "startedAt": datetime.now(UTC).isoformat(),
        "initial": snapshot(),
        "runs": [],
        "ok": False,
        "requiredGatePassed": False,
        "completedRuns": 0,
        "failureCode": None,
    }
    status = 0
    try:
        if args.require_clean and evidence["initial"]["trackedStatus"]:
            print(evidence["initial"]["trackedStatus"], file=sys.stderr)
            print("tracked tree is dirty before repeat gate", file=sys.stderr)
            evidence["failureCode"] = "E_FLAKY_SUITE"
            return 1
        initial_head = evidence["initial"]["head"]
        initial_tree = evidence["initial"]["tree"]
        for index in range(1, args.runs + 1):
            before = snapshot()
            if before["head"] != initial_head or before["tree"] != initial_tree or before["trackedStatus"]:
                status = 1
                evidence["failureCode"] = "E_FLAKY_SUITE"
                evidence["runs"].append({"index": index, "skipped": True, "before": before, "reason": "tracked tree changed"})
                break
            completed = subprocess.run(command, cwd=ROOT)
            after = snapshot()
            evidence["runs"].append(
                {
                    "index": index,
                    "returnCode": completed.returncode,
                    "before": before,
                    "after": after,
                }
            )
            if completed.returncode != 0:
                status = completed.returncode
                evidence["failureCode"] = "E_GATE_20_RUN_FAIL"
                break
            if after["head"] != initial_head or after["tree"] != initial_tree or after["trackedStatus"]:
                status = 1
                evidence["failureCode"] = "E_FLAKY_SUITE"
                break
        evidence["completedRuns"] = sum(
            1
            for run in evidence["runs"]
            if run.get("returnCode") == 0
            and run["after"]["head"] == initial_head
            and run["after"]["tree"] == initial_tree
            and not run["after"]["trackedStatus"]
        )
        evidence["ok"] = status == 0 and evidence["completedRuns"] == args.runs
        evidence["requiredGatePassed"] = evidence["ok"] and args.runs == evidence["requiredRuns"]
        return status
    finally:
        evidence["endedAt"] = datetime.now(UTC).isoformat()
        evidence["final"] = snapshot()
        evidence_path = Path(args.evidence)
        if not evidence_path.is_absolute():
            evidence_path = ROOT / evidence_path
        evidence_path.parent.mkdir(parents=True, exist_ok=True)
        evidence_path.write_text(json.dumps(evidence, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
        print(f"Wrote {evidence_path.relative_to(ROOT)}")


if __name__ == "__main__":
    raise SystemExit(main())
