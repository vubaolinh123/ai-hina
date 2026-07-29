import { createBot, type Bot, type BotOptions } from "mineflayer";

import {
  MINECRAFT_SNAPSHOT_LIMITS,
  type MinecraftConnectionConfig,
  type MinecraftNearbyEntity,
  type MinecraftVector,
  type MinecraftWorldState,
} from "./contracts.js";
import type {
  MinecraftBotEvent,
  MinecraftBotPort,
} from "./ports.js";

function finiteNumber(value: unknown, fallback = 0): number {
  return typeof value === "number" && Number.isFinite(value) ? value : fallback;
}

function rounded(value: unknown): number {
  return Math.round(finiteNumber(value) * 1_000) / 1_000;
}

function vector(value: unknown): MinecraftVector {
  const candidate = value as
    | { x?: unknown; y?: unknown; z?: unknown }
    | undefined;
  return {
    x: rounded(candidate?.x),
    y: rounded(candidate?.y),
    z: rounded(candidate?.z),
  };
}

function cleanLabel(value: unknown, fallback: string): string {
  if (typeof value !== "string") {
    return fallback;
  }
  const compact = value.replace(/[\u0000-\u001f\u007f]/g, "").trim();
  return compact.slice(0, 64) || fallback;
}

function optionalHealth(value: unknown): number | undefined {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    return undefined;
  }
  return rounded(value);
}

class MineflayerBotAdapter implements MinecraftBotPort {
  readonly #bot: Bot;

  constructor(bot: Bot) {
    this.#bot = bot;
  }

  on(
    event: MinecraftBotEvent,
    listener: (payload?: unknown) => void,
  ): () => void {
    const wrapped = (payload?: unknown): void => listener(payload);
    this.#bot.on(event, wrapped);
    return () => this.#bot.off(event, wrapped);
  }

  captureWorldState(): MinecraftWorldState {
    return normalizeMineflayerWorldState(this.#bot);
  }

  clearControlStates(): void {
    this.#bot.clearControlStates();
  }

  async stopDigging(): Promise<void> {
    await this.#bot.stopDigging();
  }

  quit(reason: string): void {
    this.#bot.quit(reason);
  }
}

export function normalizeMineflayerWorldState(bot: Bot): MinecraftWorldState {
  const playerEntity = bot.entity;
  const playerPosition = playerEntity?.position;
  const nearbyEntities = Object.values(bot.entities)
      .filter((entity) => entity !== playerEntity && entity.position !== undefined)
      .map((entity): MinecraftNearbyEntity => {
        const distance =
          playerPosition === undefined
            ? Number.POSITIVE_INFINITY
            : playerPosition.distanceTo(entity.position);
        const health = optionalHealth(
          (entity as unknown as { health?: unknown }).health,
        );
        return {
          id: finiteNumber(entity.id),
          type: cleanLabel(entity.type, "unknown"),
          name: cleanLabel(entity.name, "unknown"),
          ...(entity.username === undefined
            ? {}
            : { username: cleanLabel(entity.username, "unknown") }),
          position: vector(entity.position),
          distance: rounded(distance),
          ...(health === undefined ? {} : { health }),
        };
      })
      .sort((left, right) => left.distance - right.distance)
      .slice(0, MINECRAFT_SNAPSHOT_LIMITS.nearbyEntities);

  const inventory = bot.inventory.slots
      .map((item, slot) => ({ item, slot }))
      .filter((entry) => entry.item !== null)
      .slice(0, MINECRAFT_SNAPSHOT_LIMITS.inventoryEntries)
      .map(({ item, slot }) => ({
        slot,
        name: cleanLabel(item?.name, "unknown"),
        displayName: cleanLabel(item?.displayName, "unknown"),
        count: Math.max(0, Math.trunc(finiteNumber(item?.count))),
        metadata: Math.trunc(finiteNumber(item?.metadata)),
      }));

  const game = bot.game as
      | { dimension?: unknown; gameMode?: unknown }
      | undefined;
  const time = bot.time as
      | { timeOfDay?: unknown; isDay?: unknown }
      | undefined;

  return {
    protocolVersion: cleanLabel(bot.version, "unknown"),
    dimension:
      typeof game?.dimension === "string"
        ? cleanLabel(game.dimension, "unknown")
        : null,
    timeOfDay:
      typeof time?.timeOfDay === "number"
        ? Math.trunc(finiteNumber(time.timeOfDay))
        : null,
    isDay: typeof time?.isDay === "boolean" ? time.isDay : null,
    player:
      playerEntity === undefined
        ? null
        : {
            username: cleanLabel(bot.username, "Hina"),
            health: rounded(bot.health),
            food: rounded(bot.food),
            foodSaturation: rounded(bot.foodSaturation),
            oxygenLevel: rounded(bot.oxygenLevel),
            gameMode: cleanLabel(game?.gameMode, "unknown"),
            position: vector(playerEntity.position),
            velocity: vector(playerEntity.velocity),
            yaw: rounded(playerEntity.yaw),
            pitch: rounded(playerEntity.pitch),
            onGround: Boolean(playerEntity.onGround),
          },
    inventory,
    nearbyEntities,
  };
}

export function createMineflayerBot(
  config: MinecraftConnectionConfig,
): MinecraftBotPort {
  const options: BotOptions = {
    host: config.host,
    port: config.port,
    username: config.username,
    auth: "offline",
    hideErrors: true,
    ...(config.version === undefined ? {} : { version: config.version }),
  };
  return new MineflayerBotAdapter(createBot(options));
}
