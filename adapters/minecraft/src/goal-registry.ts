import {
  MinecraftAdapterError,
  MINECRAFT_HARVEST_MAX_DISTANCE_BLOCKS,
  type MinecraftGoalDefinition,
  type MinecraftGoalRequest,
} from "./contracts.js";

export const HARVEST_NEARBY_LOG_GOAL_DEFINITION: MinecraftGoalDefinition =
  Object.freeze({
    id: "harvest.nearby-log.v1",
    version: 1,
    description:
      "Harvest exactly one nearby allowlisted log after fresh-state checks and postcondition verification.",
    preconditions: Object.freeze([
      "controller_online",
      "emergency_stop_not_latched",
      "fresh_physics_state",
      "player_state_available",
      "player_on_ground",
      `allowlisted_log_within_${MINECRAFT_HARVEST_MAX_DISTANCE_BLOCKS}_blocks`,
      "no_other_action_active",
    ]),
    timeoutMs: 12_000,
    budget: Object.freeze({
      maximumAttempts: 1,
    }),
    destructive: true,
    postcondition: Object.freeze({
      kind: "targeted_allowlisted_log_absent",
    }),
  });

const GOAL_REGISTRY = Object.freeze([HARVEST_NEARBY_LOG_GOAL_DEFINITION]);
const HARVESTABLE_LOG_NAMES = new Set([
  "oak_log",
  "spruce_log",
  "birch_log",
  "jungle_log",
  "acacia_log",
  "dark_oak_log",
  "mangrove_log",
  "cherry_log",
  "pale_oak_log",
]);

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

export function getMinecraftGoalRegistry(): readonly MinecraftGoalDefinition[] {
  return GOAL_REGISTRY;
}

export function isHarvestableLogName(value: unknown): value is string {
  return typeof value === "string" && HARVESTABLE_LOG_NAMES.has(value);
}

export function validateMinecraftGoalRequest(value: unknown): MinecraftGoalRequest {
  if (!isRecord(value) || Object.keys(value).sort().join(",") !== "goalId") {
    throw new MinecraftAdapterError(
      "E_MINECRAFT_GOAL_SCHEMA",
      "Goal request must contain exactly goalId",
    );
  }
  if (value.goalId !== HARVEST_NEARBY_LOG_GOAL_DEFINITION.id) {
    throw new MinecraftAdapterError(
      "E_MINECRAFT_GOAL_UNKNOWN",
      "Minecraft goal is not in the fixed allowlist",
    );
  }
  return { goalId: HARVEST_NEARBY_LOG_GOAL_DEFINITION.id };
}
