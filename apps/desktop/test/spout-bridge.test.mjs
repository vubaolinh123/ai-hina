import assert from "node:assert/strict";
import { createRequire } from "node:module";
import test from "node:test";

const require = createRequire(import.meta.url);
const {
  SpoutBridge,
  isFrameStale,
  parseWorkerLine,
} = require("../dist-electron/spout-bridge.js");

test("Spout worker line parser accepts only bounded protocol prefixes", () => {
  assert.deepEqual(
    parseWorkerLine(
      'READY {"port":54321,"sender":"VTubeStudioSpout","message":"ready"}',
    ),
    {
      kind: "READY",
      payload: {
        port: 54321,
        sender: "VTubeStudioSpout",
        message: "ready",
      },
    },
  );
  assert.deepEqual(
    parseWorkerLine(
      'STATUS {"width":720,"height":405,"frameReady":true,"transparent":false}',
    ),
    {
      kind: "STATUS",
      payload: {
        width: 720,
        height: 405,
        frameReady: true,
        transparent: false,
      },
    },
  );
  assert.equal(parseWorkerLine("uv resolved dependencies"), null);
  assert.equal(parseWorkerLine("READY not-json"), null);
  assert.equal(parseWorkerLine('UNKNOWN {"port":54321}'), null);
  assert.equal(parseWorkerLine('READY ["not","an","object"]'), null);
});

test("stale Spout frames fail closed after the bounded freshness window", () => {
  assert.equal(isFrameStale(true, 1_999), false);
  assert.equal(isFrameStale(true, 2_001), true);
  assert.equal(isFrameStale(false, 60_000), false);
  assert.equal(isFrameStale(true, "2001"), false);
});

test("disabled Spout bridge never spawns and returns deterministic fallback state", async () => {
  const bridge = new SpoutBridge({
    repoRoot: "D:/ProjectHinaAI",
    enabled: false,
  });
  assert.deepEqual(await bridge.start(), {
    available: true,
    enabled: false,
    state: "disabled",
    sender: "VTubeStudioSpout",
    endpoint: null,
    frameUrl: null,
    frameReady: false,
    frameSequence: 0,
    frameAgeMilliseconds: null,
    width: 0,
    height: 0,
    transparent: false,
    lastErrorCode: null,
  });
  await bridge.stop();
  assert.equal(bridge.status().state, "disabled");
});
