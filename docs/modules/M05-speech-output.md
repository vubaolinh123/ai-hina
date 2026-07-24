# M05 — Speech output, turn-taking and barge-in

- Status: fast-development candidate; implementation, local fast evidence and independent review complete
- Branch: `codex/M05-speech-output`
- Base: `d459032242fa60ced8c7c6a2e5f2a553a47eddc7`
- Active slices: `M05-S1` provider/service, `M05-S2` runtime/UI, `M05-S3` turn voice/cancel

## Runnable result

The Dev Console synthesizes actual local Vietnamese audio through a pinned
VieNeu-TTS v3 Turbo CPU/ONNX provider. The complete utterance must pass the
existing `pre_tts` moderation surface before provider invocation. Generated
audio stays in memory and is returned as binary WAV; it is not stored or used
for training.

The first allowlisted voice is the upstream built-in `Trúc Ly` preset. M05 does
not expose reference audio, voice enrollment or voice cloning. If the provider,
model, codec or voice manifest is unavailable, the UI must show the real error
and correlation ID rather than playing fake or placeholder audio.

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
- The upstream preset is distributed in the Apache-2.0 wheel, but independent
  speaker-consent evidence is not published. Local owner evaluation is allowed;
  public/production promotion remains blocked pending consent review.

## Deferred promotion evidence

The ≥100-sentence independent-ASR/human accuracy corpus, ≥50-pair blind voice
evaluation, RTF/first-audio benchmark, phoneme-accurate alignment, 1000-turn
Companion Gate A and deep barge-in/soak runs remain deferred until the owner
requests M05 promotion testing.
