import { performance } from "node:perf_hooks";

import { createBot, type Bot, type BotOptions } from "mineflayer";
import pathfinderRuntime from "mineflayer-pathfinder";

import {
  MINECRAFT_HARVEST_DIG_REACH_DISTANCE_BLOCKS,
  MINECRAFT_HARVEST_COLLECTION_VERIFY_TICKS,
  MINECRAFT_HARVEST_DISCOVERY_MAX_DISTANCE_BLOCKS,
  MINECRAFT_HARVEST_DROP_MATCH_DISTANCE_BLOCKS,
  MINECRAFT_HARVEST_ENTITY_BASELINE_LIMIT,
  MINECRAFT_HARVEST_PATHFINDER_POLICY,
  MINECRAFT_SNAPSHOT_LIMITS,
  MINECRAFT_WORLD_FRESHNESS_MAX_AGE_MS,
  type MinecraftConnectionConfig,
  type MinecraftHarvestCollectionBaseline,
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

const { Movements, goals, pathfinder } = pathfinderRuntime;

const HARVEST_TOOL_PRIORITY = Object.freeze([
  "netherite_axe",
  "diamond_axe",
  "iron_axe",
  "golden_axe",
  "stone_axe",
  "wooden_axe",
]);

export interface MinecraftHarvestDropCandidate {
  id: number;
  itemName: string | null;
  isValid: boolean;
  position: MinecraftVector;
}

export function selectNewMatchingHarvestDrop<
  T extends MinecraftHarvestDropCandidate,
>(
  candidates: readonly T[],
  target: MinecraftHarvestTarget,
  excludedEntityIds: ReadonlySet<number>,
): T | null {
  const matching = candidates
    .filter(
      (candidate) =>
        !excludedEntityIds.has(candidate.id)
        && candidate.isValid
        && Number.isSafeInteger(candidate.id)
        && candidate.id >= 0
        && hasFinitePosition(candidate.position)
        && candidate.itemName === target.name,
    )
    .map((candidate) => ({
      candidate,
      distance: Math.hypot(
        candidate.position.x - target.position.x,
        candidate.position.y - target.position.y,
        candidate.position.z - target.position.z,
      ),
    }))
    .filter(
      ({ distance }) =>
        distance <= MINECRAFT_HARVEST_DROP_MATCH_DISTANCE_BLOCKS,
    )
    .sort(
      (left, right) =>
        left.distance - right.distance
        || left.candidate.id - right.candidate.id,
    );
  return matching[0]?.candidate ?? null;
}

export function selectBestHarvestTool<T extends { name?: string | null }>(
  slots: readonly (T | null | undefined)[],
): T | null {
  for (const toolName of HARVEST_TOOL_PRIORITY) {
    const item = slots.find((candidate) => candidate?.name === toolName);
    if (item !== undefined && item !== null) {
      return item;
    }
  }
  return null;
}

function finiteNumber(value: unknown, fallback = 0): number {
  return typeof value === "number" && Number.isFinite(value) ? value : fallback;
}

function rounded(value: unknown): number {
  return Math.round(finiteNumber(value) * 1_000) / 1_000;
}

function hasFinitePosition(
  value: unknown,
): value is { x: number; y: number; z: number } {
  if (typeof value !== "object" || value === null) return false;
  const candidate = value as { x?: unknown; y?: unknown; z?: unknown };
  return (
    typeof candidate.x === "number"
    && Number.isFinite(candidate.x)
    && typeof candidate.y === "number"
    && Number.isFinite(candidate.y)
    && typeof candidate.z === "number"
    && Number.isFinite(candidate.z)
  );
}

function boundedPathfinderDiagnostic(error: unknown): string {
  const raw =
    error instanceof Error
      ? (error.stack ?? `${error.name}: ${error.message}`)
      : String(error);
  return raw.replaceAll("\u0000", "").slice(0, 2_048);
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
  #pathfinderReady = false;
  #pathfinderInitializationError: Error | null = null;

  constructor(bot: Bot) {
    this.#bot = bot;
    this.#bot.on("physicsTick", () => {
      this.#freshness.recordTick();
    });
    this.#bot.once("spawn", () => {
      try {
        this.#initializeBoundedPathfinder();
      } catch (error) {
        this.#pathfinderInitializationError =
          error instanceof Error
            ? error
            : new Error("Mineflayer pathfinder initialization failed");
      }
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

  async navigateToHarvestTarget(
    target: MinecraftHarvestTarget,
    signal: AbortSignal,
  ): Promise<void> {
    if (signal.aborted) {
      throw signal.reason instanceof Error
        ? signal.reason
        : new Error("Harvest pathfinding was cancelled");
    }
    if (!this.#pathfinderReady) {
      throw this.#pathfinderInitializationError
        ?? new Error("Mineflayer pathfinder is not ready");
    }
    try {
      const block = this.#findExactHarvestableLog(target);
      if (block === null) {
        throw new Error("The selected allowlisted log is no longer loaded");
      }
      const goal = new goals.GoalLookAtBlock(
        block.position,
        this.#bot.world,
        { reach: MINECRAFT_HARVEST_DIG_REACH_DISTANCE_BLOCKS },
      );
      const onAbort = (): void => {
        this.#bot.pathfinder.setGoal(null);
      };
      signal.addEventListener("abort", onAbort, { once: true });
      try {
        await this.#bot.pathfinder.goto(goal);
        if (signal.aborted) {
          throw signal.reason instanceof Error
            ? signal.reason
            : new Error("Harvest pathfinding was cancelled");
        }
      } finally {
        signal.removeEventListener("abort", onAbort);
        if (this.#bot.pathfinder.goal === goal) {
          this.#bot.pathfinder.setGoal(null);
        }
      }
    } catch (error) {
      if (!signal.aborted) {
        console.error(
          `[hina-minecraft:path:ERROR] ${boundedPathfinderDiagnostic(error)}`,
        );
      }
      throw error;
    }
  }

  async equipBestHarvestTool(): Promise<void> {
    const item = selectBestHarvestTool(this.#bot.inventory.slots);
    if (item !== null) {
      await this.#bot.equip(item, "hand");
      if (this.#bot.heldItem?.name !== item.name) {
        throw new Error("Mineflayer did not confirm the selected harvest tool");
      }
      return;
    }
    await this.#bot.unequip("hand");
    if (this.#bot.heldItem !== null) {
      throw new Error("Mineflayer did not confirm an empty harvest hand");
    }
  }

  captureHarvestCollectionBaseline(
    itemName: string,
  ): MinecraftHarvestCollectionBaseline {
    if (!isHarvestableLogName(itemName)) {
      throw new Error("Harvest collection item is outside the fixed log allowlist");
    }
    const entities = Object.values(this.#bot.entities);
    if (entities.length > MINECRAFT_HARVEST_ENTITY_BASELINE_LIMIT) {
      throw new Error("Loaded entity count exceeds the harvest baseline limit");
    }
    return {
      itemName,
      inventoryCount: this.getInventoryItemCount(itemName),
      preexistingEntityIds: entities
        .map((entity) => entity.id)
        .filter((entityId) => Number.isSafeInteger(entityId) && entityId >= 0)
        .sort((left, right) => left - right),
    };
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

  async collectNewHarvestDrop(
    target: MinecraftHarvestTarget,
    baseline: MinecraftHarvestCollectionBaseline,
    signal: AbortSignal,
  ): Promise<void> {
    if (
      !isHarvestableLogName(target.name)
      || baseline.itemName !== target.name
      || !Number.isSafeInteger(baseline.inventoryCount)
      || baseline.inventoryCount < 0
    ) {
      throw new Error("Harvest collection baseline does not match the target");
    }
    const excludedEntityIds = new Set(baseline.preexistingEntityIds);
    let pickupPathAttempted = false;
    for (
      let tick = 0;
      tick < MINECRAFT_HARVEST_COLLECTION_VERIFY_TICKS;
      tick += 1
    ) {
      if (signal.aborted) {
        throw signal.reason instanceof Error
          ? signal.reason
          : new Error("Harvest collection was cancelled");
      }
      if (
        this.getInventoryItemCount(target.name) > baseline.inventoryCount
      ) {
        return;
      }
      const drop = this.#findNewMatchingHarvestDrop(
        target,
        excludedEntityIds,
      );
      if (drop !== null && !pickupPathAttempted) {
        pickupPathAttempted = true;
        try {
          await this.#navigateToHarvestDrop(drop.position, signal);
        } catch (error) {
          if (
            this.getInventoryItemCount(target.name) > baseline.inventoryCount
          ) {
            return;
          }
          throw error;
        }
      }
      await this.waitForPhysicsTick(signal);
    }
    if (this.getInventoryItemCount(target.name) > baseline.inventoryCount) {
      return;
    }
    throw new Error(
      pickupPathAttempted
        ? "Matching harvested log drop did not enter inventory"
        : "No new matching harvested log drop appeared near the target",
    );
  }

  getInventoryItemCount(itemName: string): number {
    if (!isHarvestableLogName(itemName)) {
      throw new Error("Inventory item is outside the fixed log allowlist");
    }
    return this.#bot.inventory
      .items()
      .filter((item) => item.name === itemName)
      .reduce(
        (total, item) =>
          total
          + (Number.isSafeInteger(item.count) && item.count > 0
            ? item.count
            : 0),
        0,
      );
  }

  isHarvestableLogPresent(target: MinecraftHarvestTarget): boolean {
    return this.#findExactHarvestableLog(target) !== null;
  }

  #droppedItemName(
    entity: Bot["entities"][number],
  ): string | null {
    try {
      return entity.getDroppedItem()?.name ?? null;
    } catch {
      return null;
    }
  }

  #findNewMatchingHarvestDrop(
    target: MinecraftHarvestTarget,
    excludedEntityIds: ReadonlySet<number>,
  ): Bot["entities"][number] | null {
    const candidates = Object.values(this.#bot.entities).map((entity) => ({
      id: entity.id,
      itemName: this.#droppedItemName(entity),
      isValid: entity.isValid !== false,
      position: vector(entity.position),
      entity,
    }));
    return selectNewMatchingHarvestDrop(
      candidates,
      target,
      excludedEntityIds,
    )?.entity ?? null;
  }

  async #navigateToHarvestDrop(
    position: { x: number; y: number; z: number },
    signal: AbortSignal,
  ): Promise<void> {
    if (signal.aborted) {
      throw signal.reason instanceof Error
        ? signal.reason
        : new Error("Harvest collection pathfinding was cancelled");
    }
    if (!this.#pathfinderReady) {
      throw this.#pathfinderInitializationError
        ?? new Error("Mineflayer pathfinder is not ready");
    }
    const goal = new goals.GoalNear(
      position.x,
      position.y,
      position.z,
      1,
    );
    const onAbort = (): void => {
      this.#bot.pathfinder.setGoal(null);
    };
    signal.addEventListener("abort", onAbort, { once: true });
    try {
      await this.#bot.pathfinder.goto(goal);
      if (signal.aborted) {
        throw signal.reason instanceof Error
          ? signal.reason
          : new Error("Harvest collection pathfinding was cancelled");
      }
    } finally {
      signal.removeEventListener("abort", onAbort);
      if (this.#bot.pathfinder.goal === goal) {
        this.#bot.pathfinder.setGoal(null);
      }
    }
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
        isHarvestableLogName(candidate.name),
      useExtraInfo: (candidate) =>
        candidate !== null &&
        hasFinitePosition(candidate.position) &&
        candidate.position.x === target.position.x &&
        candidate.position.y === target.position.y &&
        candidate.position.z === target.position.z,
      maxDistance: MINECRAFT_HARVEST_DISCOVERY_MAX_DISTANCE_BLOCKS,
    });
    return block ?? null;
  }

  #initializeBoundedPathfinder(): void {
    if (this.#pathfinderReady) return;
    this.#bot.loadPlugin(pathfinder);
    const movements = new Movements(this.#bot);
    movements.canDig = MINECRAFT_HARVEST_PATHFINDER_POLICY.canDig;
    movements.canOpenDoors = MINECRAFT_HARVEST_PATHFINDER_POLICY.canOpenDoors;
    movements.allow1by1towers =
      MINECRAFT_HARVEST_PATHFINDER_POLICY.allowTowering;
    movements.allowFreeMotion = false;
    movements.allowParkour = MINECRAFT_HARVEST_PATHFINDER_POLICY.allowParkour;
    movements.allowSprinting =
      MINECRAFT_HARVEST_PATHFINDER_POLICY.allowSprinting;
    movements.allowEntityDetection =
      MINECRAFT_HARVEST_PATHFINDER_POLICY.allowEntityDetection;
    if (!MINECRAFT_HARVEST_PATHFINDER_POLICY.canPlace) {
      movements.scafoldingBlocks = [];
    }
    movements.maxDropDown =
      MINECRAFT_HARVEST_PATHFINDER_POLICY.maximumDropDownBlocks;
    movements.infiniteLiquidDropdownDistance =
      !MINECRAFT_HARVEST_PATHFINDER_POLICY.avoidLiquids;
    for (const name of [
      "water",
      "lava",
      "fire",
      "soul_fire",
      "cactus",
      "sweet_berry_bush",
      "powder_snow",
      "magma_block",
    ]) {
      const block = this.#bot.registry.blocksByName[name];
      if (block !== undefined) movements.blocksToAvoid.add(block.id);
    }
    this.#bot.pathfinder.setMovements(movements);
    this.#bot.pathfinder.thinkTimeout =
      MINECRAFT_HARVEST_PATHFINDER_POLICY.thinkTimeoutMs;
    this.#bot.pathfinder.tickTimeout =
      MINECRAFT_HARVEST_PATHFINDER_POLICY.tickTimeoutMs;
    (
      this.#bot.pathfinder as unknown as {
        searchRadius: number;
      }
    ).searchRadius = MINECRAFT_HARVEST_PATHFINDER_POLICY.searchRadiusBlocks;
    this.#pathfinderReady = true;
    this.#pathfinderInitializationError = null;
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
