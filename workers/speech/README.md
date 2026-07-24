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
