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

export class MinecraftAdapterError extends Error {
  readonly code: string;

  constructor(code: string, message: string, options?: ErrorOptions) {
    super(message, options);
    this.name = "MinecraftAdapterError";
    this.code = code;
  }
}
