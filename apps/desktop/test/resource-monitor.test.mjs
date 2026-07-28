import assert from "node:assert/strict";
import { createRequire } from "node:module";
import test from "node:test";

const require = createRequire(import.meta.url);
const {
  ModelTransitionTracker,
  augmentResourceStatus,
} = require("../dist-electron/resource-monitor.js");

function model(id, state, name = id, measuredVramMiB = null) {
  return {
    id,
    role: `Role ${id}`,
    name,
    state,
    measuredVramMiB,
  };
}

test("resource transition tracker reports load and unload without growing forever", () => {
  const tracker = new ModelTransitionTracker(3);
  const baseline = tracker.observe([model("brain", "unloaded")], 1_000);
  assert.equal(baseline.length, 1);
  assert.equal(baseline[0].action, "observed");

  let history = tracker.observe([model("brain", "loaded")], 2_000);
  assert.equal(history.at(-1).action, "loaded");
  assert.equal(history.at(-1).fromState, "unloaded");
  history = tracker.observe([model("brain", "unloaded")], 3_000);
  assert.equal(history.at(-1).action, "unloaded");
  history = tracker.observe([model("brain", "unavailable")], 4_000);
  assert.equal(history.length, 3);
  assert.deepEqual(history.map((entry) => entry.sequence), [2, 3, 4]);

  const copy = tracker.snapshot();
  copy[0].toState = "tampered";
  assert.notEqual(tracker.snapshot()[0].toState, "tampered");
});

test("resource monitor adds only bounded desktop memory and in-memory history", () => {
  const tracker = new ModelTransitionTracker();
  const result = augmentResourceStatus(
    {
      schemaVersion: "1.0",
      sampledAtUnixMilliseconds: 1_000,
      models: [model("tts", "loaded", "OmniVoice", 1_900)],
      processes: {
        coreRuntime: { label: "Core", rssMiB: 2_048 },
      },
    },
    tracker,
    {
      rss: 128 * 1024 * 1024,
      heapTotal: 64 * 1024 * 1024,
      heapUsed: 32 * 1024 * 1024,
      external: 4 * 1024 * 1024,
      arrayBuffers: 0,
    },
  );
  assert.deepEqual(result.processes.desktopMain, {
    label: "Electron desktop main process",
    rssMiB: 128,
    heapUsedMiB: 32,
    externalMiB: 4,
  });
  assert.equal(result.modelTransitions.length, 1);
  assert.equal(result.models[0].sampledPeakVramMiB, 1_900);
  assert.equal(result.transitionHistory.persistence, false);
  assert.equal(result.transitionHistory.limit, 100);

  const later = augmentResourceStatus(
    {
      schemaVersion: "1.0",
      sampledAtUnixMilliseconds: 2_000,
      models: [model("tts", "loaded", "OmniVoice", 1_850)],
    },
    tracker,
  );
  assert.equal(later.models[0].sampledPeakVramMiB, 1_900);
});

test("resource monitor rejects oversized or unknown model states", () => {
  const tracker = new ModelTransitionTracker();
  assert.throws(
    () => tracker.observe([model("brain", "invented")]),
    /E_DESKTOP_RESOURCE_RESPONSE/,
  );
  assert.throws(
    () => augmentResourceStatus({ schemaVersion: "2.0", models: [] }, tracker),
    /E_DESKTOP_RESOURCE_RESPONSE/,
  );
  assert.throws(
    () => tracker.observe([model("brain", "loaded", "brain", Number.NaN)]),
    /E_DESKTOP_RESOURCE_RESPONSE/,
  );
  assert.throws(
    () => new ModelTransitionTracker(0),
    /E_DESKTOP_RESOURCE_HISTORY/,
  );
});
