from __future__ import annotations

import argparse
import json
import re
import unicodedata
from difflib import SequenceMatcher
from pathlib import Path

from faster_whisper import WhisperModel


ROOT = Path(__file__).resolve().parents[2]
MODEL_ID = "Systran/faster-whisper-large-v3"
MODEL_REVISION = "edaa852ec7e145841d8ffdb056a99866b5f0a478"


def _normalized(value: str) -> str:
    value = unicodedata.normalize("NFC", value).casefold()
    return " ".join(re.findall(r"[\wÀ-ỹđ]+", value, flags=re.UNICODE))


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Transcribe a generated TTS WAV on CUDA and reject unintelligible output."
    )
    parser.add_argument("wav", type=Path)
    parser.add_argument("--expected", required=True)
    parser.add_argument("--minimum-similarity", type=float, default=0.55)
    args = parser.parse_args()
    wav = args.wav.resolve()
    if not wav.is_file():
        raise FileNotFoundError(wav)
    if not 0.0 <= args.minimum_similarity <= 1.0:
        raise ValueError("minimum similarity must be between zero and one")

    model = WhisperModel(
        MODEL_ID,
        device="cuda",
        compute_type="float16",
        download_root=str(ROOT / "var" / "cache" / "models" / "faster-whisper"),
        local_files_only=False,
        revision=MODEL_REVISION,
    )
    segments, info = model.transcribe(
        str(wav),
        language="vi",
        task="transcribe",
        beam_size=5,
        temperature=0,
        condition_on_previous_text=False,
        vad_filter=True,
    )
    transcript = " ".join(segment.text.strip() for segment in segments if segment.text.strip())
    expected = _normalized(args.expected)
    actual = _normalized(transcript)
    similarity = SequenceMatcher(a=expected, b=actual).ratio()
    result = {
        "model": MODEL_ID,
        "revision": MODEL_REVISION,
        "device": "cuda",
        "language": info.language,
        "languageProbability": round(float(info.language_probability), 4),
        "expected": args.expected,
        "transcript": transcript,
        "similarity": round(similarity, 4),
        "minimumSimilarity": args.minimum_similarity,
        "passed": similarity >= args.minimum_similarity,
    }
    print(json.dumps(result, ensure_ascii=True))
    return 0 if result["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
