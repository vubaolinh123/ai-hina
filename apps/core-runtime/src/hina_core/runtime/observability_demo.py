from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
from typing import Any

from hina_testkit import (
    FakeMemoryProvider,
    FakeModelProvider,
    FakeProviderError,
    FakeSpeechProvider,
    FakeToolProvider,
)

from .error_log import JsonlErrorLogger
from .error_report import collect_error_report
from .observability import JsonlTraceWriter, MetricRegistry
from .primitives import PrimitiveError
from .replay import TurnReplayHarness
from .resource import FakeResourceScheduler, ResourceInventory, ResourceRequest


ROOT = Path(__file__).resolve().parents[5]
FIXTURE = ROOT / "packages" / "contracts" / "fixtures" / "golden" / "turn.media.echo.json"
DEFAULT_TRACE = ROOT / "var" / "logs" / "m01-s6-traces.jsonl"
DEFAULT_ERROR = ROOT / "var" / "logs" / "m01-s6-errors.jsonl"
DEFAULT_METRICS = ROOT / "var" / "metrics" / "m01-s6-metrics.json"
DEFAULT_REPORT = ROOT / "var" / "reports" / "m01-s6-error-report.json"


async def run_observability_demo(
    trace_path: Path,
    error_path: Path,
    metrics_path: Path,
    report_path: Path,
) -> dict[str, Any]:
    for path in (trace_path, error_path, metrics_path, report_path):
        path.unlink(missing_ok=True)
    build_commit = os.environ.get("HINA_BUILD_COMMIT", "development")
    metrics = MetricRegistry(max_series=256)
    traces = JsonlTraceWriter(
        trace_path,
        metrics=metrics,
        build_commit=build_commit,
    )
    errors = JsonlErrorLogger(error_path, build_commit=build_commit)
    scheduler = FakeResourceScheduler(
        ResourceInventory(
            total_vram_mib=8_192,
            total_ram_mib=32_768,
            reserved_vram_headroom_mib=2_048,
        ),
        metrics=metrics,
    )
    model_lease = await scheduler.acquire(
        ResourceRequest(owner="fake-model", vram_mib=4_096, ram_mib=2_048)
    )
    speech_lease = await scheduler.acquire(
        ResourceRequest(owner="fake-speech", vram_mib=1_024, ram_mib=512)
    )
    active_snapshot = await scheduler.snapshot()

    envelope = json.loads(FIXTURE.read_text(encoding="utf-8"))
    model = FakeModelProvider()
    speech = FakeSpeechProvider()
    memory = FakeMemoryProvider()
    tools = FakeToolProvider()
    harness = TurnReplayHarness(
        model,
        speech,
        traces=traces,
        metrics=metrics,
    )
    first = await harness.replay(envelope)
    duplicate = await harness.replay(envelope)

    try:
        await memory.remember("owner.preference", {"language": "vi"}, consent=False)
    except FakeProviderError as exc:
        consent_error = exc.code
    else:
        consent_error = "MISSING_EXPECTED_CONSENT_ERROR"
    await memory.remember("owner.preference", {"language": "vi"}, consent=True)
    recalled = await memory.recall("owner.preference")
    tool_result = await tools.invoke("add", {"left": 20, "right": 22})

    try:
        await scheduler.acquire(
            ResourceRequest(owner="fake-vision", vram_mib=2_048, ram_mib=1_024)
        )
    except PrimitiveError as exc:
        capacity_error = str(exc.code)
        errors.log_error(
            exc,
            component="runtime.resource",
            operation="acquire",
            correlation_id=envelope["correlationId"],
            session_id=envelope.get("sessionId"),
            turn_id=envelope.get("turnId"),
            context={
                "owner": "fake-vision",
                "authorization": "Bearer demo-resource-secret",
            },
        )
    else:
        capacity_error = "MISSING_EXPECTED_CAPACITY_ERROR"

    await speech_lease.release()
    await model_lease.release()
    final_snapshot = await scheduler.snapshot()

    metrics_path.parent.mkdir(parents=True, exist_ok=True)
    metrics_path.write_text(
        json.dumps(metrics.as_json(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    report = collect_error_report(
        [error_path],
        report_path,
        max_records=100,
        build_commit=build_commit,
    )
    trace_records = (
        [json.loads(line) for line in trace_path.read_text(encoding="utf-8").splitlines()]
        if trace_path.exists()
        else []
    )
    report_text = report_path.read_text(encoding="utf-8")
    return {
        "status": "ok",
        "turn": {
            "response": first.response_text,
            "audioBytes": len(first.audio),
            "audioEncoding": first.audio_encoding,
            "firstSource": str(first.source),
            "duplicateSource": str(duplicate.source),
            "modelCalls": model.call_count,
            "speechCalls": speech.call_count,
        },
        "fakeProviders": {
            "consentError": consent_error,
            "memory": recalled,
            "toolAdd": tool_result["value"],
        },
        "resources": {
            "activeLeases": active_snapshot.active_leases,
            "usedVramMiB": active_snapshot.used_vram_mib,
            "reservedHeadroomMiB": active_snapshot.reserved_vram_headroom_mib,
            "physicalHeadroomMiB": (
                active_snapshot.reserved_vram_headroom_mib
                + active_snapshot.available_vram_mib
            ),
            "capacityError": capacity_error,
            "finalActiveLeases": final_snapshot.active_leases,
        },
        "observability": {
            "traceRecords": len(trace_records),
            "traceNames": [record["name"] for record in trace_records],
            "metricSeries": metrics.series_count,
            "errorRecords": report["recordCount"],
            "secretRedacted": "demo-resource-secret" not in report_text,
        },
        "artifacts": {
            "traces": str(trace_path),
            "errors": str(error_path),
            "metrics": str(metrics_path),
            "report": str(report_path),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the visible M01-S6 observability demo.")
    parser.add_argument("--traces", type=Path, default=DEFAULT_TRACE)
    parser.add_argument("--errors", type=Path, default=DEFAULT_ERROR)
    parser.add_argument("--metrics", type=Path, default=DEFAULT_METRICS)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args()
    result = asyncio.run(
        run_observability_demo(
            args.traces.resolve(),
            args.errors.resolve(),
            args.metrics.resolve(),
            args.report.resolve(),
        )
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
