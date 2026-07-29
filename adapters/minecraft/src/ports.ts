import type {
  MinecraftConnectionConfig,
  MinecraftWorldState,
} from "./contracts.js";

export type MinecraftBotEvent = "spawn" | "end" | "kicked" | "error";

export interface MinecraftBotPort {
  on(
    event: MinecraftBotEvent,
    listener: (payload?: unknown) => void,
  ): () => void;
  captureWorldState(): MinecraftWorldState;
  clearControlStates(): void;
  stopDigging(): Promise<void>;
  quit(reason: string): void;
}

export type MinecraftBotFactory = (
  config: MinecraftConnectionConfig,
) => MinecraftBotPort;
