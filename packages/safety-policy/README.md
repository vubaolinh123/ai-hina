# Hina safety policy

`hina_safety` is the single policy authority introduced in M02. It owns:

- versioned capability manifests;
- deterministic `allow | ask | deny` decisions;
- monotonic rate limits and bounded session budgets;
- capability expiry and revocation;
- operator emergency stop, mute and feature flags;
- append-only SHA-256 chained audit records.

It accepts only structured identifiers and control fields. Raw prompts, model
reasoning, tool output, audio and arbitrary context are intentionally absent
from its API.

This first slice does not implement content moderation or execute capabilities.
