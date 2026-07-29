export const MINECRAFT_SNAPSHOT_LIMITS = Object.freeze({
  inventoryEntries: 46,
  nearbyEntities: 32,
});

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

export type MinecraftSkillId = "look.v1" | "move.step.v1";

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

export type MinecraftSkillDefinition =
  | MinecraftLookSkillDefinition
  | MinecraftMoveSkillDefinition;

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

export type MinecraftSkillRequest =
  | MinecraftLookSkillRequest
  | MinecraftMoveSkillRequest;

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

export interface MinecraftMovementEvidence {
  deltaX: number;
  deltaZ: number;
  forwardProgressBlocks: number;
  lateralDriftBlocks: number;
  horizontalDistanceBlocks: number;
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
    observed: MinecraftMovementEvidence | null;
  };
}

export type MinecraftSkillExecutionResult =
  | MinecraftLookSkillExecutionResult
  | MinecraftMoveSkillExecutionResult;

export class MinecraftAdapterError extends Error {
  readonly code: string;

  constructor(code: string, message: string, options?: ErrorOptions) {
    super(message, options);
    this.name = "MinecraftAdapterError";
    this.code = code;
  }
}
