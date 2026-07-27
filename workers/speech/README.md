# Hina speech worker

M04 owns microphone/audio input, WAV normalization, VAD and Vietnamese STT.

The runnable desktop adapter records microphone PCM through an AudioWorklet and
sends an `audio/wav` binary body to the loopback runtime. The worker keeps audio
in memory only, normalizes it to 16 kHz mono, rejects silence before inference,
and lazily invokes the pinned GPU STT backend.

Desktop profile:

- provider: `faster-whisper` (`Systran/faster-whisper-large-v3`, CUDA float16)
- language/task: automatic language detection, `transcribe`
- CPU fallback: disabled (fail-closed)
- raw audio retention: disabled

The first accepted speech request can download the pinned model into
`var/cache/models/faster-whisper`. Set `HINA_STT_ALLOW_DOWNLOAD=false` for
strict offline operation after preloading the model. Moonshine Vietnamese Base
remains an explicit diagnostic provider only; its current Windows package is
CPU-only, so it is not selected by the GPU-only desktop profile.

The Moonshine Python library is MIT, but its Vietnamese weights use the
non-commercial Moonshine Community License. This candidate must not be promoted
for commercial/public deployment until that model license is cleared.

## M05 speech output

The same worker now defaults to pinned VoxCPM2 2B on CUDA/BF16. It conditions
the fixed owner-authorized `Hina Anime AI v1` reference voice from the prepared
SHA-256-bound profile anchor (or the checked-in fallback) and exposes 48 kHz
mono PCM16 WAV through the loopback runtime.

Every complete utterance passes `pre_tts` moderation before inference. Voice
uploads, generated-audio retention and input-text retention are disabled.
Long utterances are split at 180 characters, validated per segment and retried
through VoxCPM2's bad-case path. No post-generation time-stretch is applied.
The first accepted request can download the pinned model into
`var/cache/models/voxcpm2`; set `HINA_TTS_ALLOW_DOWNLOAD=false` after
preloading for strict offline use. The desktop launcher fails closed when
CUDA/PyTorch is not available; it never silently switches to CPU.

The TTS model owns a lower-priority shared scheduler lease while warm. Chat and
STT can preempt it when required; unload returns CUDA memory before lease
release. Ollama is called with `keep_alive: 0`, preventing stale model memory
from causing `E_RESOURCE_CAPACITY` on the next phase.

The ZaloPay F5-TTS adapter remains available only for explicit experiments.
Both the model-card checkpoint `model_960000.pt` and current
`model_1290000.pt` failed Hina's round-trip quality smoke with nonsense/noise,
so the desktop launcher does not select it by default. VieNeu v3 Turbo remains
an explicit rollback provider.

### Owner voice profile

Place owner-authorized MP3 clips in `voice_demo` and run:

```powershell
pnpm prepare:voice
```

The command audits every clip, records SHA-256 and duration metadata in
`var/cache/voices/hina/hina-profile.json`, and creates both the normalized
VoxCPM2/VieNeu anchor and the experimental F5 reference. The desktop launcher
automatically uses the profile anchor on the next start. All clips are included
in the local manifest for provenance and future fine-tuning work.

Run one real moderated inference and keep a WAV under the ignored `var/tmp`
folder for manual listening:

```powershell
pnpm smoke:m05-tts
```
