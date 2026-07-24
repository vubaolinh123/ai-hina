from __future__ import annotations

import asyncio
import struct
import sys
import tempfile
import threading
import time
import unittest
import wave
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace


SPEECH_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SPEECH_ROOT / "src"))

from hina_speech import (  # noqa: E402
    DEFAULT_TTS_CODEC_REVISION,
    DEFAULT_TTS_MODEL_REVISION,
    DEFAULT_TTS_VOICE,
    SpeechOutputService,
    TtsConfig,
    TtsError,
    TtsPcmChunk,
    TtsSynthesis,
    VieneuTtsProvider,
    normalize_tts_text,
    pcm16_to_wav,
    split_tts_chunks,
)


CORRELATION_ID = "11111111-1111-4111-8111-111111111111"
SESSION_ID = "22222222-2222-4222-8222-222222222222"
UTTERANCE_ID = "33333333-3333-4333-8333-333333333333"


def _allow(payload: dict[str, object]) -> dict[str, object]:
    return {"decision": "allow", "sanitizedText": payload["text"]}


def _synthesis(chunks: tuple[str, ...]) -> TtsSynthesis:
    cursor = 0.0
    output: list[TtsPcmChunk] = []
    for text in chunks:
        pcm = struct.pack("<" + "h" * 480, *([500] * 480))
        output.append(
            TtsPcmChunk(
                text=text,
                pcm16=pcm,
                start_seconds=cursor,
                end_seconds=cursor + 0.01,
            )
        )
        cursor += 0.01
    return TtsSynthesis(
        sample_rate_hz=48_000,
        voice=DEFAULT_TTS_VOICE,
        chunks=tuple(output),
        first_chunk_milliseconds=4.0,
        processing_milliseconds=8.0,
    )


class _FakeProvider:
    def __init__(self, *, block: bool = False) -> None:
        self.calls = 0
        self.chunks: tuple[str, ...] = ()
        self.block = block
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.closed = False

    async def status(self) -> dict[str, object]:
        return {"available": not self.closed, "modelLoaded": False, "modelCached": True}

    async def synthesize(
        self,
        chunks: tuple[str, ...],
        cancel_event: threading.Event,
    ) -> TtsSynthesis:
        self.calls += 1
        self.chunks = chunks
        self.started.set()
        if self.block:
            while not cancel_event.is_set() and not self.release.is_set():
                await asyncio.sleep(0.005)
        if cancel_event.is_set():
            raise TtsError("E_TTS_CANCELLED", "cancelled")
        return _synthesis(chunks)

    async def close(self) -> None:
        self.closed = True


class _FakeVieNeu:
    def __init__(self, *, block: bool = False) -> None:
        self.calls: list[dict[str, object]] = []
        self.block = block
        self.started = threading.Event()
        self.release = threading.Event()

    def infer_stream(self, text: str, **kwargs):
        self.calls.append({"text": text, **kwargs})
        self.started.set()
        if self.block:
            self.release.wait(timeout=2)
        yield [0.0, 0.5, -0.5]


class TextAndAudioTests(unittest.TestCase):
    def test_normalization_is_nfc_and_speaks_only_url_hostname(self) -> None:
        value = normalize_tts_text(
            "Xin cha\u0300o 😊 https://example.com/private?q=secret"
        )
        self.assertEqual(value, "Xin chào vui vẻ đường dẫn example chấm com")
        self.assertNotIn("private", value)
        self.assertNotIn("secret", value)

    def test_chunking_is_bounded_and_lossless_for_words(self) -> None:
        text = "Một câu ngắn. " + "từ " * 100
        chunks = split_tts_chunks(text.strip(), max_characters=64)
        self.assertTrue(all(0 < len(chunk) <= 64 for chunk in chunks))
        self.assertEqual(" ".join(chunks).split(), text.split())

    def test_pcm16_wav_is_mono_and_uses_requested_sample_rate(self) -> None:
        wav = pcm16_to_wav(struct.pack("<hhh", 1, -2, 3), sample_rate_hz=48_000)
        with wave.open(BytesIO(wav), "rb") as handle:
            self.assertEqual(handle.getnchannels(), 1)
            self.assertEqual(handle.getsampwidth(), 2)
            self.assertEqual(handle.getframerate(), 48_000)
            self.assertEqual(handle.getnframes(), 3)

    def test_config_rejects_gpu_without_resource_lease(self) -> None:
        with self.assertRaisesRegex(TtsError, "ResourceLease"):
            TtsConfig(device="cuda")


class SpeechOutputServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_moderates_entire_text_before_provider_and_returns_real_wav(self) -> None:
        provider = _FakeProvider()
        moderation_payloads: list[dict[str, object]] = []

        def moderator(payload: dict[str, object]) -> dict[str, object]:
            moderation_payloads.append(payload)
            return {"decision": "allow", "sanitizedText": "Nội dung đã lọc."}

        service = SpeechOutputService(TtsConfig(), provider, moderator=moderator)
        result = await service.synthesize(
            "Nội dung gốc.",
            utterance_id=UTTERANCE_ID,
            correlation_id=CORRELATION_ID,
            session_id=SESSION_ID,
            source="owner.console",
        )

        self.assertEqual(provider.calls, 1)
        self.assertEqual(provider.chunks, ("Nội dung đã lọc.",))
        self.assertEqual(moderation_payloads[0]["surface"], "pre_tts")
        self.assertTrue(result["audioWav"].startswith(b"RIFF"))
        self.assertNotIn("text", result)
        self.assertEqual(result["retention"]["generatedAudio"], False)

    async def test_blocked_text_never_reaches_provider(self) -> None:
        provider = _FakeProvider()
        service = SpeechOutputService(
            TtsConfig(),
            provider,
            moderator=lambda _payload: {"decision": "block", "reasonCode": "unsafe"},
        )
        with self.assertRaisesRegex(TtsError, "moderation blocked"):
            await service.synthesize(
                "không được phát",
                utterance_id=UTTERANCE_ID,
                correlation_id=CORRELATION_ID,
                session_id=None,
                source="owner.console",
            )
        self.assertEqual(provider.calls, 0)

    async def test_cancel_interrupts_active_utterance(self) -> None:
        provider = _FakeProvider(block=True)
        service = SpeechOutputService(TtsConfig(), provider, moderator=_allow)
        task = asyncio.create_task(
            service.synthesize(
                "Một câu đang phát.",
                utterance_id=UTTERANCE_ID,
                correlation_id=CORRELATION_ID,
                session_id=SESSION_ID,
                source="owner.console",
            )
        )
        await provider.started.wait()
        cancelled = await service.cancel(UTTERANCE_ID)
        self.assertEqual(cancelled, {"utteranceId": UTTERANCE_ID, "cancelled": True})
        with self.assertRaisesRegex(TtsError, "cancelled"):
            await task
        self.assertEqual((await service.status())["queue"]["activeUtterances"], 0)

    async def test_bounded_queue_rejects_second_request(self) -> None:
        provider = _FakeProvider(block=True)
        service = SpeechOutputService(
            TtsConfig(max_pending_syntheses=1),
            provider,
            moderator=_allow,
        )
        first = asyncio.create_task(
            service.synthesize(
                "Lượt thứ nhất.",
                utterance_id=UTTERANCE_ID,
                correlation_id=CORRELATION_ID,
                session_id=None,
                source="owner.console",
            )
        )
        await provider.started.wait()
        with self.assertRaisesRegex(TtsError, "queue is full"):
            await service.synthesize(
                "Lượt thứ hai.",
                utterance_id="44444444-4444-4444-8444-444444444444",
                correlation_id=CORRELATION_ID,
                session_id=None,
                source="owner.console",
            )
        provider.release.set()
        await first

    async def test_failure_report_has_ids_but_no_input_text(self) -> None:
        reports: list[dict[str, str]] = []

        class FailingProvider(_FakeProvider):
            async def synthesize(self, chunks, cancel_event):
                raise TtsError("E_TTS_INFERENCE", "secret text")

        service = SpeechOutputService(
            TtsConfig(),
            FailingProvider(),
            moderator=_allow,
            on_error=reports.append,
        )
        with self.assertRaises(TtsError):
            await service.synthesize(
                "private input",
                utterance_id=UTTERANCE_ID,
                correlation_id=CORRELATION_ID,
                session_id=SESSION_ID,
                source="owner.console",
            )
        self.assertEqual(reports[0]["errorCode"], "E_TTS_INFERENCE")
        self.assertNotIn("private input", repr(reports))
        self.assertNotIn("secret text", repr(reports))


class VieneuProviderTests(unittest.IsolatedAsyncioTestCase):
    async def test_provider_downloads_exact_revisions_and_disables_cloning(self) -> None:
        downloads: list[dict[str, object]] = []
        fake_model = _FakeVieNeu()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)

            def downloader(**kwargs):
                downloads.append(kwargs)
                directory = root / ("model" if len(downloads) == 1 else "codec")
                directory.mkdir()
                return str(directory)

            factory_calls: list[tuple[Path, Path, TtsConfig]] = []

            def factory(model_path: Path, codec_path: Path, config: TtsConfig):
                factory_calls.append((model_path, codec_path, config))
                return fake_model

            provider = VieneuTtsProvider(
                TtsConfig(model_cache=root),
                snapshot_downloader=downloader,
                sdk_factory=factory,
            )
            result = await provider.synthesize(("Xin chào.",), threading.Event())
            await provider.close()

        self.assertEqual(downloads[0]["revision"], DEFAULT_TTS_MODEL_REVISION)
        self.assertEqual(downloads[1]["revision"], DEFAULT_TTS_CODEC_REVISION)
        self.assertEqual(downloads[0]["local_files_only"], False)
        self.assertEqual(len(factory_calls), 1)
        self.assertEqual(fake_model.calls[0]["voice"], DEFAULT_TTS_VOICE)
        self.assertEqual(fake_model.calls[0]["apply_watermark"], True)
        self.assertGreater(len(result.pcm16), 0)

    async def test_provider_serializes_native_inference_and_skips_cancelled_waiter(self) -> None:
        fake_model = _FakeVieNeu(block=True)
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            snapshot = root / "snapshot"
            snapshot.mkdir()
            provider = VieneuTtsProvider(
                TtsConfig(model_cache=root),
                snapshot_downloader=lambda **_kwargs: str(snapshot),
                sdk_factory=lambda *_args: fake_model,
            )
            first_cancel = threading.Event()
            second_cancel = threading.Event()
            first = asyncio.create_task(provider.synthesize(("Một.",), first_cancel))
            await asyncio.to_thread(fake_model.started.wait, 1)
            second = asyncio.create_task(provider.synthesize(("Hai.",), second_cancel))
            await asyncio.sleep(0.02)
            self.assertEqual(len(fake_model.calls), 1)
            second_cancel.set()
            fake_model.release.set()
            await first
            with self.assertRaisesRegex(TtsError, "cancelled"):
                await second
            self.assertEqual(len(fake_model.calls), 1)
            await provider.close()

    async def test_timeout_keeps_provider_draining_until_native_worker_exits(self) -> None:
        fake_model = _FakeVieNeu(block=True)
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            snapshot = root / "snapshot"
            snapshot.mkdir()
            provider = VieneuTtsProvider(
                TtsConfig(
                    model_cache=root,
                    request_timeout_seconds=5.0,
                ),
                snapshot_downloader=lambda **_kwargs: str(snapshot),
                sdk_factory=lambda *_args: fake_model,
            )
            provider.config = SimpleNamespace(
                **{
                    **{
                        field: getattr(provider.config, field)
                        for field in provider.config.__dataclass_fields__
                    },
                    "request_timeout_seconds": 0.02,
                }
            )
            with self.assertRaisesRegex(TtsError, "timed out"):
                await provider.synthesize(("Xin chào.",), threading.Event())
            self.assertTrue((await provider.status())["drainingTimedOutInference"])
            fake_model.release.set()
            for _ in range(100):
                if not (await provider.status())["drainingTimedOutInference"]:
                    break
                await asyncio.sleep(0.005)
            self.assertFalse((await provider.status())["drainingTimedOutInference"])
            await provider.close()


if __name__ == "__main__":
    unittest.main()
