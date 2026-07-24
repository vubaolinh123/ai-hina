# Hina speech worker

M04 owns microphone/audio input, WAV normalization, VAD and Vietnamese STT.

The runnable Dev Console adapter records microphone PCM in the browser and
sends an `audio/wav` binary body to the loopback runtime. The worker keeps audio
in memory only, normalizes it to 16 kHz mono, rejects silence before inference,
and lazily invokes pinned `faster-whisper`.

Defaults:

- provider: `faster-whisper 1.2.1`
- model: `Systran/faster-whisper-small`
- model revision: `536b0662742c02347bc0e980a01041f333bce120`
- device/compute: CPU `int8`
- language/task: Vietnamese `vi`, `transcribe`
- raw audio retention: disabled

The first accepted speech request can download the pinned model into
`var/cache/models/faster-whisper`. Set `HINA_STT_ALLOW_DOWNLOAD=false` for
strict offline operation after preloading the model.

## M05 speech output

The same worker now provides real Vietnamese synthesis through pinned
`vieneu==3.2.3`, the VieNeu-TTS v3 Turbo ONNX int8 snapshot and the MOSS audio
codec snapshot. It runs on CPU, uses the allowlisted `Trúc Ly` preset voice,
watermarks generated audio, and exposes 48 kHz mono PCM16 WAV through the
loopback runtime.

Every complete utterance passes `pre_tts` moderation before inference. Voice
cloning, generated-audio retention and input-text retention are disabled.
The first accepted request can download the pinned model and codec into
`var/cache/models/vieneu`; set `HINA_TTS_ALLOW_DOWNLOAD=false` after preloading
for strict offline use.

Run one real moderated inference and keep a WAV under the ignored `var/tmp`
folder for manual listening:

```powershell
pnpm smoke:m05-tts
```
