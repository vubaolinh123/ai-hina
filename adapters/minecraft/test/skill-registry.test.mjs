import assert from "node:assert/strict";
import test from "node:test";

import {
  getMinecraftSkillRegistry,
  LOOK_SKILL_DEFINITION,
  MOVE_STEP_SKILL_DEFINITION,
  MOVE_TO_SKILL_DEFINITION,
  MinecraftAdapterError,
  validateMinecraftSkillRequest,
} from "../dist/index.js";

test("registry contains exactly three immutable non-destructive skills", () => {
  const registry = getMinecraftSkillRegistry();
  assert.equal(registry.length, 3);
  assert.equal(registry[0], LOOK_SKILL_DEFINITION);
  assert.equal(registry[1], MOVE_STEP_SKILL_DEFINITION);
  assert.equal(registry[2], MOVE_TO_SKILL_DEFINITION);
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
  assert.deepEqual(registry[1], {
    id: "move.step.v1",
    version: 1,
    description: "Move Hina a short verified cardinal step on a resettable world.",
    preconditions: [
      "controller_online",
      "emergency_stop_not_latched",
      "player_state_available",
      "player_on_ground",
      "no_other_skill_active",
    ],
    timeoutMs: 4_000,
    budget: {
      maximumAttempts: 1,
    },
    postcondition: {
      kind: "player_cardinal_displacement_matches",
      minimumProgressRatio: 0.75,
      maximumOvershootBlocks: 0.75,
      lateralToleranceBlocks: 0.35,
    },
    destructive: false,
  });
  assert.deepEqual(registry[2], {
    id: "move.to.v1",
    version: 1,
    description: "Turn and move Hina to one verified nearby X/Z coordinate.",
    preconditions: [
      "controller_online",
      "emergency_stop_not_latched",
      "player_state_available",
      "player_on_ground",
      "fresh_physics_state",
      "target_distance_0.25_to_2_blocks",
      "no_other_skill_active",
    ],
    timeoutMs: 4_000,
    budget: {
      maximumAttempts: 1,
    },
    postcondition: {
      kind: "player_target_coordinate_matches",
      minimumProgressRatio: 0.75,
      maximumOvershootBlocks: 0.75,
      lateralToleranceBlocks: 0.35,
    },
    destructive: false,
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

test("validates a bounded move.step.v1 request", () => {
  assert.deepEqual(
    validateMinecraftSkillRequest({
      skillId: "move.step.v1",
      arguments: {
        direction: "north",
        distanceBlocks: 2,
      },
    }),
    {
      skillId: "move.step.v1",
      arguments: {
        direction: "north",
        distanceBlocks: 2,
      },
    },
  );
});

test("validates a bounded move.to.v1 coordinate request", () => {
  assert.deepEqual(
    validateMinecraftSkillRequest({
      skillId: "move.to.v1",
      arguments: {
        targetX: -123.5,
        targetZ: 456.25,
      },
    }),
    {
      skillId: "move.to.v1",
      arguments: {
        targetX: -123.5,
        targetZ: 456.25,
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
    {
      skillId: "move.step.v1",
      arguments: { direction: "up", distanceBlocks: 1 },
    },
    {
      skillId: "move.step.v1",
      arguments: { direction: "east", distanceBlocks: 2.01 },
    },
    {
      skillId: "move.step.v1",
      arguments: { direction: "east", distanceBlocks: 0.24 },
    },
    {
      skillId: "move.step.v1",
      arguments: { direction: "east", distanceBlocks: 1, sprint: true },
    },
    {
      skillId: "move.to.v1",
      arguments: { targetX: Number.NaN, targetZ: 2 },
    },
    {
      skillId: "move.to.v1",
      arguments: { targetX: 30_000_001, targetZ: 2 },
    },
    {
      skillId: "move.to.v1",
      arguments: { targetX: 1, targetZ: 2, pathfind: true },
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
