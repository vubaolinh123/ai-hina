import {
  MinecraftAdapterError,
  type MinecraftLookSkillRequest,
  type MinecraftSkillDefinition,
  type MinecraftSkillRequest,
} from "./contracts.js";

export const LOOK_SKILL_DEFINITION: MinecraftSkillDefinition = Object.freeze({
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

const SKILL_REGISTRY = Object.freeze([LOOK_SKILL_DEFINITION]);
const ROOT_FIELDS = Object.freeze(["arguments", "skillId"]);
const LOOK_FIELDS = Object.freeze(["pitchRadians", "yawRadians"]);

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
  if (value.skillId !== LOOK_SKILL_DEFINITION.id) {
    throw new MinecraftAdapterError(
      "E_MINECRAFT_SKILL_UNKNOWN",
      "Minecraft skill is not in the fixed allowlist",
    );
  }
  if (
    !isRecord(value.arguments) ||
    !hasExactFields(value.arguments, LOOK_FIELDS)
  ) {
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
