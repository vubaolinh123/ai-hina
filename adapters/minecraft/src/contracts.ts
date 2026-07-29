export const MINECRAFT_SNAPSHOT_LIMITS = Object.freeze({
  inventoryEntries: 46,
  nearbyEntities: 32,
});

export const MINECRAFT_WORLD_FRESHNESS_MAX_AGE_MS = 1_000;
export const MINECRAFT_HARVEST_MAX_DISTANCE_BLOCKS = 4.5;

export type MinecraftConnectionPhase =
  | "disconnected"
  | "connecting"
  | "online"
  | "stopping"
  | "stopped"
  | "error";

export interface MinecraftConnectionConfig {
  host: string;
  port: number;
  username: string;
  version?: string;
  connectTimeoutMs: number;
  statusPort: number;
}

export interface MinecraftVector {
  x: number;
  y: number;
  z: number;
}

export interface MinecraftPlayerState {
  username: string;
  health: number;
  food: number;
  foodSaturation: number;
  oxygenLevel: number;
  gameMode: string;
  position: MinecraftVector;
  velocity: MinecraftVector;
  yaw: number;
  pitch: number;
  onGround: boolean;
}

export interface MinecraftInventoryEntry {
  slot: number;
  name: string;
  displayName: string;
  count: number;
  metadata: number;
}

export interface MinecraftNearbyEntity {
  id: number;
  type: string;
  name: string;
  username?: string;
  position: MinecraftVector;
  distance: number;
  health?: number;
}

export interface MinecraftWorldState {
  protocolVersion: string | null;
  dimension: string | null;
  timeOfDay: number | null;
  isDay: boolean | null;
  player: MinecraftPlayerState | null;
  inventory: MinecraftInventoryEntry[];
  nearbyEntities: MinecraftNearbyEntity[];
}

export interface MinecraftWorldFreshness {
  physicsTickSequence: number;
  ageMs: number | null;
  maximumAgeMs: number;
  state: "fresh" | "stale" | "unavailable";
}

export interface MinecraftAdapterErrorView {
  code: string;
  message: string;
}

export interface MinecraftControllerStatus {
  schemaVersion: 1;
  phase: MinecraftConnectionPhase;
  emergencyStopped: boolean;
  sequence: number;
  target: {
    host: string;
    port: number;
    username: string;
    version: string | null;
  } | null;
  connectedAt: string | null;
  capturedAt: string;
  world: MinecraftWorldState | null;
  worldFreshness: MinecraftWorldFreshness | null;
  lastError: MinecraftAdapterErrorView | null;
}

export interface EmergencyStopResult {
  alreadyStopped: boolean;
  localActionsStoppedAt: string;
  dispatchDurationMs: number;
}

export interface MinecraftDisconnectResult {
  alreadyDisconnected: boolean;
  localActionsStoppedAt: string;
  dispatchDurationMs: number;
}

export type MinecraftSkillId = "look.v1" | "move.step.v1" | "move.to.v1";

interface MinecraftSkillDefinitionBase {
  id: MinecraftSkillId;
  version: 1;
  description: string;
  preconditions: readonly string[];
  timeoutMs: number;
  budget: {
    maximumAttempts: 1;
  };
  destructive: false;
}

export interface MinecraftLookSkillDefinition
  extends MinecraftSkillDefinitionBase {
  id: "look.v1";
  postcondition: {
    kind: "player_rotation_matches";
    toleranceRadians: number;
  };
}

export type MinecraftCardinalDirection =
  | "north"
  | "east"
  | "south"
  | "west";

export interface MinecraftMoveSkillDefinition
  extends MinecraftSkillDefinitionBase {
  id: "move.step.v1";
  postcondition: {
    kind: "player_cardinal_displacement_matches";
    minimumProgressRatio: number;
    maximumOvershootBlocks: number;
    lateralToleranceBlocks: number;
  };
}

export interface MinecraftMoveToSkillDefinition
  extends MinecraftSkillDefinitionBase {
  id: "move.to.v1";
  postcondition: {
    kind: "player_target_coordinate_matches";
    minimumProgressRatio: number;
    maximumOvershootBlocks: number;
    lateralToleranceBlocks: number;
  };
}

export type MinecraftSkillDefinition =
  | MinecraftLookSkillDefinition
  | MinecraftMoveSkillDefinition
  | MinecraftMoveToSkillDefinition;

export interface MinecraftLookSkillRequest {
  skillId: "look.v1";
  arguments: {
    yawRadians: number;
    pitchRadians: number;
  };
}

export interface MinecraftMoveSkillRequest {
  skillId: "move.step.v1";
  arguments: {
    direction: MinecraftCardinalDirection;
    distanceBlocks: number;
  };
}

export interface MinecraftMoveToSkillRequest {
  skillId: "move.to.v1";
  arguments: {
    targetX: number;
    targetZ: number;
  };
}

export type MinecraftMovementSkillRequest =
  | MinecraftMoveSkillRequest
  | MinecraftMoveToSkillRequest;

export type MinecraftSkillRequest =
  | MinecraftLookSkillRequest
  | MinecraftMovementSkillRequest;

export interface MinecraftRotationEvidence {
  yawRadians: number;
  pitchRadians: number;
}

interface MinecraftSkillExecutionResultBase {
  schemaVersion: 1;
  executionId: number;
  skillId: MinecraftSkillId;
  status: "succeeded" | "failed";
  startedAt: string;
  finishedAt: string;
  durationMs: number;
  attempts: 1;
  precondition: {
    passed: boolean;
  };
  error: MinecraftAdapterErrorView | null;
}

export interface MinecraftLookSkillExecutionResult
  extends MinecraftSkillExecutionResultBase {
  skillId: "look.v1";
  postcondition: {
    passed: boolean;
    toleranceRadians: number;
    expected: MinecraftRotationEvidence;
    observed: MinecraftRotationEvidence | null;
  };
}

export interface MinecraftMovementProgressEvidence {
  physicsTicksObserved: number;
  stagnantTicksObserved: number;
  maximumForwardProgressBlocks: number;
}

export interface MinecraftMovementEvidence
  extends MinecraftMovementProgressEvidence {
  deltaX: number;
  deltaZ: number;
  forwardProgressBlocks: number;
  lateralDriftBlocks: number;
  horizontalDistanceBlocks: number;
  remainingDistanceBlocks: number;
}

export interface MinecraftMoveSkillExecutionResult
  extends MinecraftSkillExecutionResultBase {
  skillId: "move.step.v1";
  postcondition: {
    passed: boolean;
    minimumProgressBlocks: number;
    maximumProgressBlocks: number;
    lateralToleranceBlocks: number;
    expected: {
      direction: MinecraftCardinalDirection;
      distanceBlocks: number;
    };
    progress: MinecraftMovementProgressEvidence;
    observed: MinecraftMovementEvidence | null;
  };
}

export interface MinecraftMoveToSkillExecutionResult
  extends MinecraftSkillExecutionResultBase {
  skillId: "move.to.v1";
  postcondition: {
    passed: boolean;
    targetDistanceBlocks: number | null;
    minimumProgressBlocks: number | null;
    maximumProgressBlocks: number | null;
    lateralToleranceBlocks: number;
    expected: {
      targetX: number;
      targetZ: number;
    };
    progress: MinecraftMovementProgressEvidence;
    observed: MinecraftMovementEvidence | null;
  };
}

export type MinecraftMovementSkillExecutionResult =
  | MinecraftMoveSkillExecutionResult
  | MinecraftMoveToSkillExecutionResult;

export type MinecraftSkillExecutionResult =
  | MinecraftLookSkillExecutionResult
  | MinecraftMovementSkillExecutionResult;

/**
 * High-level goals are deliberately separate from the internal skill set.
 * The model may choose only one of these identifiers; it never supplies
 * coordinates, Mineflayer calls, scripts, or an arbitrary action sequence.
 */
export type MinecraftGoalId = "harvest.nearby-log.v1";

export interface MinecraftGoalDefinition {
  id: MinecraftGoalId;
  version: 1;
  description: string;
  preconditions: readonly string[];
  timeoutMs: number;
  budget: {
    maximumAttempts: 1;
  };
  destructive: true;
  postcondition: {
    kind: "targeted_allowlisted_log_absent";
  };
}

export interface MinecraftGoalRequest {
  goalId: "harvest.nearby-log.v1";
}

export interface MinecraftHarvestTarget {
  name: string;
  position: MinecraftVector;
  distanceBlocks: number;
}

export interface MinecraftGoalExecutionResult {
  schemaVersion: 1;
  executionId: number;
  goalId: MinecraftGoalId;
  status: "succeeded" | "failed";
  startedAt: string;
  finishedAt: string;
  durationMs: number;
  attempts: 1;
  precondition: {
    passed: boolean;
  };
  target: MinecraftHarvestTarget | null;
  postcondition: {
    passed: boolean;
    kind: "targeted_allowlisted_log_absent";
    targetStillPresent: boolean | null;
  };
  error: MinecraftAdapterErrorView | null;
}

export class MinecraftAdapterError extends Error {
  readonly code: string;

  constructor(code: string, message: string, options?: ErrorOptions) {
    super(message, options);
    this.name = "MinecraftAdapterError";
    this.code = code;
  }
}
