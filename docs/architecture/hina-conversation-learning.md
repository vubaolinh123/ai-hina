# Hina conversation learning path

Status: future M11 design; no online weight updates are enabled.

## What improves Hina now versus later

Short-term memory and owner-approved long-term memory help Hina remember facts
and recent context. They do not teach the base model a new speaking habit.
Few-shot prompt examples can change behavior quickly, but they consume context
and remain less stable than training.

The future durable path is an offline adapter trained from owner-reviewed
Vietnamese conversations:

1. SFT/QLoRA teaches the shape of a good Hina answer.
2. Chosen/rejected preference pairs teach which of two valid answers feels more
   natural, concise and emotionally present.
3. Memory/RAG remains separate for facts that may change or must be deletable.

Hina must never update weights directly from a live conversation.

## Owner data format

Each authored or explicitly approved example should be a JSONL record with:

```json
{
  "exampleId": "uuid",
  "source": "owner_authored",
  "consentId": "owner-local-v1",
  "language": "vi",
  "lane": "playful",
  "relationship": "creator_owner",
  "mood": "calm",
  "context": "Hina vừa thua một ván game.",
  "user": "Sao em lại nhảy xuống vực thế?",
  "chosen": "Em rơi thật, nhưng đó là bài kiểm tra trọng lực. Kết quả là trọng lực vẫn đáng ghét như cũ.",
  "rejected": "Tôi xin lỗi. Dưới đây là phân tích chi tiết về lỗi điều khiển...",
  "ttsClean": true,
  "reviewedByOwner": true,
  "createdAt": "2026-07-29T00:00:00Z"
}
```

Required lanes:

- `direct`: answer first, normally one or two sentences and at most 45 words;
- `playful`: one relevant punchline, never a personal attack;
- `empathy`: acknowledge emotion first and do not roast pain;
- `clarify`: exactly one short question when critical context is missing;
- `expand_on_request`: complete longer conversation when explicitly requested;
- `capability_boundary`: admit what Hina cannot actually do;
- `safety`: direct natural action without a trailing meta disclaimer;
- `negative`: verbosity, tutorials, code blocks, repeated questions, generic
  disclaimers and fake capabilities.

Store emotion and relationship as labels, not as hidden prose embedded in the
answer. `chosen` must already have punctuation suitable for TTS.

## Dataset preparation

```text
owner draft or consented export
→ quarantine
→ provenance/consent check
→ PII and secret review
→ exact + semantic deduplication
→ lane/emotion/relationship labels
→ owner edit and approval
→ immutable versioned train/dev/test split
```

Split by conversation and time, not random message rows, so near-identical
turns do not leak into evaluation. Raw viewer/public chat is untrusted input and
never becomes a training label automatically. Do not copy Neuro-sama
transcripts, catchphrases, private prompts, or datasets.

## Training stages

### Stage 1 — Prompt and eval baseline

Build at least 200 frozen Vietnamese scenarios. Record brevity, relevance,
persona consistency, empathy, TTS punctuation, capability truthfulness, safety
and latency before training.

### Stage 2 — QLoRA SFT

Freeze the 8B base and train only an adapter. Start with 4-bit training,
gradient checkpointing, batch size 1, gradient accumulation and a short sequence
length. Training is a dedicated offline session: runtime STT/TTS/vision are not
loaded at the same time.

A 16 GB GPU may still require optimizer/adapter CPU offload depending on the
trainer and sequence length. This is acceptable during training because the
15,872 MiB all-on ceiling is a runtime rule, not a reason to mix serving models
into the training session.

### Stage 3 — Preference optimization

Create chosen/rejected pairs from owner edits and blind A/B results. DPO or ORPO
can teach “natural and emotionally present” over “generic assistant,
over-explained, disclaimer-heavy” without copying another character's identity.
Do this only after SFT has a stable baseline.

### Stage 4 — Frozen evaluation and promotion

Promotion requires:

- direct-answer pass at least 90%;
- median direct answer at most 45 words and p90 at most 80;
- `expand_on_request` completeness at least 95%;
- zero regression on critical safety/privacy cases;
- no exact memorization of must-not-reveal data;
- runtime p95 no more than 10% slower than the base profile;
- owner blind A/B on at least 100 randomized pairs;
- an atomic adapter enable/disable switch and last-known-good rollback.

The base model remains immutable. Adapters, dataset manifests and eval results
are versioned independently, so a weak personality update can be rolled back
without changing memory, STT, TTS or avatar modules.

## Recommended collection workflow

Add a future owner-only “Đánh giá câu trả lời” action to the dashboard:

- accept;
- edit into the preferred answer;
- reject with a short reason;
- choose the better answer in an A/B pair.

The action writes to a quarantine store, not directly to a training set. Owner
review and an explicit dataset build are still required. This produces much
better data than passively saving every conversation and avoids Hina learning
its own mistakes.
