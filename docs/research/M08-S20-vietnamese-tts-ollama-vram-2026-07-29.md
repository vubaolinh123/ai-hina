# M08-S20 — Vietnamese TTS and Ollama VRAM decision

Date: 2026-07-29

Machine: owner RTX 5070 Ti 16 GB

Promotion ceiling: 15,872 MiB physical GPU use

## Decision

Keep `k2-fsa/OmniVoice` as Hina's default local voice for this slice. This is a
quality-gate result, not a claim that the base model is the best model-card
candidate available.

`g-group-ai-lab/g-omnivoice` is the most credible next candidate found. Its
model card describes a Vietnamese-optimized 0.6B OmniVoice fine-tune and reports
WER 0.0259 with speaker similarity 0.890. The files are gated behind accepting
the Hugging Face access conditions, so the checkpoint could not be downloaded
or verified on the owner reference in this run. It must not replace a tested
runtime from claims alone.

Other real candidates did not pass:

| Candidate | Real owner-machine result | Decision |
| --- | --- | --- |
| `pnnbao-ump/VieNeu-TTS-v2` Standard | 11.876 s load; 18.206/25.392 s synthesis; 2,386 MiB CUDA reserved peak. Reverse Faster-Whisper similarity 0.2667/0.0922 and output resembled unrelated generic speech. | Reject |
| `splendor1811/omnivoice-vietnamese` | 1.208/1.951 s synthesis; 2,328 MiB CUDA reserved peak. Reverse-STT similarity 0.2667/0.5660 with `language=vi`; still wrong/gibberish on the owner samples. Dataset is CC-BY-NC-SA-4.0. | Reject |
| Fish Audio S2 | Official inference guidance recommends at least 24 GB VRAM. | Ineligible on this 16 GB all-on target |
| `g-group-ai-lab/g-omnivoice` | Not runnable until the owner accepts the gated model terms and supplies local Hugging Face authorization. | Next A/B candidate |

The current pinned OmniVoice baseline remains materially stronger on the
repository regression phrases: reverse-STT similarity 0.9733 short and 0.9285
long, with 2,270 MiB measured CUDA reserved peak. Its pretrained weights remain
local non-commercial owner testing only under the recorded CC-BY-NC terms.

No rejected candidate dependency, checkpoint, generated audio, or one-off
benchmark script was added to product source. The platform blocked deletion of
the following verified agent-created experiment targets, so they remain an
explicit cleanup blocker rather than being hidden behind `.gitignore`:

- `C:\Users\Admin\AppData\Local\HinaAI\cache\models\vieneu-v2-candidate`
- `C:\Users\Admin\AppData\Local\HinaAI\cache\models\omnivoice-vietnamese`
- `D:\ProjectHinaAI\var\tmp\m08-s20-vieneu-v2`
- `D:\ProjectHinaAI\var\tmp\m08-s20-omnivoice-vi`
- `D:\ProjectHinaAI\var\tmp\m08-s20-omnivoice-vi-language`

These paths contain no owner voice source and must be removed only through an
allowed, scope-verified cleanup action.

## Ollama memory profile

The installed brain is already a `Q4_K_M` weight build. Replacing it with Q8
weights would increase, not reduce, its resident weight memory. The useful Q8
setting here is the independent KV-cache quantization `q8_0`.

The launcher profile keeps:

- `OLLAMA_FLASH_ATTENTION=1`;
- `OLLAMA_KV_CACHE_TYPE=q8_0`;
- `OLLAMA_NUM_PARALLEL=1`;
- `OLLAMA_MAX_LOADED_MODELS=1`;
- Qwen `num_ctx=8192`;
- Qwen `num_gpu=32` for a 36-layer text stack.

This is fixed partial offload: four text layers live in system RAM and execute
on CPU. It does not dynamically spill a transient VRAM spike during a request.
Changing `num_gpu` requires model reload; lower values save VRAM but increase
latency.

Measured resident brain values from Ollama `/api/ps`:

| Profile | Ollama `size_vram` | Result |
| --- | ---: | --- |
| 36 GPU layers, context 8192 | about 5,693 MiB | Too close to the all-on physical ceiling |
| 32 GPU layers, context 8192 | about 4,735 MiB | Selected |
| 28 GPU layers, context 8192 | about 4,238 MiB | More headroom, unnecessary latency tradeoff |

With Brain + Faster-Whisper large-v3 + OmniVoice forced resident, the old
36-layer profile reached 15,416 MiB while warming and 15,666 MiB during a real
turn, leaving only 330 MiB free and ending in `E_MODEL_TIMEOUT`. The selected
32-layer profile completed a simple turn in 2.673 s and a selectively reasoned
turn in 5.789 s. Sampling every 100 ms across both turns measured:

- physical peak: 12,905 MiB;
- minimum physical free: 3,091 MiB;
- maximum GPU utilization: 99%;
- brain resident: 4,735 MiB;
- OmniVoice allocated baseline: 1,946.3 MiB.

Faster-Whisper remains `null` per-model in the dashboard because CTranslate2
does not expose a trustworthy model-only CUDA allocator value inside the
shared native worker. The total NVIDIA physical measurement is exact enough for
the admission ceiling; scheduler reservation is not presented as measured VRAM.

## Bounded selective reasoning

At 32 GPU layers, the former 768-token one-pass Thinking request consumed the
entire 9-second provider deadline before emitting a final answer. M08-S20 uses
the same checkpoint in two bounded passes:

1. at most 256 private scratchpad tokens;
2. the scratchpad is closed and passed only inside the provider to a final
   answer pass capped at 128 tokens.

The scratchpad is never emitted, logged, stored in memory, sent to TTS, or
returned to the renderer. A real complex Vietnamese turn completed in 5.789 s
under the all-on profile.

## Primary sources

- G-OmniVoice model card: <https://huggingface.co/g-group-ai-lab/g-omnivoice>
- VieNeu-TTS repository: <https://github.com/pnnbao97/VieNeu-TTS>
- Vietnamese OmniVoice fine-tune: <https://huggingface.co/splendor1811/omnivoice-vietnamese>
- Fish Audio S2 inference requirements:
  <https://github.com/fishaudio/fish-speech/blob/main/docs/en/inference.md>
- Ollama FAQ, Flash Attention and KV cache:
  <https://github.com/ollama/ollama/blob/main/docs/faq.mdx>
- Ollama API: <https://docs.ollama.com/api>
