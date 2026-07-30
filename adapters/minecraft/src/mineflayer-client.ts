import { performance } from "node:perf_hooks";

import { createBot, type Bot, type BotOptions } from "mineflayer";

import {
  MINECRAFT_SNAPSHOT_LIMITS,
  MINECRAFT_WORLD_FRESHNESS_MAX_AGE_MS,
  type MinecraftConnectionConfig,
  type MinecraftHarvestTarget,
  type MinecraftNearbyEntity,
  type MinecraftVector,
  type MinecraftWorldFreshness,
  type MinecraftWorldState,
} from "./contracts.js";
import type {
  MinecraftBotEvent,
  MinecraftBotPort,
} from "./ports.js";
import { isHarvestableLogName } from "./goal-registry.js";

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

export function evaluateWorldStateFreshness(
  physicsTickSequence: number,
  lastPhysicsTickAtMs: number | null,
  nowMs: number,
): MinecraftWorldFreshness {
  if (
    !Number.isSafeInteger(physicsTickSequence) ||
    physicsTickSequence <= 0 ||
    lastPhysicsTickAtMs === null ||
    !Number.isFinite(lastPhysicsTickAtMs) ||
    !Number.isFinite(nowMs)
  ) {
    return {
      physicsTickSequence: 0,
      ageMs: null,
      maximumAgeMs: MINECRAFT_WORLD_FRESHNESS_MAX_AGE_MS,
      state: "unavailable",
    };
  }
  const ageMs = Math.max(
    0,
    Math.round((nowMs - lastPhysicsTickAtMs) * 1_000) / 1_000,
  );
  return {
    physicsTickSequence,
    ageMs,
    maximumAgeMs: MINECRAFT_WORLD_FRESHNESS_MAX_AGE_MS,
    state:
      ageMs <= MINECRAFT_WORLD_FRESHNESS_MAX_AGE_MS ? "fresh" : "stale",
  };
}

export class PhysicsFreshnessTracker {
  #physicsTickSequence = 0;
  #lastPhysicsTickAtMs: number | null = null;

  recordTick(nowMs = performance.now()): void {
    if (!Number.isFinite(nowMs)) {
      return;
    }
    this.#physicsTickSequence += 1;
    this.#lastPhysicsTickAtMs = nowMs;
  }

  read(nowMs = performance.now()): MinecraftWorldFreshness {
    return evaluateWorldStateFreshness(
      this.#physicsTickSequence,
      this.#lastPhysicsTickAtMs,
      nowMs,
    );
  }
}

class MineflayerBotAdapter implements MinecraftBotPort {
  readonly #bot: Bot;
  readonly #freshness = new PhysicsFreshnessTracker();

  constructor(bot: Bot) {
    this.#bot = bot;
    this.#bot.on("physicsTick", () => {
      this.#freshness.recordTick();
    });
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

  getWorldStateFreshness(): MinecraftWorldFreshness {
    return this.#freshness.read();
  }

  clearControlStates(): void {
    this.#bot.clearControlStates();
  }

  async look(yawRadians: number, pitchRadians: number): Promise<void> {
    await this.#bot.look(yawRadians, pitchRadians, true);
  }

  setControlState(control: "forward", enabled: boolean): void {
    this.#bot.setControlState(control, enabled);
  }

  waitForPhysicsTick(signal: AbortSignal): Promise<void> {
    return new Promise<void>((resolve, reject) => {
      const onTick = (): void => {
        cleanup();
        resolve();
      };
      const onAbort = (): void => {
        cleanup();
        reject(
          signal.reason instanceof Error
            ? signal.reason
            : new Error("Minecraft physics wait was cancelled"),
        );
      };
      const cleanup = (): void => {
        this.#bot.off("physicsTick", onTick);
        signal.removeEventListener("abort", onAbort);
      };
      if (signal.aborted) {
        onAbort();
        return;
      }
      this.#bot.once("physicsTick", onTick);
      signal.addEventListener("abort", onAbort, { once: true });
    });
  }

  async stopDigging(): Promise<void> {
    await this.#bot.stopDigging();
  }

  findNearestHarvestableLog(
    maximumDistanceBlocks: number,
  ): MinecraftHarvestTarget | null {
    if (
      !Number.isFinite(maximumDistanceBlocks) ||
      maximumDistanceBlocks <= 0 ||
      this.#bot.entity?.position === undefined
    ) {
      return null;
    }
    const block = this.#bot.findBlock({
      matching: (candidate) =>
        candidate !== null &&
        isHarvestableLogName(candidate.name),
      maxDistance: maximumDistanceBlocks,
    });
    if (block === null || !isHarvestableLogName(block.name)) {
      return null;
    }
    const horizontalDistanceBlocks = Math.hypot(
      this.#bot.entity.position.x - block.position.x,
      this.#bot.entity.position.z - block.position.z,
    );
    if (horizontalDistanceBlocks > maximumDistanceBlocks) {
      return null;
    }
    return {
      name: block.name,
      position: vector(block.position),
      distanceBlocks: rounded(horizontalDistanceBlocks),
    };
  }

  isHarvestApproachClear(
    target: MinecraftHarvestTarget,
    destination: { x: number; z: number },
  ): boolean {
    const playerPosition = this.#bot.entity?.position;
    if (
      playerPosition === undefined ||
      !Number.isFinite(target.position.x) ||
      !Number.isFinite(target.position.y) ||
      !Number.isFinite(target.position.z) ||
      !Number.isFinite(destination.x) ||
      !Number.isFinite(destination.z) ||
      target.position.y !== Math.floor(playerPosition.y)
    ) {
      return false;
    }
    const deltaX = destination.x - playerPosition.x;
    const deltaZ = destination.z - playerPosition.z;
    const distanceBlocks = Math.hypot(deltaX, deltaZ);
    if (distanceBlocks < 0.25 || distanceBlocks > 2) {
      return false;
    }
    const origin = playerPosition.floored();
    const sampleCount = Math.max(1, Math.ceil(distanceBlocks * 2));
    for (let index = 1; index <= sampleCount; index += 1) {
      const fraction = index / sampleCount;
      const x = Math.floor(playerPosition.x + deltaX * fraction);
      const z = Math.floor(playerPosition.z + deltaZ * fraction);
      const feet = this.#bot.blockAt(
        origin.offset(x - origin.x, 0, z - origin.z),
      );
      const head = this.#bot.blockAt(
        origin.offset(x - origin.x, 1, z - origin.z),
      );
      const ground = this.#bot.blockAt(
        origin.offset(x - origin.x, -1, z - origin.z),
      );
      if (
        feet === null ||
        head === null ||
        ground === null ||
        feet.boundingBox !== "empty" ||
        head.boundingBox !== "empty" ||
        ground.boundingBox !== "block"
      ) {
        return false;
      }
    }
    return true;
  }

  isHarvestableLogDiggable(target: MinecraftHarvestTarget): boolean {
    const block = this.#findExactHarvestableLog(target);
    return block !== null && this.#bot.canDigBlock(block);
  }

  async digHarvestableLog(target: MinecraftHarvestTarget): Promise<void> {
    const block = this.#findExactHarvestableLog(target);
    if (block === null || !this.isHarvestableLogDiggable(target)) {
      throw new Error("Targeted allowlisted log is no longer diggable");
    }
    await this.#bot.dig(block, true);
  }

  isHarvestableLogPresent(target: MinecraftHarvestTarget): boolean {
    return this.#findExactHarvestableLog(target) !== null;
  }

  #findExactHarvestableLog(target: MinecraftHarvestTarget) {
    if (
      !isHarvestableLogName(target.name) ||
      !Number.isFinite(target.position.x) ||
      !Number.isFinite(target.position.y) ||
      !Number.isFinite(target.position.z)
    ) {
      return null;
    }
    const block = this.#bot.findBlock({
      matching: (candidate) =>
        candidate !== null &&
        candidate.name === target.name &&
        isHarvestableLogName(candidate.name) &&
        candidate.position.x === target.position.x &&
        candidate.position.y === target.position.y &&
        candidate.position.z === target.position.z,
      maxDistance: 5,
    });
    return block ?? null;
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
