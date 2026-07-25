"""Audit owner-provided MP3 clips and build a VieNeu reference profile.

VieNeu-TTS v3 Turbo does not fine-tune its base weights from a folder of MP3s.
It enrolls one short reference (up to eight seconds) and reuses the resulting
speaker embedding/reference codes. This tool therefore:

* audits every MP3 in ``voice_demo`` with ffprobe and SHA-256;
* chooses the longest clean clip that fits VieNeu's eight-second limit;
* converts that clip to a deterministic 16 kHz mono WAV; and
* writes an auditable manifest containing *all* supplied clips.

The manifest is intentionally generated under ``var/`` (ignored by git) so
raw owner voice data never becomes a repository artifact.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any


MAX_REFERENCE_SECONDS = 8.0
MIN_CLIP_SECONDS = 0.5
MAX_SOURCE_SECONDS = 300.0


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _probe(path: Path, ffprobe: str) -> dict[str, Any]:
    command = [
        ffprobe,
        "-v",
        "error",
        "-show_entries",
        "format=duration:stream=sample_rate,channels",
        "-of",
        "json",
        str(path),
    ]
    result = subprocess.run(command, check=True, capture_output=True, text=True)
    payload = json.loads(result.stdout)
    streams = payload.get("streams") or [{}]
    stream = streams[0]
    duration = float((payload.get("format") or {}).get("duration") or 0.0)
    return {
        "durationSeconds": round(duration, 6),
        "sampleRateHz": int(stream.get("sample_rate") or 0),
        "channels": int(stream.get("channels") or 0),
    }


def _normalize(source: Path, destination: Path, ffmpeg: str) -> None:
    command = [
        ffmpeg,
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-i",
        str(source),
        "-t",
        str(MAX_REFERENCE_SECONDS),
        "-ac",
        "1",
        "-ar",
        "16000",
        "-af",
        "loudnorm=I=-20:TP=-2:LRA=7",
        str(destination),
    ]
    subprocess.run(command, check=True)


def build_profile(input_dir: Path, output_dir: Path, *, force: bool = False) -> Path:
    ffmpeg = shutil.which("ffmpeg")
    ffprobe = shutil.which("ffprobe")
    if not ffmpeg or not ffprobe:
        raise RuntimeError("ffmpeg and ffprobe are required to prepare the voice profile")
    clips = sorted(input_dir.glob("*.mp3"), key=lambda item: item.name.casefold())
    if not clips:
        raise RuntimeError(f"no MP3 clips found in {input_dir}")

    entries: list[dict[str, Any]] = []
    eligible: list[tuple[float, Path]] = []
    for clip in clips:
        probe = _probe(clip, ffprobe)
        duration = float(probe["durationSeconds"])
        entry = {
            "file": clip.name,
            "sha256": _sha256(clip),
            **probe,
            "eligibleReference": MIN_CLIP_SECONDS <= duration <= MAX_REFERENCE_SECONDS,
        }
        entries.append(entry)
        if entry["eligibleReference"]:
            eligible.append((duration, clip))

    if not eligible:
        raise RuntimeError("no clip fits the VieNeu reference window (0.5-8 seconds)")
    eligible.sort(key=lambda item: (-item[0], item[1].name.casefold()))
    selected_duration, selected = eligible[0]

    output_dir.mkdir(parents=True, exist_ok=True)
    anchor = output_dir / "hina-profile-anchor.wav"
    manifest = output_dir / "hina-profile.json"
    if (anchor.exists() or manifest.exists()) and not force:
        raise FileExistsError(
            f"profile already exists under {output_dir}; pass --force to rebuild"
        )
    with tempfile.TemporaryDirectory(prefix="hina-voice-profile-") as temporary:
        temporary_anchor = Path(temporary) / anchor.name
        _normalize(selected, temporary_anchor, ffmpeg)
        shutil.copy2(temporary_anchor, anchor)

    profile = {
        "schemaVersion": 1,
        "provider": "vieneu",
        "modelReferenceLimitSeconds": MAX_REFERENCE_SECONDS,
        "sourceDirectory": str(input_dir),
        "clipCount": len(entries),
        "eligibleClipCount": len(eligible),
        "selectedReference": {
            "file": selected.name,
            "durationSeconds": selected_duration,
            "sha256": _sha256(selected),
            "anchor": anchor.name,
        },
        "clips": entries,
        "notes": [
            "All owner-provided clips are audited and retained in this manifest.",
            "VieNeu v3 Turbo uses one <=8 second anchor; it does not fine-tune base weights from MP3 folders.",
            "The anchor is selected deterministically by longest eligible clip to preserve natural prosody.",
        ],
    }
    manifest.write_text(json.dumps(profile, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=Path("voice_demo"))
    parser.add_argument("--output", type=Path, default=Path("var/cache/voices/hina"))
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    manifest = build_profile(args.input, args.output, force=args.force)
    print(manifest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
