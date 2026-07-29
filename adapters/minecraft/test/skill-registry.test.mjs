import assert from "node:assert/strict";
import test from "node:test";

import {
  getMinecraftSkillRegistry,
  LOOK_SKILL_DEFINITION,
  MinecraftAdapterError,
  validateMinecraftSkillRequest,
} from "../dist/index.js";

test("registry contains exactly one immutable non-destructive look skill", () => {
  const registry = getMinecraftSkillRegistry();
  assert.equal(registry.length, 1);
  assert.equal(registry[0], LOOK_SKILL_DEFINITION);
  assert.deepEqual(registry[0], {
    id: "look.v1",
    version: 1,
    description: "Turn Hina's view to one validated yaw and pitch target.",
    preconditions: [
      "controller_online",
      "emergency_stop_not_latched",
      "player_state_available",
      "no_other_skill_active",
    ],
    timeoutMs: 2_000,
    budget: {
      maximumAttempts: 1,
    },
    postcondition: {
      kind: "player_rotation_matches",
      toleranceRadians: 0.05,
    },
    destructive: false,
  });
  assert.throws(() => registry.push({}));
  assert.throws(() => {
    registry[0].budget.maximumAttempts = 3;
  });
});

test("validates a bounded look.v1 request", () => {
  assert.deepEqual(
    validateMinecraftSkillRequest({
      skillId: "look.v1",
      arguments: {
        yawRadians: Math.PI,
        pitchRadians: -Math.PI / 2,
      },
    }),
    {
      skillId: "look.v1",
      arguments: {
        yawRadians: Math.PI,
        pitchRadians: -Math.PI / 2,
      },
    },
  );
});

test("rejects unknown skills, shape changes and unsafe angles", () => {
  const invalid = [
    null,
    {},
    { skillId: "move.v1", arguments: { yawRadians: 0, pitchRadians: 0 } },
    { skillId: "look.v1" },
    {
      skillId: "look.v1",
      arguments: { yawRadians: 0, pitchRadians: 0 },
      timeoutMs: 99_999,
    },
    {
      skillId: "look.v1",
      arguments: { yawRadians: 0, pitchRadians: 0, force: true },
    },
    {
      skillId: "look.v1",
      arguments: { yawRadians: Number.NaN, pitchRadians: 0 },
    },
    {
      skillId: "look.v1",
      arguments: { yawRadians: Math.PI + 0.01, pitchRadians: 0 },
    },
    {
      skillId: "look.v1",
      arguments: { yawRadians: 0, pitchRadians: Math.PI },
    },
  ];
  for (const request of invalid) {
    assert.throws(
      () => validateMinecraftSkillRequest(request),
      (error) =>
        error instanceof MinecraftAdapterError &&
        error.code.startsWith("E_MINECRAFT_SKILL_"),
    );
  }
});
