# ADR-0001: Modular monolith with process adapters

- Status: accepted
- Date: 2026-07-23
- Owners: project owner, primary orchestrator

## Context

Hina AI must combine Python AI libraries, an Electron/Vue desktop, Node-based Mineflayer, and GPU-native workers on one Windows machine with 16 GB VRAM. A dense microservice stack would add failure and deployment overhead before load requires it.

## Decision

Use a Python modular-monolith core. Split a process only at a language, native dependency, GPU, or fault-isolation boundary. Use generated contracts across process/language boundaries.

## Consequences

- Simpler bootstrap and integration tests.
- Strong module ownership without early infrastructure.
- Later extraction remains possible through versioned ports.
- Process lifecycle and cross-language contracts must be tested from M01.

## Rollback

Revisit by ADR only after profiling proves an isolation or scale requirement.
