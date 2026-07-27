# M05 — Speech output, turn-taking and barge-in

- Status: fast-development candidate; implementation, local fast evidence and independent review complete
- Branch: `main`
- Active slices: `M05-S1` provider/service, `M05-S2` runtime/UI, `M05-S3` turn voice/cancel, `M05-S4` owner reference voice

## Runnable result

### Current quality decision — VieNeu CUDA default, F5 rejected

The desktop/control-plane default selects the pinned VieNeu-TTS v3 Turbo
checkpoint on CUDA. It conditions on the owner-authorized Hina synthetic
reference and returns 48 kHz mono WAV.

The ZaloPay F5 provider remains experimental and is not selected by the
launcher. Both `model_960000.pt` from the model-card revision and the current
`model_1290000.pt` produced nonsense/noise in real Hina reference tests; their
round-trip transcripts did not match the requested Vietnamese text.

The Dev Console synthesizes actual local Vietnamese audio through a pinned
VieNeu-TTS v3 Turbo CUDA provider. The complete utterance must pass the
existing `pre_tts` moderation surface before provider invocation. Generated
audio stays in memory and is returned as binary WAV; it is not stored or used
for training.

The default allowlisted voice is `Hina Anime AI v1`, enrolled at runtime from
the owner-provided ElevenLabs synthetic reference. The source is hash-bound by
`assets/manifests/hina-anime-elevenlabs-voice.v1.json`; this is zero-shot
reference enrollment, not training or fine-tuning of VieNeu weights. Arbitrary
reference uploads remain disabled. If the provider, model, codec, speaker
encoder or reference manifest is unavailable, the UI must show the real error
and correlation ID rather than playing fake or placeholder audio.

VieNeu v3 Turbo supports `[chuckle]`, `[sigh]` and `[clear throat]`. Hina
normalizes aliases such as `[chuckles]`, `[laughs]`, `[sighs]`, `[clears
throat]` and approximates `[takes a deep breath]` as `[sigh]`. Unsupported
tags such as `[yawns]`, `[gasps]` and `[smacks lips]` are removed instead of
being spoken literally. Long text uses a bounded pitch-preserving WSOLA
post-process from 1.00x to 1.18x; short text stays at normal speed.

Implemented surfaces:

- `GET /v1/tts/status`;
- binary `POST /v1/tts/synthesis`;
- `POST /v1/tts/utterances/{utteranceId}/cancel`;
- manual text synthesis/playback and auto-speak for completed moderated chat;
- immediate browser playback stop plus provider cancellation on barge-in;
- redacted JSONL errors containing correlation/utterance IDs but no text/audio;
- estimated chunk alignment events, explicitly not phoneme-accurate visemes.

The provider is `vieneu==3.2.3`, model revision
`75ff82a72f54d55ed389e1eeb12041d3c4bac7d4` and codec revision
`ceff0d0749bfb3fa2d61149794ec6feef0d1e1ae`. Code, model, codec and bundled
voice-preset provenance are recorded separately.

## Fast evidence

- `pnpm test:fast`: 103 tests passed (22 safety, 22 text brain, 25 speech,
  34 core runtime) plus JavaScript syntax check.
- `pnpm smoke:m05-tts`: real moderated CPU inference produced a valid 48 kHz
  mono WAV, 391724 bytes and 4.08 seconds of audio.
- Observed CPU smoke: 7515 ms processing and 6750 ms first chunk. This proves
  the runnable real path but does **not** pass the roadmap's release latency
  target.

The smoke artifact is written only by the explicit owner tool to
`var/tmp/m05-real-tts/hina-smoke.wav` for manual listening. The runtime endpoint
does not persist generated audio.

Independent review found no P0/P1 or acceptance blocker. Its page-unload P2 was
closed with best-effort `sendBeacon`/keepalive provider cancellation; the
remaining voice-consent P2 is intentionally retained as a release blocker.

Ngày 2026-07-25, owner chỉ thị tiếp tục task tiếp theo. Quyết định này cho phép
chuyển fast-development write phase sang M06; các deep performance/consent gate
của M05 vẫn chưa được mô tả là đã pass.

## Known release blockers

- CPU performance is above the RTF and first-audio promotion targets; a later
  optimization may require a ResourceLease-protected GPU backend or a different
  reviewed model.
- The fixed synthetic reference is authorized for local owner use according to
  the owner statement recorded in its manifest. The raw source MP3 remains
  outside Git; deleting the canonical reference WAV and manifest revokes local
  enrollment. Public/production promotion still requires a separate quality
  and licensing review.

## Deferred promotion evidence

The ≥100-sentence independent-ASR/human accuracy corpus, ≥50-pair blind voice
evaluation, RTF/first-audio benchmark, phoneme-accurate alignment, 1000-turn
Companion Gate A and deep barge-in/soak runs remain deferred until the owner
requests M05 promotion testing.
