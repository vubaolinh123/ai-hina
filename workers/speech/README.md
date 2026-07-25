# Hina speech worker

M04 owns microphone/audio input, WAV normalization, VAD and Vietnamese STT.

The runnable Dev Console adapter records microphone PCM in the browser and
sends an `audio/wav` binary body to the loopback runtime. The worker keeps audio
in memory only, normalizes it to 16 kHz mono, rejects silence before inference,
and lazily invokes pinned `moonshine-voice`.

Defaults:

- provider: `moonshine-voice 0.0.73`
- model: Vietnamese Base, architecture `1`
- device: CPU
- language/task: Vietnamese `vi`, `transcribe`
- raw audio retention: disabled

The first accepted speech request can download the pinned model into
`var/cache/models/moonshine`. Set `HINA_STT_ALLOW_DOWNLOAD=false` for strict
offline operation after preloading the model. Set
`HINA_STT_PROVIDER=faster-whisper` to roll back to the previous pinned provider.

The Moonshine Python library is MIT, but its Vietnamese weights use the
non-commercial Moonshine Community License. This candidate must not be promoted
for commercial/public deployment until that model license is cleared.

## M05 speech output

The same worker now provides real Vietnamese synthesis through pinned
`vieneu==3.2.3`, the VieNeu-TTS v3 Turbo ONNX int8 snapshot and the MOSS audio
codec snapshot. It runs on CPU, enrolls the fixed owner-authorized
`Hina Anime AI v1` reference voice from
`assets/voices/hina-anime-elevenlabs-reference.wav`, watermarks generated
audio, and exposes 48 kHz mono PCM16 WAV through the loopback runtime.

Every complete utterance passes `pre_tts` moderation before inference. Voice
uploads, generated-audio retention and input-text retention are disabled.
VieNeu's supported `[chuckle]`, `[sigh]` and `[clear throat]` cues are kept
after alias normalization; unsupported cues are removed. Long utterances use a
bounded 1.00x–1.18x pitch-preserving speed adjustment.
The first accepted request can download the pinned model and codec into
`var/cache/models/vieneu`; set `HINA_TTS_ALLOW_DOWNLOAD=false` after preloading
for strict offline use.

Run one real moderated inference and keep a WAV under the ignored `var/tmp`
folder for manual listening:

```powershell
pnpm smoke:m05-tts
```
