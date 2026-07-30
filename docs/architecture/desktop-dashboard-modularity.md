# Desktop dashboard module boundary

## Purpose

The Electron operator dashboard must remain understandable without turning
`apps/desktop/src/App.vue` into a page-sized monolith. A page is an owner-facing
workflow, not merely a visual section.

## Boundary

- `App.vue` owns Electron window-mode selection, top-level lifecycle, page
  selection and global composition. Trusted feature workflows may live in a
  typed renderer composable rather than grow the shell.
- `src/dashboard/DashboardNav.vue` owns navigation labels and navigation events.
- Each `src/dashboard/pages/*.vue` file owns one page's markup, accessibility,
  local visual state and ergonomics. It must not import Electron, Node, direct
  network APIs, persistence or model runtimes.
- Business calls remain in a typed renderer composable or the shell and reach
  services only through `window.hinaDesktop`. A page emits intent or receives
  bounded data; it never receives a secret, source ID, raw pixel buffer or
  hidden model text.
- Page-specific CSS stays under a stable page/class prefix in `style.css` until
  a page has enough local styles to justify a colocated stylesheet.

## Current migration state (M08-S18)

- Extracted: `DashboardNav.vue`, `pages/OverviewPage.vue`,
  `pages/ChatPage.vue`, `pages/PerceptionPage.vue`,
  `pages/ResourcesPage.vue`, `pages/SpeechPage.vue`,
  `pages/Live2DPage.vue`, `pages/AvatarPage.vue`, and
  `pages/RuntimePage.vue`. There is no remaining legacy root dashboard page.
- `ChatPage.vue` owns message-list follow behavior, scroll intent, composer
  accessibility and aggregate context display. The composer is sticky on
  desktop and becomes normal flow at narrow widths.
- `PerceptionPage.vue` owns the screen-capture and Vision configuration
  presentation. It receives bounded display data and emits owner intent or
  field updates; `App.vue` remains the only owner of capture grants, Safety,
  session binding, typed IPC, stored-key lifecycle and error logging.
- `ResourcesPage.vue` owns telemetry/residency/lease presentation and emits only
  refresh or allowlisted control intent. `App.vue` keeps visibility-scoped
  polling, samples, telemetry/error state and the actual typed IPC call. Model
  rows distinguish provider-reported current VRAM, provider-measured request
  peak and the dashboard's 1.5-second sampled session peak; an unavailable
  provider counter remains null with a source-specific explanation.
- `SpeechPage.vue` owns the owner-facing mic/STT/TTS test presentation and emits
  only explicit start/stop/test or field updates. `App.vue` retains microphone
  streams, WAV conversion, audio object-URL cleanup, realtime throttling and
  typed speech IPC.
- `Live2DPage.vue` owns the VTube Studio/Spout status and fixed owner controls;
  it receives no token, WebSocket, raw frame or arbitrary command capability.
  `App.vue` retains typed IPC, token/transport lifecycle, polling and error state.
- `AvatarPage.vue` owns the stage/VRM fallback, renderer telemetry, manual visual
  preview and provenance guidance. The trusted Avatar/Runtime composable retains
  VRM lazy-load/recovery, performance event handling, avatar polling and every
  typed avatar IPC call.
- `RuntimePage.vue` owns widget and Safety presentation. The trusted composable
  retains widget position lifecycle, widget/Safety typed IPC, retry/backoff and
  global error state. The page emits only the fixed show/hide/reset, mute and
  emergency intents.
- `composables/use-avatar-runtime.ts` is the trusted renderer boundary beneath
  the Avatar/Runtime pages. It owns Avatar/Widget/VRM state, fixed typed IPC,
  250 ms avatar and one-second Safety/widget polls, bounded offline backoff and
  VRM recovery telemetry. `App.vue` only composes it with the operator lifecycle;
  the separate Perception feature-flag workflow remains where it is.
- New dashboard UI must be added to the relevant page component; `App.vue` is the
  shell/lifecycle boundary and must not regain page-sized markup.

## Conversation UI contract

- Display only aggregate context telemetry: configured token window, bounded
  byte-budget estimate, recent-turn count and approved memory/observation
  counts. Never display system prompt text, hidden reasoning or raw history.
- Keep the message list independently scrollable and preserve an owner who
  deliberately scrolls away from the newest message; otherwise follow new
  messages automatically.
- Keep the input/composer reachable while page content scrolls. On compact
  windows, prefer a normal-flow composer over an overlapping sticky control.

## Verification

`apps/desktop/test/security.test.mjs` assembles the operator renderer modules
to retain the no-direct-network/Electron/storage invariant and asserts the
navigation, context meter and sticky-chat boundary. Run:

```powershell
pnpm --filter @hina/desktop typecheck
pnpm test:desktop
```

## Minecraft goal boundary (M09-S8/S9)

- `pages/MinecraftPage.vue` is a presentation/intent page. It can collect one
  bounded natural-language owner goal and display a bounded status/world snapshot,
  but it has no direct network, Mineflayer, Electron, model, secret or filesystem
  access.
- The page deliberately contains no yaw/pitch, cardinal movement, distance, X/Z,
  target-copy or per-skill gameplay controls. Connection, read-only status,
  emergency stop and the explicit Safety permission remain separate owner actions.
- `App.vue` invokes a typed Electron bridge. Electron main first asks the local
  text service to select one fixed allowlisted goal, then calls the separate
  Mineflayer service only with that exact ID. Raw model output, hidden reasoning,
  free-form action lists and arbitrary arguments never cross into the renderer or
  controller.
- New Minecraft capability must add a reviewed goal/state-machine module with
  typed preconditions, cancellation, bounded attempt/timeout and game-state
  postcondition evidence. Do not rebuild manual UI controls as a shortcut.
- The current `harvest.nearby-log.v2` state machine may discover one same-level
  allowlisted log within eight horizontal blocks, then compose at most three
  verified flat/clear segments of at most two blocks before one dig. The page may
  describe that scope, but it never receives a target coordinate, route, movement
  primitive, raw model output or action sequence. Obstacles, jumps, pathfinding,
  crafting, equipping, retries and autonomous play remain unavailable until a
  separately reviewed deterministic goal adds them.
