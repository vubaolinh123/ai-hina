import {
  MinecraftAdapterError,
  type MinecraftLookSkillRequest,
  type MinecraftLookSkillDefinition,
  type MinecraftMoveSkillRequest,
  type MinecraftMoveSkillDefinition,
  type MinecraftSkillDefinition,
  type MinecraftSkillRequest,
} from "./contracts.js";

export const LOOK_SKILL_DEFINITION: MinecraftLookSkillDefinition = Object.freeze({
  id: "look.v1",
  version: 1,
  description: "Turn Hina's view to one validated yaw and pitch target.",
  preconditions: Object.freeze([
    "controller_online",
    "emergency_stop_not_latched",
    "player_state_available",
    "no_other_skill_active",
  ]),
  timeoutMs: 2_000,
  budget: Object.freeze({
    maximumAttempts: 1,
  }),
  postcondition: Object.freeze({
    kind: "player_rotation_matches",
    toleranceRadians: 0.05,
  }),
  destructive: false,
});

export const MOVE_STEP_SKILL_DEFINITION: MinecraftMoveSkillDefinition = Object.freeze({
  id: "move.step.v1",
  version: 1,
  description: "Move Hina a short verified cardinal step on a resettable world.",
  preconditions: Object.freeze([
    "controller_online",
    "emergency_stop_not_latched",
    "player_state_available",
    "player_on_ground",
    "no_other_skill_active",
  ]),
  timeoutMs: 4_000,
  budget: Object.freeze({
    maximumAttempts: 1,
  }),
  postcondition: Object.freeze({
    kind: "player_cardinal_displacement_matches",
    minimumProgressRatio: 0.75,
    maximumOvershootBlocks: 0.75,
    lateralToleranceBlocks: 0.35,
  }),
  destructive: false,
});

const SKILL_REGISTRY = Object.freeze([
  LOOK_SKILL_DEFINITION,
  MOVE_STEP_SKILL_DEFINITION,
]);
const ROOT_FIELDS = Object.freeze(["arguments", "skillId"]);
const LOOK_FIELDS = Object.freeze(["pitchRadians", "yawRadians"]);
const MOVE_FIELDS = Object.freeze(["direction", "distanceBlocks"]);
const MOVE_DIRECTIONS = new Set(["north", "east", "south", "west"]);

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function hasExactFields(
  value: Record<string, unknown>,
  expected: readonly string[],
): boolean {
  const actual = Object.keys(value).sort();
  return (
    actual.length === expected.length &&
    actual.every((field, index) => field === expected[index])
  );
}

function finiteInRange(
  value: unknown,
  minimum: number,
  maximum: number,
): value is number {
  return (
    typeof value === "number" &&
    Number.isFinite(value) &&
    value >= minimum &&
    value <= maximum
  );
}

export function getMinecraftSkillRegistry(): readonly MinecraftSkillDefinition[] {
  return SKILL_REGISTRY;
}

export function validateMinecraftSkillRequest(
  value: unknown,
): MinecraftSkillRequest {
  if (!isRecord(value) || !hasExactFields(value, ROOT_FIELDS)) {
    throw new MinecraftAdapterError(
      "E_MINECRAFT_SKILL_SCHEMA",
      "Skill request must contain exactly skillId and arguments",
    );
  }
  if (
    value.skillId !== LOOK_SKILL_DEFINITION.id &&
    value.skillId !== MOVE_STEP_SKILL_DEFINITION.id
  ) {
    throw new MinecraftAdapterError(
      "E_MINECRAFT_SKILL_UNKNOWN",
      "Minecraft skill is not in the fixed allowlist",
    );
  }
  if (!isRecord(value.arguments)) {
    throw new MinecraftAdapterError(
      "E_MINECRAFT_SKILL_SCHEMA",
      "Skill arguments must be an object",
    );
  }
  if (value.skillId === MOVE_STEP_SKILL_DEFINITION.id) {
    if (!hasExactFields(value.arguments, MOVE_FIELDS)) {
      throw new MinecraftAdapterError(
        "E_MINECRAFT_SKILL_SCHEMA",
        "move.step.v1 arguments must contain exactly direction and distanceBlocks",
      );
    }
    const { direction, distanceBlocks } = value.arguments;
    if (
      typeof direction !== "string" ||
      !MOVE_DIRECTIONS.has(direction) ||
      !finiteInRange(distanceBlocks, 0.25, 2)
    ) {
      throw new MinecraftAdapterError(
        "E_MINECRAFT_SKILL_SCHEMA",
        "move.step.v1 requires a cardinal direction and 0.25-2.0 blocks",
      );
    }
    const request: MinecraftMoveSkillRequest = {
      skillId: "move.step.v1",
      arguments: {
        direction: direction as MinecraftMoveSkillRequest["arguments"]["direction"],
        distanceBlocks,
      },
    };
    return request;
  }
  if (!hasExactFields(value.arguments, LOOK_FIELDS)) {
    throw new MinecraftAdapterError(
      "E_MINECRAFT_SKILL_SCHEMA",
      "look.v1 arguments must contain exactly yawRadians and pitchRadians",
    );
  }
  const { yawRadians, pitchRadians } = value.arguments;
  if (!finiteInRange(yawRadians, -Math.PI, Math.PI)) {
    throw new MinecraftAdapterError(
      "E_MINECRAFT_SKILL_SCHEMA",
      "yawRadians must be finite and between -pi and pi",
    );
  }
  if (!finiteInRange(pitchRadians, -Math.PI / 2, Math.PI / 2)) {
    throw new MinecraftAdapterError(
      "E_MINECRAFT_SKILL_SCHEMA",
      "pitchRadians must be finite and between -pi/2 and pi/2",
    );
  }
  const request: MinecraftLookSkillRequest = {
    skillId: "look.v1",
    arguments: {
      yawRadians,
      pitchRadians,
    },
  };
  return request;
}
