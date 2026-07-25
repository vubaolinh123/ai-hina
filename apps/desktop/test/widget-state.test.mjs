import assert from "node:assert/strict";
import { createRequire } from "node:module";
import test from "node:test";

const require = createRequire(import.meta.url);
const state = require("../dist-electron/widget-state.js");

const SIZE = { width: 440, height: 620 };
const PRIMARY = { x: 0, y: 0, width: 1920, height: 1080 };

test("widget position serialization persists exactly three bounded fields", () => {
  const raw = state.serializeWidgetPosition({ x: -640, y: 125 });
  assert.deepEqual(JSON.parse(raw), {
    schemaVersion: "1.0",
    x: -640,
    y: 125,
  });
  assert.deepEqual(state.parseWidgetPosition(raw), { x: -640, y: 125 });
  assert.throws(
    () => state.serializeWidgetPosition({ x: Number.NaN, y: 0 }),
    /E_DESKTOP_WIDGET_POSITION/,
  );
});

test("malformed, oversized and unknown widget state fails closed", () => {
  for (const raw of [
    "",
    "not json",
    "[]",
    '{"schemaVersion":"2.0","x":0,"y":0}',
    '{"schemaVersion":"1.0","x":0.1,"y":0}',
    '{"schemaVersion":"1.0","x":0,"y":0,"note":"unexpected"}',
    " ".repeat(state.WIDGET_STATE_MAX_BYTES + 1),
  ]) {
    assert.equal(state.parseWidgetPosition(raw), null);
  }
});

test("default position keeps the fixed widget inside primary work area", () => {
  assert.deepEqual(
    state.defaultWidgetPosition(PRIMARY, SIZE),
    { x: 1456, y: 436 },
  );
  assert.deepEqual(
    state.defaultWidgetPosition({ x: 0, y: 0, width: 320, height: 480 }, SIZE),
    { x: 0, y: 0 },
  );
});

test("restore preserves negative-coordinate displays and clamps their edges", () => {
  const workAreas = [
    PRIMARY,
    { x: -2560, y: -200, width: 2560, height: 1440 },
  ];
  assert.deepEqual(
    state.clampWidgetPosition({ x: -1800, y: 200 }, SIZE, workAreas),
    { x: -1800, y: 200 },
  );
  assert.deepEqual(
    state.clampWidgetPosition({ x: -2800, y: -500 }, SIZE, workAreas),
    { x: -2560, y: -200 },
  );
});

test("display removal recovers an off-screen widget onto the nearest display", () => {
  assert.deepEqual(
    state.clampWidgetPosition({ x: 2600, y: 900 }, SIZE, [PRIMARY]),
    { x: 1480, y: 460 },
  );
  assert.throws(
    () => state.clampWidgetPosition({ x: 0, y: 0 }, SIZE, []),
    /E_DESKTOP_WIDGET_BOUNDS/,
  );
});
