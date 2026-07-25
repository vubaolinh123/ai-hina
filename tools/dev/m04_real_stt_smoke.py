from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from hina_speech import (
    FasterWhisperProvider,
    MoonshineProvider,
    SpeechConfig,
    decode_and_normalize_wav,
)


ROOT = Path(__file__).resolve().parents[2]


async def run(wav_path: Path) -> dict[str, object]:
    config = SpeechConfig.from_env(root=ROOT)
    audio = decode_and_normalize_wav(wav_path.read_bytes())
    provider = (
        MoonshineProvider(config)
        if config.provider == "moonshine"
        else FasterWhisperProvider(config)
    )
    try:
        result = await provider.transcribe(audio)
        status = await provider.status()
    finally:
        await provider.unload()
    return {
        "provider": config.provider,
        "model": config.model_id,
        "revision": config.model_revision,
        "device": status["effectiveDevice"],
        "language": result.language,
        "transcript": result.text,
        "segments": len(result.segments),
        "durationSeconds": round(result.duration_seconds, 3),
        "modelLoadedDuringInference": True,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run one real M04 STT provider inference.")
    parser.add_argument("wav", type=Path)
    args = parser.parse_args()
    resolved = args.wav.resolve()
    if not resolved.is_file():
        raise FileNotFoundError(resolved)
    print(json.dumps(asyncio.run(run(resolved)), ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
