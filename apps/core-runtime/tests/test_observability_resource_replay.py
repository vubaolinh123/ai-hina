from __future__ import annotations

import asyncio
import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
APP_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages" / "contracts" / "src"))
sys.path.insert(0, str(ROOT / "packages" / "testkit" / "src"))
sys.path.insert(0, str(APP_ROOT / "src"))

from hina_core.runtime import (  # noqa: E402
    FakeResourceScheduler,
    JsonlErrorLogger,
    JsonlTraceWriter,
    MetricRegistry,
    PrimitiveError,
    ResourceInventory,
    ResourceRequest,
    RuntimeErrorCode,
    TurnReplayHarness,
)
from hina_core.runtime.error_report import collect_error_report  # noqa: E402
from hina_core.runtime.observability_demo import run_observability_demo  # noqa: E402
from hina_testkit import (  # noqa: E402
    FakeMemoryProvider,
    FakeModelProvider,
    FakeProviderError,
    FakeSpeechProvider,
    FakeToolProvider,
)


FIXTURE = ROOT / "packages" / "contracts" / "fixtures" / "golden" / "turn.media.echo.json"


class ObservabilityTests(unittest.TestCase):
    def test_metric_series_and_labels_are_hard_bounded(self) -> None:
        metrics = MetricRegistry(max_series=2)
        metrics.increment("hina_requests_total", labels={"status": "ok"})
        metrics.increment("hina_requests_total", labels={"status": "error"})
        self.assertEqual(metrics.series_count, 2)
        with self.assertRaises(PrimitiveError) as raised:
            metrics.increment("hina_requests_total", labels={"status": "third"})
        self.assertEqual(raised.exception.code, RuntimeErrorCode.METRIC_CAPACITY)
        with self.assertRaises(PrimitiveError) as raised:
            metrics.increment("hina_other_total", labels={"user_id": "viewer-1"})
        self.assertEqual(raised.exception.code, RuntimeErrorCode.OBSERVABILITY_INVALID)

    def test_nested_traces_redact_secrets_and_logging_failure_never_masks_error(self) -> None:
        with tempfile.TemporaryDirectory(dir=APP_ROOT) as temporary_directory:
            directory = Path(temporary_directory)
            trace_path = directory / "traces.jsonl"
            metrics = MetricRegistry()
            traces = JsonlTraceWriter(trace_path, metrics=metrics)
            with traces.span(
                "turn.replay",
                correlation_id="99999999-9999-4999-8999-999999999999",
                attributes={"model": "authorization=trace-secret"},
            ):
                with traces.span(
                    "model.generate",
                    correlation_id="99999999-9999-4999-8999-999999999999",
                    attributes={"provider": "fake"},
                ):
                    pass
            text = trace_path.read_text(encoding="utf-8")
            records = [json.loads(line) for line in text.splitlines()]
            self.assertEqual(len(records), 2)
            self.assertEqual(records[0]["parentSpanId"], records[1]["spanId"])
            self.assertNotIn("trace-secret", text)
            self.assertIn("<redacted>", text)
            self.assertEqual(metrics.series_count, 4)

            class ExpectedFailure(Exception):
                pass

            with self.assertRaises(ExpectedFailure):
                with JsonlTraceWriter(directory).span(
                    "failure.test",
                    correlation_id="99999999-9999-4999-8999-999999999999",
                ):
                    raise ExpectedFailure("original")

    def test_error_report_is_bounded_and_redacts_again(self) -> None:
        with tempfile.TemporaryDirectory(dir=APP_ROOT) as temporary_directory:
            directory = Path(temporary_directory)
            log_path = directory / "errors.jsonl"
            output = directory / "report.json"
            logger = JsonlErrorLogger(log_path, build_commit="test-sha")
            for index in range(3):
                logger.log_error(
                    PrimitiveError(RuntimeErrorCode.OPERATION_FAILED, f"api_key=secret-{index}"),
                    component="test",
                    operation="report",
                    correlation_id=f"00000000-0000-4000-8000-{index:012d}",
                    context={"authorization": f"Bearer secret-{index}"},
                )
            with log_path.open("a", encoding="utf-8") as handle:
                handle.write("not-json\n")
            report = collect_error_report(
                [log_path],
                output,
                max_records=2,
                build_commit="test-sha",
            )
            report_text = output.read_text(encoding="utf-8")
            self.assertEqual(report["recordCount"], 2)
            self.assertEqual(report["invalidLinesSkipped"], 1)
            self.assertNotIn("secret-", report_text)
            self.assertIn("<redacted>", report_text)

            failed_record = JsonlErrorLogger(directory).log_error(
                PrimitiveError(RuntimeErrorCode.OPERATION_FAILED, "original failure"),
                component="test",
                operation="logging-failure",
                correlation_id="not-a-secret-token",
            )
            self.assertTrue(failed_record["loggingFailed"])
            self.assertEqual(
                failed_record["correlationId"],
                "00000000-0000-0000-0000-000000000000",
            )


class ResourceAndReplayTests(unittest.IsolatedAsyncioTestCase):
    async def test_resource_headroom_admission_release_and_expiry(self) -> None:
        metrics = MetricRegistry()
        scheduler = FakeResourceScheduler(
            ResourceInventory(8_192, 16_384, 2_048),
            metrics=metrics,
        )
        lease = await scheduler.acquire(
            ResourceRequest(owner="model", vram_mib=4_096, ram_mib=2_048)
        )
        snapshot = await scheduler.snapshot()
        self.assertEqual(snapshot.reserved_vram_headroom_mib, 2_048)
        self.assertGreaterEqual(
            snapshot.reserved_vram_headroom_mib + snapshot.available_vram_mib,
            2_048,
        )
        with self.assertRaises(PrimitiveError) as raised:
            await scheduler.acquire(
                ResourceRequest(owner="vision", vram_mib=3_072, ram_mib=1)
            )
        self.assertEqual(raised.exception.code, RuntimeErrorCode.RESOURCE_CAPACITY)
        self.assertTrue(await lease.release())
        self.assertFalse(await lease.release())

        expiring = await scheduler.acquire(
            ResourceRequest(
                owner="short-task",
                vram_mib=1,
                ttl_seconds=0.01,
            )
        )
        await asyncio.sleep(0.03)
        self.assertEqual((await scheduler.snapshot()).active_leases, 0)
        with self.assertRaises(PrimitiveError) as raised:
            expiring.assert_active()
        self.assertEqual(raised.exception.code, RuntimeErrorCode.RESOURCE_LEASE_EXPIRED)

    async def test_fake_providers_and_duplicate_turn_replay_are_deterministic(self) -> None:
        with tempfile.TemporaryDirectory(dir=APP_ROOT) as temporary_directory:
            trace_path = Path(temporary_directory) / "traces.jsonl"
            model = FakeModelProvider()
            speech = FakeSpeechProvider()
            metrics = MetricRegistry()
            harness = TurnReplayHarness(
                model,
                speech,
                traces=JsonlTraceWriter(trace_path, metrics=metrics),
                metrics=metrics,
            )
            envelope = json.loads(FIXTURE.read_text(encoding="utf-8"))
            first = await harness.replay(envelope)
            duplicate = await harness.replay(envelope)
            self.assertEqual(str(first.source), "executed")
            self.assertEqual(str(duplicate.source), "replayed")
            self.assertEqual(first.response_text, duplicate.response_text)
            self.assertEqual(model.call_count, 1)
            self.assertEqual(speech.call_count, 1)
            self.assertEqual(first.audio, duplicate.audio)

            conflicting = copy.deepcopy(envelope)
            conflicting["payload"]["message"] = "different replay"
            with self.assertRaises(PrimitiveError) as raised:
                await harness.replay(conflicting)
            self.assertEqual(raised.exception.code, RuntimeErrorCode.REPLAY_CONFLICT)

            memory = FakeMemoryProvider()
            with self.assertRaises(FakeProviderError) as raised:
                await memory.remember("preference", {"language": "vi"}, consent=False)
            self.assertEqual(raised.exception.code, "E_CONSENT_REQUIRED")
            await memory.remember("preference", {"language": "vi"}, consent=True)
            self.assertEqual(await memory.recall("preference"), {"language": "vi"})

            tools = FakeToolProvider()
            self.assertEqual(
                await tools.invoke("add", {"left": 2, "right": 3}),
                {"value": 5},
            )
            with self.assertRaises(FakeProviderError) as raised:
                await tools.invoke("shell", {"command": "whoami"})
            self.assertEqual(raised.exception.code, "E_FAKE_TOOL_UNKNOWN")

    async def test_visible_demo_produces_safe_artifacts(self) -> None:
        with tempfile.TemporaryDirectory(dir=APP_ROOT) as temporary_directory:
            directory = Path(temporary_directory)
            result = await run_observability_demo(
                directory / "traces.jsonl",
                directory / "errors.jsonl",
                directory / "metrics.json",
                directory / "report.json",
            )
            self.assertEqual(result["status"], "ok")
            self.assertEqual(result["turn"]["firstSource"], "executed")
            self.assertEqual(result["turn"]["duplicateSource"], "replayed")
            self.assertEqual(result["turn"]["modelCalls"], 1)
            self.assertEqual(result["turn"]["speechCalls"], 1)
            self.assertEqual(result["fakeProviders"]["consentError"], "E_CONSENT_REQUIRED")
            self.assertGreaterEqual(result["resources"]["physicalHeadroomMiB"], 2_048)
            self.assertEqual(result["resources"]["capacityError"], "E_RESOURCE_CAPACITY")
            self.assertEqual(result["resources"]["finalActiveLeases"], 0)
            self.assertEqual(result["observability"]["traceRecords"], 3)
            self.assertEqual(result["observability"]["errorRecords"], 1)
            self.assertTrue(result["observability"]["secretRedacted"])


if __name__ == "__main__":
    unittest.main()
