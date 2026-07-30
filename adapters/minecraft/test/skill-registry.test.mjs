import assert from "node:assert/strict";
import test from "node:test";

import {
  getMinecraftSkillRegistry,
  LOOK_SKILL_DEFINITION,
  MOVE_STEP_SKILL_DEFINITION,
  MOVE_TO_SKILL_DEFINITION,
  MinecraftAdapterError,
  validateMinecraftSkillRequest,
  getMinecraftGoalRegistry,
  GATHER_NEARBY_LOG_GOAL_DEFINITION,
  MINECRAFT_HARVEST_PATHFINDER_POLICY,
  validateMinecraftGoalRequest,
} from "../dist/index.js";

test("goal registry exposes exactly one model-selectable verified gather goal", () => {
  const registry = getMinecraftGoalRegistry();
  assert.equal(registry.length, 1);
  assert.equal(registry[0], GATHER_NEARBY_LOG_GOAL_DEFINITION);
  assert.deepEqual(registry[0], {
    id: "gather.nearby-log.v1",
    version: 1,
    description:
      "Find, safely path to, harvest and collect exactly one loaded allowlisted log after fresh-state checks.",
    preconditions: [
      "controller_online",
      "emergency_stop_not_latched",
      "fresh_physics_state",
      "player_state_available",
      "player_on_ground",
      "allowlisted_log_within_32_horizontal_blocks",
      "vertical_offset_at_most_8_blocks",
      "bounded_path_search_radius_40_blocks",
      "pathfinder_cannot_dig_place_sprint_parkour_or_enter_liquids",
      "new_matching_drop_within_2.5_blocks_of_target",
      "preexisting_entity_snapshot_at_most_512",
      "no_other_action_active",
    ],
    timeoutMs: 30_000,
    budget: { maximumAttempts: 1 },
    destructive: true,
    postcondition: { kind: "targeted_allowlisted_log_collected" },
  });
  assert.throws(() => registry.push({}));
  assert.throws(() => {
    registry[0].budget.maximumAttempts = 3;
  });
  assert.deepEqual(MINECRAFT_HARVEST_PATHFINDER_POLICY, {
    canDig: false,
    canPlace: false,
    canOpenDoors: false,
    allowTowering: false,
    allowParkour: false,
    allowSprinting: false,
    allowEntityDetection: true,
    avoidLiquids: true,
    maximumDropDownBlocks: 1,
    searchRadiusBlocks: 40,
    thinkTimeoutMs: 5_000,
    tickTimeoutMs: 20,
  });
  assert.equal(Object.isFrozen(MINECRAFT_HARVEST_PATHFINDER_POLICY), true);
  assert.deepEqual(
    validateMinecraftGoalRequest({ goalId: "gather.nearby-log.v1" }),
    { goalId: "gather.nearby-log.v1" },
  );
  for (const value of [
    null,
    {},
    { goalId: "move.to.v1" },
    { goalId: "harvest.nearby-log.v1" },
    { goalId: "harvest.nearby-log.v2" },
    { goalId: "harvest.nearby-log.v3" },
    { goalId: "gather.nearby-log.v1", targetX: 2 },
  ]) {
    assert.throws(
      () => validateMinecraftGoalRequest(value),
      (error) =>
        error instanceof MinecraftAdapterError
        && error.code.startsWith("E_MINECRAFT_GOAL_"),
    );
  }
});

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
