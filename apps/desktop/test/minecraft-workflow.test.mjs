import assert from "node:assert/strict";
import test from "node:test";

import {
  MINECRAFT_WORKFLOW_TRACE_MAX_ENTRIES,
  parseMinecraftGoalProgress,
} from "../dist-electron/minecraft-workflow.js";

const VALID = Object.freeze({
  schemaVersion: 1,
  workflowId: "11111111-1111-4111-8111-111111111111",
  sequence: 3,
  occurredAt: "2026-07-30T08:00:00.000Z",
  stage: "planner.completed",
  status: "succeeded",
  title: "Đã chọn goal trong allowlist",
  detail: "Model chọn harvest.nearby-log.v3; schema đã được xác minh.",
  elapsedMs: 4210.4,
});

test("Minecraft workflow trace accepts only the fixed bounded event", () => {
  assert.deepEqual(parseMinecraftGoalProgress(VALID), VALID);
  assert.equal(MINECRAFT_WORKFLOW_TRACE_MAX_ENTRIES, 8);
});

test("Minecraft workflow trace rejects raw reasoning, prompt fields and malformed bounds", () => {
  for (const value of [
    { ...VALID, reasoning: "hidden chain of thought" },
    { ...VALID, prompt: "raw system prompt" },
    { ...VALID, sequence: 9 },
    { ...VALID, workflowId: "not-a-uuid" },
    { ...VALID, stage: "model.raw-output" },
    { ...VALID, detail: "x".repeat(385) },
    { ...VALID, elapsedMs: Number.NaN },
  ]) {
    assert.equal(parseMinecraftGoalProgress(value), null);
  }
});
