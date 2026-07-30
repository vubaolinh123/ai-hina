import {
  MinecraftAdapterError,
  MINECRAFT_HARVEST_DISCOVERY_MAX_DISTANCE_BLOCKS,
  MINECRAFT_HARVEST_DROP_MATCH_DISTANCE_BLOCKS,
  MINECRAFT_HARVEST_ENTITY_BASELINE_LIMIT,
  MINECRAFT_HARVEST_PATH_SEARCH_RADIUS_BLOCKS,
  MINECRAFT_HARVEST_VERTICAL_MAX_DISTANCE_BLOCKS,
  type MinecraftGoalDefinition,
  type MinecraftGoalRequest,
} from "./contracts.js";

export const GATHER_NEARBY_LOG_GOAL_DEFINITION: MinecraftGoalDefinition =
  Object.freeze({
    id: "gather.nearby-log.v1",
    version: 1,
    description:
      "Find, safely path to, harvest and collect exactly one loaded allowlisted log after fresh-state checks.",
    preconditions: Object.freeze([
      "controller_online",
      "emergency_stop_not_latched",
      "fresh_physics_state",
      "player_state_available",
      "player_on_ground",
      `allowlisted_log_within_${MINECRAFT_HARVEST_DISCOVERY_MAX_DISTANCE_BLOCKS}_horizontal_blocks`,
      `vertical_offset_at_most_${MINECRAFT_HARVEST_VERTICAL_MAX_DISTANCE_BLOCKS}_blocks`,
      `bounded_path_search_radius_${MINECRAFT_HARVEST_PATH_SEARCH_RADIUS_BLOCKS}_blocks`,
      "pathfinder_cannot_dig_place_sprint_parkour_or_enter_liquids",
      `new_matching_drop_within_${MINECRAFT_HARVEST_DROP_MATCH_DISTANCE_BLOCKS}_blocks_of_target`,
      `preexisting_entity_snapshot_at_most_${MINECRAFT_HARVEST_ENTITY_BASELINE_LIMIT}`,
      "no_other_action_active",
    ]),
    timeoutMs: 30_000,
    budget: Object.freeze({
      maximumAttempts: 1,
    }),
    destructive: true,
    postcondition: Object.freeze({
      kind: "targeted_allowlisted_log_collected",
    }),
  });

const GOAL_REGISTRY = Object.freeze([GATHER_NEARBY_LOG_GOAL_DEFINITION]);
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
  if (value.goalId !== GATHER_NEARBY_LOG_GOAL_DEFINITION.id) {
    throw new MinecraftAdapterError(
      "E_MINECRAFT_GOAL_UNKNOWN",
      "Minecraft goal is not in the fixed allowlist",
    );
  }
  return { goalId: GATHER_NEARBY_LOG_GOAL_DEFINITION.id };
}
