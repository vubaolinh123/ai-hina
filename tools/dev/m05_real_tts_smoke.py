from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from uuid import uuid4

from hina_safety import AuditTrail, CapabilityManifest, SafetyPolicyService
from hina_speech import (
    F5TtsProvider,
    OmniVoiceTtsProvider,
    SpeechOutputService,
    TtsConfig,
    VieneuTtsProvider,
)


ROOT = Path(__file__).resolve().parents[2]


async def run(text: str, output: Path, *, iterations: int = 1) -> dict[str, object]:
    config = TtsConfig.from_env(root=ROOT)
    output.parent.mkdir(parents=True, exist_ok=True)
    safety = SafetyPolicyService(
        CapabilityManifest.load(
            ROOT / "packages" / "safety-policy" / "manifests" / "default.v1.json"
        ),
        AuditTrail(
            output.parent / "m05-real-tts-audit.jsonl",
            build_commit="m05-real-tts-smoke",
        ),
    )
    if config.provider == "f5-tts":
        provider = F5TtsProvider(config)
    elif config.provider == "omnivoice":
        provider = OmniVoiceTtsProvider(config)
    else:
        provider = VieneuTtsProvider(config)
    service = SpeechOutputService(
        config,
        provider,
        moderator=safety.moderate,
    )
    runs: list[dict[str, object]] = []
    wav = b""
    try:
        for index in range(iterations):
            result = await service.synthesize(
                text,
                utterance_id=str(uuid4()),
                correlation_id=str(uuid4()),
                session_id=str(uuid4()),
                source="owner.console",
            )
            wav = result.pop("audioWav")
            status = await service.status()
            runs.append(
                {
                    "iteration": index + 1,
                    "durationSeconds": result["durationSeconds"],
                    "firstChunkMilliseconds": result["firstChunkMilliseconds"],
                    "processingMilliseconds": result["processingMilliseconds"],
                    "speakingRate": result["speakingRate"],
                    "providerTelemetry": {
                        key: status["provider"].get(key)
                        for key in (
                            "modelBaselineAllocatedMiB",
                            "lastPeakAllocatedMiB",
                            "lastPeakReservedMiB",
                            "lastPostAllocatedMiB",
                            "warmRequestCount",
                            "recycleRequired",
                            "asrLoaded",
                        )
                        if key in status["provider"]
                    },
                }
            )
        output.write_bytes(wav)
    finally:
        await service.close()
    last_run = runs[-1]
    return {
        "provider": config.provider,
        "providerVersion": config.public_status()["providerVersion"],
        "model": config.model_id,
        "revision": config.model_revision,
        "audioDecoder": (
            config.vocoder_id
            if config.provider == "f5-tts"
            else config.codec_id
            if config.provider == "vieneu"
            else "OmniVoice Higgs Audio V2 tokenizer"
        ),
        "audioDecoderRevision": (
            config.vocoder_revision
            if config.provider == "f5-tts"
            else config.codec_revision
            if config.provider == "vieneu"
            else config.model_revision
        ),
        "device": status["provider"]["effectiveDevice"],
        "precision": status["provider"]["effectivePrecision"],
        "voice": result["voice"],
        "sampleRateHz": result["sampleRateHz"],
        "durationSeconds": last_run["durationSeconds"],
        "firstChunkMilliseconds": last_run["firstChunkMilliseconds"],
        "processingMilliseconds": last_run["processingMilliseconds"],
        "providerTelemetry": last_run["providerTelemetry"],
        "iterations": iterations,
        "runs": runs,
        "eventCount": len(result["events"]),
        "output": str(output),
        "audioBytes": output.stat().st_size,
        "retainedByRuntime": False,
        "smokeArtifactWrittenByOwnerTool": True,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run one real moderated M05 local TTS inference."
    )
    parser.add_argument(
        "--text",
        default="Xin chào, mình là Hina. Đây là bài kiểm tra giọng nói tiếng Việt.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "var" / "tmp" / "m05-real-tts" / "hina-smoke.wav",
    )
    parser.add_argument("--iterations", type=int, default=1)
    args = parser.parse_args()
    if not 1 <= args.iterations <= 20:
        raise ValueError("iterations must be between 1 and 20")
    output = args.output.resolve()
    allowed = (ROOT / "var" / "tmp").resolve()
    if allowed not in output.parents:
        raise ValueError("smoke output must stay under var/tmp")
    print(
        json.dumps(
            asyncio.run(run(args.text, output, iterations=args.iterations)),
            ensure_ascii=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
