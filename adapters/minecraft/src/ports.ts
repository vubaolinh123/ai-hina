import type {
  MinecraftConnectionConfig,
  MinecraftHarvestCollectionBaseline,
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
  navigateToHarvestTarget(
    target: MinecraftHarvestTarget,
    signal: AbortSignal,
  ): Promise<void>;
  equipBestHarvestTool(): Promise<void>;
  captureHarvestCollectionBaseline(
    itemName: string,
  ): MinecraftHarvestCollectionBaseline;
  isHarvestableLogDiggable(target: MinecraftHarvestTarget): boolean;
  digHarvestableLog(target: MinecraftHarvestTarget): Promise<void>;
  collectNewHarvestDrop(
    target: MinecraftHarvestTarget,
    baseline: MinecraftHarvestCollectionBaseline,
    signal: AbortSignal,
  ): Promise<void>;
  getInventoryItemCount(itemName: string): number;
  isHarvestableLogPresent(target: MinecraftHarvestTarget): boolean;
  quit(reason: string): void;
}

export type MinecraftBotFactory = (
  config: MinecraftConnectionConfig,
) => MinecraftBotPort;
