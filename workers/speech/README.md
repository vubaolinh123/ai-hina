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

The same worker now defaults to pinned OmniVoice 0.2.1 on CUDA/FP16. It
conditions the fixed owner-authorized `Hina Anime AI v1` voice from the
checked-in, transcript-aligned and SHA-256-bound eight-second reference, then
exposes 24 kHz mono PCM16 WAV through the loopback runtime. The optional
OmniVoice Whisper ASR is disabled because Hina already owns a separate STT
module.

Every complete utterance passes `pre_tts` moderation before inference. Voice
uploads, generated-audio retention and input-text retention are disabled.
Long utterances are split at 110 characters with clause punctuation preferred,
then OmniVoice also bounds its audio-duration chunks. The quality profile keeps
one stable, natural 1.0x rate for the whole utterance and uses a 160 ms pause
between segments; it never rushes a long sentence to save wall-clock time.
Output is validated per segment and no post-generation time-stretch is applied.
The first accepted request can download the pinned model into
`var/cache/models/omnivoice`; set `HINA_TTS_ALLOW_DOWNLOAD=false` after
preloading for strict offline use. The desktop launcher fails closed when
CUDA/PyTorch is not available; it never silently switches to CPU.

The quality-first profile uses 32 diffusion steps: the 16-step profile was
faster but dropped part of a long Vietnamese sentence in reverse-STT
regression. The reusable voice prompt lives on CPU between requests, batch size
is one, unused CUDA allocator blocks are cleared after inference, and the
provider records allocated/reserved peaks. On the owner's RTX 5070 Ti, measured
peak reserved VRAM is about 2270 MiB; the scheduler reserves 3072 MiB to keep
margin above the measured peak.

The TTS model owns a lower-priority shared scheduler lease while warm. Chat and
STT can preempt it when required; unload returns CUDA memory before lease
release. Ollama is called with `keep_alive: 0`, preventing stale model memory
from causing `E_RESOURCE_CAPACITY` on the next phase.

The ZaloPay F5-TTS adapter remains available only for explicit experiments.
Both the model-card checkpoint `model_960000.pt` and current
`model_1290000.pt` failed Hina's round-trip quality smoke with nonsense/noise,
so the desktop launcher does not select it by default. VieNeu v3 Turbo remains
an explicit rollback provider.

OmniVoice runtime code is Apache-2.0, but the upstream pretrained weights are
declared CC-BY-NC because of training-data constraints. This candidate is
therefore local non-commercial owner testing only and is not production-ready.

### Owner voice profile

Place owner-authorized MP3 clips in `voice_demo` and run:

```powershell
pnpm prepare:voice
```

The command audits every clip, records SHA-256 and duration metadata in
`var/cache/voices/hina/hina-profile.json`, and creates the normalized VieNeu
anchor plus the experimental F5 reference. OmniVoice intentionally uses the
checked-in transcript-aligned reference instead of the generic longest clip.
All clips are included in the local manifest for provenance and future
owner-authorized training work.

Run one real moderated inference and keep a WAV under the ignored `var/tmp`
folder for manual listening:

```powershell
pnpm smoke:m05-tts
```
