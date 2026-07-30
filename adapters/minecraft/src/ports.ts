import type {
  MinecraftConnectionConfig,
  MinecraftHarvestTarget,
  MinecraftWorldFreshness,
  MinecraftWorldState,
} from "./contracts.js";

export type MinecraftBotEvent = "spawn" | "end" | "kicked" | "error";

export interface MinecraftBotPort {
  on(
    event: MinecraftBotEvent,
    listener: (payload?: unknown) => void,
  ): () => void;
  captureWorldState(): MinecraftWorldState;
  getWorldStateFreshness(): MinecraftWorldFreshness;
  look(yawRadians: number, pitchRadians: number): Promise<void>;
  setControlState(control: "forward", enabled: boolean): void;
  waitForPhysicsTick(signal: AbortSignal): Promise<void>;
  clearControlStates(): void;
  stopDigging(): Promise<void>;
  findNearestHarvestableLog(
    maximumDistanceBlocks: number,
  ): MinecraftHarvestTarget | null;
  isHarvestApproachClear(
    target: MinecraftHarvestTarget,
    destination: { x: number; z: number },
  ): boolean;
  isHarvestableLogDiggable(target: MinecraftHarvestTarget): boolean;
  digHarvestableLog(target: MinecraftHarvestTarget): Promise<void>;
  isHarvestableLogPresent(target: MinecraftHarvestTarget): boolean;
  quit(reason: string): void;
}

export type MinecraftBotFactory = (
  config: MinecraftConnectionConfig,
) => MinecraftBotPort;
