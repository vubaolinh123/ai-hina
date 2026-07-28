# Desktop dashboard module boundary

## Purpose

The Electron operator dashboard must remain understandable without turning
`apps/desktop/src/App.vue` into a page-sized monolith. A page is an owner-facing
workflow, not merely a visual section.

## Boundary

- `App.vue` owns Electron window-mode selection, trusted typed-IPC lifecycle,
  shared polling, global error/backoff and page selection.
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

## Current migration state (M08-S12)

- Extracted: `DashboardNav.vue`, `pages/OverviewPage.vue`, and
  `pages/ChatPage.vue`.
- `ChatPage.vue` owns message-list follow behavior, scroll intent, composer
  accessibility and aggregate context display. The composer is sticky on
  desktop and becomes normal flow at narrow widths.
- Existing Speech, Perception, Resources, Live2D and Avatar/Runtime markup is
  legacy root markup. New controls must not be appended to those root sections;
  migrate the entire affected page into `src/dashboard/pages/` as the next
  bounded UI slice.

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
