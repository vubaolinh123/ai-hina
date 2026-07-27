from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from uuid import uuid4

from hina_safety import AuditTrail, CapabilityManifest, SafetyPolicyService
from hina_speech import (
    F5TtsProvider,
    SpeechOutputService,
    TtsConfig,
    VieneuTtsProvider,
    VoxCpm2TtsProvider,
)


ROOT = Path(__file__).resolve().parents[2]


async def run(text: str, output: Path) -> dict[str, object]:
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
    elif config.provider == "voxcpm2":
        provider = VoxCpm2TtsProvider(config)
    else:
        provider = VieneuTtsProvider(config)
    service = SpeechOutputService(
        config,
        provider,
        moderator=safety.moderate,
    )
    try:
        result = await service.synthesize(
            text,
            utterance_id=str(uuid4()),
            correlation_id=str(uuid4()),
            session_id=str(uuid4()),
            source="owner.console",
        )
        wav = result.pop("audioWav")
        output.write_bytes(wav)
        status = await service.status()
    finally:
        await service.close()
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
            else "VoxCPM2 AudioVAE V2"
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
        "durationSeconds": result["durationSeconds"],
        "firstChunkMilliseconds": result["firstChunkMilliseconds"],
        "processingMilliseconds": result["processingMilliseconds"],
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
    args = parser.parse_args()
    output = args.output.resolve()
    allowed = (ROOT / "var" / "tmp").resolve()
    if allowed not in output.parents:
        raise ValueError("smoke output must stay under var/tmp")
    print(json.dumps(asyncio.run(run(args.text, output)), ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
