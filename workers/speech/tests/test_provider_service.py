from __future__ import annotations

import asyncio
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace


SPEECH_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SPEECH_ROOT / "src"))

from hina_speech import (  # noqa: E402
    FasterWhisperProvider,
    SpeechConfig,
    SpeechError,
    SpeechInputService,
    SttResult,
    SttSegment,
    decode_and_normalize_wav,
)
from test_audio_vad import wav_bytes  # noqa: E402


CORRELATION_ID = "11111111-1111-4111-8111-111111111111"
SESSION_ID = "22222222-2222-4222-8222-222222222222"


class _FakeProvider:
    def __init__(self, *, block: bool = False) -> None:
        self.calls = 0
        self.block = block
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def status(self) -> dict[str, object]:
        return {
            "available": True,
            "modelLoaded": False,
            "modelCached": True,
        }

    async def transcribe(self, audio):
        self.calls += 1
        self.started.set()
        if self.block:
            await self.release.wait()
        return SttResult(
            text="xin chào Hina",
            language="vi",
            language_probability=0.99,
            duration_seconds=audio.duration_seconds,
            segments=(
                SttSegment(0.0, audio.duration_seconds, "xin chào Hina", 0.9),
            ),
        )

    async def unload(self) -> None:
        return None


class _FakeWhisperModel:
    def transcribe(self, samples, **kwargs):
        self.samples = samples
        self.kwargs = kwargs
        segment = SimpleNamespace(
            start=0.0,
            end=0.25,
            text=" xin chào ",
            no_speech_prob=0.01,
            avg_logprob=-0.1,
        )
        return [segment], SimpleNamespace(language_probability=0.97)


class _BlockingWhisperModel(_FakeWhisperModel):
    def __init__(self) -> None:
        self.calls = 0
        self.started = threading.Event()
        self.release = threading.Event()

    def transcribe(self, samples, **kwargs):
        self.calls += 1
        self.started.set()
        self.release.wait(timeout=5)
        return super().transcribe(samples, **kwargs)


class _FailingWhisperModel(_FakeWhisperModel):
    def transcribe(self, samples, **kwargs):
        raise RuntimeError("simulated device inference failure")


class _FakeLease:
    def __init__(self) -> None:
        self.release_calls = 0

    def assert_active(self) -> None:
        return None

    async def release(self) -> bool:
        self.release_calls += 1
        return True


class ProviderTests(unittest.IsolatedAsyncioTestCase):
    async def test_provider_lazily_loads_pinned_model_and_locks_vi_transcribe(self) -> None:
        created: dict[str, object] = {}

        def factory(model_id: str, **kwargs):
            created["model_id"] = model_id
            created["kwargs"] = kwargs
            model = _FakeWhisperModel()
            created["model"] = model
            return model

        with tempfile.TemporaryDirectory(dir=SPEECH_ROOT) as temporary_directory:
            config = SpeechConfig(
                model_cache=Path(temporary_directory),
                allow_download=False,
            )
            provider = FasterWhisperProvider(config, model_factory=factory)
            before = await provider.status()
            self.assertFalse(before["modelLoaded"])
            audio = decode_and_normalize_wav(wav_bytes(duration_seconds=0.25))
            result = await provider.transcribe(audio)
            self.assertEqual(result.text, "xin chào")
            self.assertEqual(created["model_id"], config.model_id)
            kwargs = created["kwargs"]
            self.assertEqual(kwargs["revision"], config.model_revision)
            self.assertTrue(kwargs["local_files_only"])
            transcribe_kwargs = created["model"].kwargs
            self.assertEqual(transcribe_kwargs["language"], "vi")
            self.assertEqual(transcribe_kwargs["task"], "transcribe")
            self.assertTrue(transcribe_kwargs["vad_filter"])
            self.assertFalse(transcribe_kwargs["condition_on_previous_text"])

    async def test_cuda_without_resource_lease_fails_or_uses_explicit_cpu_fallback(self) -> None:
        audio = decode_and_normalize_wav(wav_bytes(duration_seconds=0.25))
        blocked = FasterWhisperProvider(
            SpeechConfig(device="cuda", compute_type="float16", fallback_to_cpu=False),
            model_factory=lambda *_args, **_kwargs: _FakeWhisperModel(),
        )
        with self.assertRaises(SpeechError) as raised:
            await blocked.transcribe(audio)
        self.assertEqual(raised.exception.code, "E_STT_RESOURCE_LEASE")

        fallback = FasterWhisperProvider(
            SpeechConfig(device="cuda", compute_type="float16", fallback_to_cpu=True),
            model_factory=lambda *_args, **_kwargs: _FakeWhisperModel(),
        )
        result = await fallback.transcribe(audio)
        self.assertEqual(result.language, "vi")
        self.assertEqual((await fallback.status())["effectiveDevice"], "cpu")

    async def test_timeout_drains_native_worker_before_releasing_lease(self) -> None:
        model = _BlockingWhisperModel()
        lease = _FakeLease()
        config = SpeechConfig(
            device="cuda",
            compute_type="float16",
            fallback_to_cpu=False,
        )
        object.__setattr__(config, "request_timeout_seconds", 0.05)

        async def acquire_lease(_unload):
            return lease

        provider = FasterWhisperProvider(
            config,
            gpu_lease_factory=acquire_lease,
            model_factory=lambda *_args, **_kwargs: model,
        )
        audio = decode_and_normalize_wav(wav_bytes(duration_seconds=0.25))

        with self.assertRaises(SpeechError) as timed_out:
            await provider.transcribe(audio)
        self.assertEqual(timed_out.exception.code, "E_STT_TIMEOUT")
        self.assertTrue(model.started.is_set())
        self.assertEqual(lease.release_calls, 0)
        self.assertTrue((await provider.status())["drainingTimedOutInference"])

        with self.assertRaises(SpeechError) as draining:
            await provider.transcribe(audio)
        self.assertEqual(draining.exception.code, "E_STT_DRAINING")
        self.assertEqual(model.calls, 1)
        self.assertEqual(lease.release_calls, 0)

        model.release.set()
        await provider.close()
        self.assertEqual(lease.release_calls, 1)

    async def test_cpu_fallback_does_not_mask_cuda_retry_on_next_request(self) -> None:
        devices: list[str] = []
        leases: list[_FakeLease] = []

        def factory(_model_id: str, **kwargs):
            device = kwargs["device"]
            devices.append(device)
            return _FailingWhisperModel() if device == "cuda" else _FakeWhisperModel()

        async def acquire_lease(_unload):
            lease = _FakeLease()
            leases.append(lease)
            return lease

        provider = FasterWhisperProvider(
            SpeechConfig(device="cuda", compute_type="float16", fallback_to_cpu=True),
            gpu_lease_factory=acquire_lease,
            model_factory=factory,
        )
        audio = decode_and_normalize_wav(wav_bytes(duration_seconds=0.25))

        await provider.transcribe(audio)
        await provider.transcribe(audio)
        await provider.close()

        self.assertEqual(devices, ["cuda", "cpu", "cuda", "cpu"])
        self.assertEqual([lease.release_calls for lease in leases], [1, 1])


class SpeechServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_silence_never_calls_provider_and_returns_empty_final(self) -> None:
        provider = _FakeProvider()
        service = SpeechInputService(SpeechConfig(), provider)
        result = await service.transcribe_wav(
            wav_bytes(amplitude=0.0),
            correlation_id=CORRELATION_ID,
            session_id=SESSION_ID,
            source="owner.dev-console",
        )
        self.assertEqual(result["status"], "silence")
        self.assertFalse(result["speechDetected"])
        self.assertEqual(result["transcript"], "")
        self.assertEqual(provider.calls, 0)
        self.assertFalse(result["audio"]["rawAudioRetained"])

    async def test_speech_returns_partial_and_final_events_without_persistence(self) -> None:
        provider = _FakeProvider()
        service = SpeechInputService(SpeechConfig(), provider)
        result = await service.transcribe_wav(
            wav_bytes(),
            correlation_id=CORRELATION_ID,
            session_id=SESSION_ID,
            source="owner.dev-console",
        )
        self.assertEqual(result["transcript"], "xin chào Hina")
        self.assertEqual(provider.calls, 1)
        self.assertEqual(
            [event["type"] for event in result["events"]],
            ["SpeechStarted", "SpeechEnded", "TranscriptPartial", "TranscriptFinal"],
        )
        self.assertTrue(all(event["correlationId"] == CORRELATION_ID for event in result["events"]))
        self.assertNotIn("rawAudio", result)

    async def test_bounded_admission_rejects_excess_concurrency(self) -> None:
        provider = _FakeProvider(block=True)
        service = SpeechInputService(
            SpeechConfig(max_pending_transcriptions=1),
            provider,
        )
        first = asyncio.create_task(
            service.transcribe_wav(
                wav_bytes(),
                correlation_id=CORRELATION_ID,
                session_id=SESSION_ID,
                source="owner.dev-console",
            )
        )
        await provider.started.wait()
        with self.assertRaises(SpeechError) as raised:
            await service.transcribe_wav(
                wav_bytes(),
                correlation_id="33333333-3333-4333-8333-333333333333",
                session_id=SESSION_ID,
                source="owner.dev-console",
            )
        self.assertEqual(raised.exception.code, "E_STT_QUEUE_FULL")
        provider.release.set()
        await first

    async def test_failure_report_contains_ids_and_sizes_but_not_audio_or_transcript(self) -> None:
        reports: list[dict[str, str]] = []
        service = SpeechInputService(
            SpeechConfig(),
            _FakeProvider(),
            on_error=reports.append,
        )
        with self.assertRaises(SpeechError):
            await service.transcribe_wav(
                b"private raw audio bytes",
                correlation_id=CORRELATION_ID,
                session_id=SESSION_ID,
                source="owner.dev-console",
            )
        self.assertEqual(reports[0]["correlationId"], CORRELATION_ID)
        encoded = repr(reports)
        self.assertNotIn("private raw audio bytes", encoded)
        self.assertNotIn("transcript", encoded.lower())


class ConfigTests(unittest.TestCase):
    def test_language_translation_and_retention_cannot_be_enabled(self) -> None:
        with self.assertRaises(SpeechError):
            SpeechConfig(language="en")
        with self.assertRaises(SpeechError):
            SpeechConfig(task="translate")
        with self.assertRaises(SpeechError):
            SpeechConfig(raw_audio_retention=True)


if __name__ == "__main__":
    unittest.main()
