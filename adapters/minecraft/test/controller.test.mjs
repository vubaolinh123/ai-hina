import assert from "node:assert/strict";
import { EventEmitter } from "node:events";
import test from "node:test";

import {
  MinecraftAdapterError,
  MinecraftController,
} from "../dist/index.js";

const CONFIG = Object.freeze({
  host: "127.0.0.1",
  port: 25565,
  username: "Hina",
  connectTimeoutMs: 1_000,
  statusPort: 8766,
});

const WORLD = Object.freeze({
  protocolVersion: "1.21.8",
  dimension: "overworld",
  timeOfDay: 1000,
  isDay: true,
  player: {
    username: "Hina",
    health: 20,
    food: 20,
    foodSaturation: 5,
    oxygenLevel: 20,
    gameMode: "survival",
    position: { x: 1, y: 64, z: 2 },
    velocity: { x: 0, y: 0, z: 0 },
    yaw: 0,
    pitch: 0,
    onGround: true,
  },
  inventory: [],
  nearbyEntities: [],
});

class FakeBotPort {
  emitter = new EventEmitter();
  clearCalls = 0;
  stopDiggingCalls = 0;
  quitCalls = 0;
  quitReason = null;
  world = WORLD;
  lookCalls = [];
  controlCalls = [];
  forwardEnabled = false;
  harvestTarget = {
    name: "oak_log",
    position: { x: 2, y: 64, z: 2 },
    distanceBlocks: 1,
  };
  harvestPresent = true;
  harvestCalls = [];
  harvestNavigationCalls = [];
  harvestDiggable = true;
  harvestAxeAvailable = false;
  harvestToolCalls = [];
  harvestCollectionCalls = [];
  harvestInventoryCount = 0;
  harvestPreexistingEntityIds = [];
  operationLog = [];
  equipBestHarvestToolImplementation = async () => {};
  collectNewHarvestDropImplementation = async () => {
    this.harvestInventoryCount += 1;
  };
  worldFreshness = {
    physicsTickSequence: 1,
    ageMs: 0,
    maximumAgeMs: 1_000,
    state: "fresh",
  };
  lookImplementation = async (yawRadians, pitchRadians) => {
    this.world = structuredClone(this.world);
    this.world.player.yaw = yawRadians;
    this.world.player.pitch = pitchRadians;
  };
  physicsTickImplementation = async () => {
    if (!this.forwardEnabled) return;
    this.world = structuredClone(this.world);
    const yaw = this.world.player.yaw;
    this.world.player.position.x += -Math.sin(yaw) * 0.1;
    this.world.player.position.z += Math.cos(yaw) * 0.1;
  };
  digHarvestableLogImplementation = async () => {
    this.harvestPresent = false;
  };
  navigateToHarvestTargetImplementation = async (target, signal) => {
    if (signal.aborted) throw signal.reason;
    const current = this.world.player.position;
    const deltaX = target.position.x - current.x;
    const deltaZ = target.position.z - current.z;
    const distanceBlocks = Math.hypot(deltaX, deltaZ);
    if (distanceBlocks > 3) {
      this.world = structuredClone(this.world);
      this.world.player.position.x =
        target.position.x - (deltaX / distanceBlocks) * 2.5;
      this.world.player.position.z =
        target.position.z - (deltaZ / distanceBlocks) * 2.5;
    }
  };

  on(event, listener) {
    this.emitter.on(event, listener);
    return () => this.emitter.off(event, listener);
  }

  emit(event, payload) {
    this.emitter.emit(event, payload);
  }

  captureWorldState() {
    return structuredClone(this.world);
  }

  getWorldStateFreshness() {
    return structuredClone(this.worldFreshness);
  }

  async look(yawRadians, pitchRadians) {
    this.lookCalls.push({ yawRadians, pitchRadians });
    await this.lookImplementation(yawRadians, pitchRadians);
  }

  setControlState(control, enabled) {
    this.controlCalls.push({ control, enabled });
    if (control === "forward") this.forwardEnabled = enabled;
  }

  async waitForPhysicsTick(signal) {
    if (signal.aborted) throw signal.reason;
    await this.physicsTickImplementation(signal);
  }

  clearControlStates() {
    this.clearCalls += 1;
    this.forwardEnabled = false;
  }

  async stopDigging() {
    this.stopDiggingCalls += 1;
  }

  findNearestHarvestableLog(maximumDistanceBlocks) {
    if (
      this.harvestTarget === null
      || this.harvestTarget.distanceBlocks > maximumDistanceBlocks
    ) {
      return null;
    }
    return structuredClone(this.harvestTarget);
  }

  async navigateToHarvestTarget(target, signal) {
    this.harvestNavigationCalls.push(structuredClone(target));
    this.operationLog.push("navigate");
    await this.navigateToHarvestTargetImplementation(target, signal);
  }

  isHarvestableLogDiggable(target) {
    return this.harvestDiggable && this.isHarvestableLogPresent(target);
  }

  async equipBestHarvestTool() {
    const tool = this.harvestAxeAvailable ? "axe" : "hand";
    this.harvestToolCalls.push(tool);
    this.operationLog.push(`equip:${tool}`);
    await this.equipBestHarvestToolImplementation();
  }

  async digHarvestableLog(target) {
    this.harvestCalls.push(structuredClone(target));
    this.operationLog.push("dig");
    await this.digHarvestableLogImplementation(target);
  }

  captureHarvestCollectionBaseline(itemName) {
    return {
      itemName,
      inventoryCount: this.harvestInventoryCount,
      preexistingEntityIds: [...this.harvestPreexistingEntityIds],
    };
  }

  async collectNewHarvestDrop(target, baseline, signal) {
    this.harvestCollectionCalls.push({
      target: structuredClone(target),
      baseline: structuredClone(baseline),
    });
    this.operationLog.push("collect");
    if (signal.aborted) throw signal.reason;
    await this.collectNewHarvestDropImplementation(target, baseline, signal);
  }

  getInventoryItemCount(itemName) {
    return itemName === this.harvestTarget?.name
      ? this.harvestInventoryCount
      : 0;
  }

  isHarvestableLogPresent(target) {
    return Boolean(
      this.harvestPresent
      && this.harvestTarget !== null
      && this.harvestTarget.name === target.name
      && this.harvestTarget.position.x === target.position.x
      && this.harvestTarget.position.y === target.position.y
      && this.harvestTarget.position.z === target.position.z,
    );
  }

  quit(reason) {
    this.quitCalls += 1;
    this.quitReason = reason;
  }
}

test("connects through the injected port and returns normalized status", async () => {
  const fake = new FakeBotPort();
  const controller = new MinecraftController(
    () => fake,
    () => new Date("2026-07-29T12:00:00.000Z"),
  );
  const connected = controller.start(CONFIG);
  assert.equal(controller.getStatus().phase, "connecting");
  fake.emit("spawn");
  const status = await connected;

  assert.equal(status.phase, "online");
  assert.equal(status.target.host, "127.0.0.1");
  assert.equal(status.world.player.username, "Hina");
  assert.equal(status.connectedAt, "2026-07-29T12:00:00.000Z");
  assert.deepEqual(status.worldFreshness, fake.worldFreshness);
});

test("maps connection failures to a stable bounded error", async () => {
  const fake = new FakeBotPort();
  const controller = new MinecraftController(() => fake);
  const connected = controller.start(CONFIG);
  fake.emit("error", new Error("socket failed\u0000with control"));

  await assert.rejects(
    connected,
    (error) =>
      error instanceof MinecraftAdapterError &&
      error.code === "E_MINECRAFT_CONNECT" &&
      !error.message.includes("\u0000"),
  );
  assert.equal(controller.getStatus().phase, "disconnected");
});

test("releases a failed connection so the owner can retry without restarting", async () => {
  const firstBot = new FakeBotPort();
  const secondBot = new FakeBotPort();
  const bots = [firstBot, secondBot];
  const controller = new MinecraftController(() => bots.shift());

  const failed = controller.start(CONFIG);
  firstBot.emit("error", new Error("connect ECONNREFUSED 127.0.0.1:25565"));

  await assert.rejects(
    failed,
    (error) =>
      error instanceof MinecraftAdapterError &&
      error.code === "E_MINECRAFT_CONNECT",
  );
  const failedStatus = controller.getStatus();
  assert.equal(failedStatus.phase, "disconnected");
  assert.deepEqual(failedStatus.lastError, {
    code: "E_MINECRAFT_CONNECT",
    message: "connect ECONNREFUSED 127.0.0.1:25565",
  });
  assert.equal(firstBot.quitReason, "Hina connection attempt failed");

  const retried = controller.start(CONFIG);
  firstBot.emit("end", "old socket finished");
  secondBot.emit("spawn");

  const retriedStatus = await retried;
  assert.equal(retriedStatus.phase, "online");
  assert.equal(controller.getStatus().phase, "online");
});

test("releases a lost online connection so the owner can reconnect", async () => {
  const firstBot = new FakeBotPort();
  const secondBot = new FakeBotPort();
  const bots = [firstBot, secondBot];
  const controller = new MinecraftController(() => bots.shift());

  const firstConnection = controller.start(CONFIG);
  firstBot.emit("spawn");
  await firstConnection;

  firstBot.emit("end", "socket closed");
  assert.equal(controller.getStatus().phase, "disconnected");
  assert.deepEqual(controller.getStatus().lastError, {
    code: "E_MINECRAFT_ENDED",
    message: "socket closed",
  });

  const secondConnection = controller.start(CONFIG);
  secondBot.emit("spawn");
  assert.equal((await secondConnection).phase, "online");
});

test("emergency stop is latched, idempotent and disconnects immediately", async () => {
  const fake = new FakeBotPort();
  const controller = new MinecraftController(() => fake);
  const connected = controller.start(CONFIG);
  fake.emit("spawn");
  await connected;

  const first = await controller.emergencyStop();
  const sequenceAfterFirst = controller.getStatus().sequence;
  const second = await controller.emergencyStop();

  assert.equal(first.alreadyStopped, false);
  assert.equal(second.alreadyStopped, true);
  assert.ok(first.dispatchDurationMs < 250);
  assert.equal(fake.clearCalls, 1);
  assert.equal(fake.stopDiggingCalls, 1);
  assert.equal(fake.quitCalls, 1);
  assert.equal(fake.quitReason, "Hina emergency stop");
  assert.equal(controller.getStatus().sequence, sequenceAfterFirst);
  assert.equal(controller.getStatus().phase, "stopped");
  assert.equal(controller.getStatus().emergencyStopped, true);
  await assert.rejects(
    controller.start(CONFIG),
    (error) =>
      error instanceof MinecraftAdapterError &&
      error.code === "E_MINECRAFT_EMERGENCY_STOPPED",
  );
});

test("emergency stop rejects an in-flight connection instead of hanging", async () => {
  const fake = new FakeBotPort();
  const controller = new MinecraftController(() => fake);
  const connected = controller.start(CONFIG);
  await controller.emergencyStop();

  await assert.rejects(
    connected,
    (error) =>
      error instanceof MinecraftAdapterError &&
      error.code === "E_MINECRAFT_EMERGENCY_STOPPED",
  );
  assert.equal(controller.getStatus().phase, "stopped");
});

test("owner disconnect is idempotent and permits reconnect", async () => {
  const firstBot = new FakeBotPort();
  const secondBot = new FakeBotPort();
  const bots = [firstBot, secondBot];
  const controller = new MinecraftController(() => bots.shift());

  const firstConnection = controller.start(CONFIG);
  firstBot.emit("spawn");
  await firstConnection;
  const first = await controller.disconnect();
  const second = await controller.disconnect();

  assert.equal(first.alreadyDisconnected, false);
  assert.equal(second.alreadyDisconnected, true);
  assert.equal(firstBot.clearCalls, 1);
  assert.equal(firstBot.quitReason, "Hina owner disconnect");
  assert.equal(controller.getStatus().phase, "disconnected");

  const reconnected = controller.start(CONFIG);
  secondBot.emit("spawn");
  assert.equal((await reconnected).phase, "online");
});

test("gather.nearby-log.v1 harvests one allowlisted log and verifies collection", async () => {
  const fake = new FakeBotPort();
  const controller = new MinecraftController(() => fake);
  const connected = controller.start(CONFIG);
  fake.emit("spawn");
  await connected;

  const result = await controller.executeGoal({
    goalId: "gather.nearby-log.v1",
  });

  assert.equal(result.status, "succeeded");
  assert.equal(result.goalId, "gather.nearby-log.v1");
  assert.equal(result.attempts, 1);
  assert.deepEqual(result.target, fake.harvestTarget);
  assert.equal(result.precondition.passed, true);
  assert.equal(result.postcondition.passed, true);
  assert.equal(result.postcondition.targetStillPresent, false);
  assert.equal(result.postcondition.inventoryItemName, "oak_log");
  assert.equal(result.postcondition.inventoryCountBefore, 0);
  assert.equal(result.postcondition.inventoryCountAfter, 1);
  assert.equal(result.error, null);
  assert.equal(fake.harvestNavigationCalls.length, 1);
  assert.equal(fake.harvestCalls.length, 1);
  assert.equal(fake.harvestCollectionCalls.length, 1);
  assert.equal(fake.clearCalls, 1);
});

test("gather.nearby-log.v1 reaches a loaded log beyond the retired eight-block bound with one path request", async () => {
  const fake = new FakeBotPort();
  fake.harvestTarget = {
    name: "oak_log",
    position: { x: 25, y: 64, z: 2 },
    distanceBlocks: 24,
  };
  const controller = new MinecraftController(() => fake);
  const connected = controller.start(CONFIG);
  fake.emit("spawn");
  await connected;

  const result = await controller.executeGoal({
    goalId: "gather.nearby-log.v1",
  });

  assert.equal(result.status, "succeeded");
  assert.equal(fake.harvestCalls.length, 1);
  assert.equal(fake.harvestNavigationCalls.length, 1);
  assert.equal(fake.controlCalls.length, 0);
  assert.equal(fake.clearCalls, 1);
});

test("gather.nearby-log.v1 fails closed when bounded pathfinding finds no safe route", async () => {
  const fake = new FakeBotPort();
  fake.harvestTarget = {
    name: "oak_log",
    position: { x: 25, y: 64, z: 2 },
    distanceBlocks: 24,
  };
  fake.navigateToHarvestTargetImplementation = async () => {
    throw new Error("No path to the goal");
  };
  const controller = new MinecraftController(() => fake);
  const connected = controller.start(CONFIG);
  fake.emit("spawn");
  await connected;

  const result = await controller.executeGoal({
    goalId: "gather.nearby-log.v1",
  });

  assert.equal(result.status, "failed");
  assert.equal(result.error.code, "E_MINECRAFT_GOAL_PATH");
  assert.equal(fake.harvestNavigationCalls.length, 1);
  assert.equal(fake.harvestCalls.length, 0);
  assert.equal(fake.forwardEnabled, false);
});

test("gather.nearby-log.v1 does not dig when physics becomes stale during pathfinding", async () => {
  const fake = new FakeBotPort();
  fake.harvestTarget = {
    name: "oak_log",
    position: { x: 25, y: 64, z: 2 },
    distanceBlocks: 24,
  };
  const defaultNavigation = fake.navigateToHarvestTargetImplementation;
  fake.navigateToHarvestTargetImplementation = async (target, signal) => {
    await defaultNavigation(target, signal);
    fake.worldFreshness = {
      ...fake.worldFreshness,
      ageMs: 1_001,
      state: "stale",
    };
  };
  const controller = new MinecraftController(() => fake);
  const connected = controller.start(CONFIG);
  fake.emit("spawn");
  await connected;

  const result = await controller.executeGoal({
    goalId: "gather.nearby-log.v1",
  });

  assert.equal(result.status, "failed");
  assert.equal(result.error.code, "E_MINECRAFT_GOAL_STALE_STATE");
  assert.equal(fake.harvestNavigationCalls.length, 1);
  assert.equal(fake.harvestCalls.length, 0);
  assert.equal(fake.forwardEnabled, false);
});

test("gather.nearby-log.v1 never digs when the exact target is no longer diggable", async () => {
  const fake = new FakeBotPort();
  fake.harvestDiggable = false;
  const controller = new MinecraftController(() => fake);
  const connected = controller.start(CONFIG);
  fake.emit("spawn");
  await connected;

  const result = await controller.executeGoal({
    goalId: "gather.nearby-log.v1",
  });

  assert.equal(result.status, "failed");
  assert.equal(result.error.code, "E_MINECRAFT_GOAL_PRECONDITION");
  assert.equal(fake.harvestCalls.length, 0);
});

test("gather.nearby-log.v1 equips one owned axe before the one dig", async () => {
  const fake = new FakeBotPort();
  fake.harvestAxeAvailable = true;
  const controller = new MinecraftController(() => fake);
  const connected = controller.start(CONFIG);
  fake.emit("spawn");
  await connected;

  const result = await controller.executeGoal({
    goalId: "gather.nearby-log.v1",
  });

  assert.equal(result.status, "succeeded");
  assert.deepEqual(fake.harvestToolCalls, ["axe"]);
  assert.deepEqual(
    fake.operationLog,
    ["navigate", "equip:axe", "dig", "collect"],
  );
  assert.equal(fake.harvestCalls.length, 1);
});

test("gather.nearby-log.v1 explicitly uses hand when no allowlisted axe is owned", async () => {
  const fake = new FakeBotPort();
  const controller = new MinecraftController(() => fake);
  const connected = controller.start(CONFIG);
  fake.emit("spawn");
  await connected;

  const result = await controller.executeGoal({
    goalId: "gather.nearby-log.v1",
  });

  assert.equal(result.status, "succeeded");
  assert.deepEqual(fake.harvestToolCalls, ["hand"]);
  assert.deepEqual(
    fake.operationLog,
    ["navigate", "equip:hand", "dig", "collect"],
  );
});

test("gather.nearby-log.v1 fails before dig when deterministic tool selection fails", async () => {
  const fake = new FakeBotPort();
  fake.harvestAxeAvailable = true;
  fake.equipBestHarvestToolImplementation = async () => {
    throw new Error("inventory changed");
  };
  const controller = new MinecraftController(() => fake);
  const connected = controller.start(CONFIG);
  fake.emit("spawn");
  await connected;

  const result = await controller.executeGoal({
    goalId: "gather.nearby-log.v1",
  });

  assert.equal(result.status, "failed");
  assert.equal(result.error.code, "E_MINECRAFT_GOAL_ACTION");
  assert.deepEqual(fake.harvestToolCalls, ["axe"]);
  assert.equal(fake.harvestCalls.length, 0);
});

test("gather.nearby-log.v1 rejects an oversized entity baseline before digging", async () => {
  const fake = new FakeBotPort();
  fake.harvestPreexistingEntityIds = Array.from(
    { length: 513 },
    (_value, index) => index,
  );
  const controller = new MinecraftController(() => fake);
  const connected = controller.start(CONFIG);
  fake.emit("spawn");
  await connected;

  const result = await controller.executeGoal({
    goalId: "gather.nearby-log.v1",
  });

  assert.equal(result.status, "failed");
  assert.equal(result.error.code, "E_MINECRAFT_GOAL_PRECONDITION");
  assert.equal(fake.harvestCalls.length, 0);
  assert.equal(fake.harvestCollectionCalls.length, 0);
});

test("emergency stop during tool selection prevents a later dig", async () => {
  const fake = new FakeBotPort();
  let releaseToolSelection = null;
  fake.equipBestHarvestToolImplementation = () => new Promise((resolve) => {
    releaseToolSelection = resolve;
  });
  const controller = new MinecraftController(() => fake);
  const connected = controller.start(CONFIG);
  fake.emit("spawn");
  await connected;

  const active = controller.executeGoal({ goalId: "gather.nearby-log.v1" });
  await Promise.resolve();
  await controller.emergencyStop();
  const result = await active;
  releaseToolSelection?.();
  await Promise.resolve();

  assert.equal(result.status, "failed");
  assert.equal(result.error.code, "E_MINECRAFT_SKILL_CANCELLED");
  assert.equal(fake.harvestCalls.length, 0);
});

test("gather.nearby-log.v1 rejects targets outside horizontal or vertical bounds", async () => {
  for (const target of [
    {
      name: "oak_log",
      position: { x: 34, y: 64, z: 2 },
      distanceBlocks: 33,
    },
    {
      name: "oak_log",
      position: { x: 2, y: 73, z: 2 },
      distanceBlocks: 1,
    },
  ]) {
    const fake = new FakeBotPort();
    fake.harvestTarget = target;
    const controller = new MinecraftController(() => fake);
    const connected = controller.start(CONFIG);
    fake.emit("spawn");
    await connected;

    const result = await controller.executeGoal({
      goalId: "gather.nearby-log.v1",
    });

    assert.equal(result.status, "failed");
    assert.equal(result.error.code, "E_MINECRAFT_GOAL_PRECONDITION");
    assert.equal(fake.harvestCalls.length, 0);
  }
});

test("emergency stop aborts in-flight harvest pathfinding before any dig", async () => {
  const fake = new FakeBotPort();
  fake.harvestTarget = {
    name: "oak_log",
    position: { x: 7, y: 64, z: 2 },
    distanceBlocks: 6,
  };
  fake.navigateToHarvestTargetImplementation = (_target, signal) => new Promise((_resolve, reject) => {
    signal.addEventListener("abort", () => reject(signal.reason), { once: true });
  });
  const controller = new MinecraftController(() => fake);
  const connected = controller.start(CONFIG);
  fake.emit("spawn");
  await connected;

  const active = controller.executeGoal({ goalId: "gather.nearby-log.v1" });
  await Promise.resolve();
  await controller.emergencyStop();
  const result = await active;

  assert.equal(result.status, "failed");
  assert.equal(result.error.code, "E_MINECRAFT_SKILL_CANCELLED");
  assert.equal(fake.harvestCalls.length, 0);
  assert.ok(fake.clearCalls >= 2);
  assert.ok(fake.stopDiggingCalls >= 2);
});

test("gather.nearby-log.v1 rejects retired harvest goal identifiers", async () => {
  const controller = new MinecraftController(() => new FakeBotPort());

  for (const goalId of [
    "harvest.nearby-log.v1",
    "harvest.nearby-log.v2",
    "harvest.nearby-log.v3",
  ]) {
    await assert.rejects(
      controller.executeGoal({ goalId }),
      (error) =>
        error instanceof MinecraftAdapterError
        && error.code === "E_MINECRAFT_GOAL_UNKNOWN",
    );
  }
});

test("gather.nearby-log.v1 fails before action when no allowlisted log is in range", async () => {
  const fake = new FakeBotPort();
  fake.harvestTarget = null;
  const controller = new MinecraftController(() => fake);
  const connected = controller.start(CONFIG);
  fake.emit("spawn");
  await connected;

  const result = await controller.executeGoal({
    goalId: "gather.nearby-log.v1",
  });

  assert.equal(result.status, "failed");
  assert.equal(result.precondition.passed, false);
  assert.equal(result.error.code, "E_MINECRAFT_GOAL_PRECONDITION");
  assert.equal(result.target, null);
  assert.equal(fake.harvestCalls.length, 0);
});

test("gather.nearby-log.v1 rejects an invalid adapter target before digging", async () => {
  const fake = new FakeBotPort();
  fake.harvestTarget = {
    name: "bedrock",
    position: { x: 2, y: 64, z: 2 },
    distanceBlocks: 1,
  };
  const controller = new MinecraftController(() => fake);
  const connected = controller.start(CONFIG);
  fake.emit("spawn");
  await connected;

  const result = await controller.executeGoal({
    goalId: "gather.nearby-log.v1",
  });

  assert.equal(result.status, "failed");
  assert.equal(result.error.code, "E_MINECRAFT_GOAL_PRECONDITION");
  assert.equal(fake.harvestCalls.length, 0);
});

test("gather.nearby-log.v1 reports a failed postcondition after one bounded attempt", async () => {
  const fake = new FakeBotPort();
  fake.digHarvestableLogImplementation = async () => {};
  const controller = new MinecraftController(() => fake);
  const connected = controller.start(CONFIG);
  fake.emit("spawn");
  await connected;

  const result = await controller.executeGoal({
    goalId: "gather.nearby-log.v1",
  });

  assert.equal(result.status, "failed");
  assert.equal(result.attempts, 1);
  assert.equal(result.postcondition.passed, false);
  assert.equal(result.postcondition.targetStillPresent, true);
  assert.equal(result.error.code, "E_MINECRAFT_GOAL_POSTCONDITION");
  assert.equal(fake.harvestCalls.length, 1);
  assert.equal(fake.clearCalls, 1);
});

test("gather.nearby-log.v1 fails closed when the matching drop is not collected", async () => {
  const fake = new FakeBotPort();
  fake.collectNewHarvestDropImplementation = async () => {
    throw new Error("No new matching harvested log drop appeared near the target");
  };
  const controller = new MinecraftController(() => fake);
  const connected = controller.start(CONFIG);
  fake.emit("spawn");
  await connected;

  const result = await controller.executeGoal({
    goalId: "gather.nearby-log.v1",
  });

  assert.equal(result.status, "failed");
  assert.equal(result.error.code, "E_MINECRAFT_GOAL_COLLECTION");
  assert.equal(fake.harvestCalls.length, 1);
  assert.equal(fake.harvestCollectionCalls.length, 1);
  assert.equal(fake.harvestInventoryCount, 0);
});

test("gather.nearby-log.v1 rejects a false collection success without inventory delta", async () => {
  const fake = new FakeBotPort();
  fake.collectNewHarvestDropImplementation = async () => {};
  const controller = new MinecraftController(() => fake);
  const connected = controller.start(CONFIG);
  fake.emit("spawn");
  await connected;

  const result = await controller.executeGoal({
    goalId: "gather.nearby-log.v1",
  });

  assert.equal(result.status, "failed");
  assert.equal(result.error.code, "E_MINECRAFT_GOAL_POSTCONDITION");
  assert.equal(result.postcondition.targetStillPresent, false);
  assert.equal(result.postcondition.inventoryCountBefore, 0);
  assert.equal(result.postcondition.inventoryCountAfter, 0);
});

test("emergency stop cancels gather while the matching drop is being collected", async () => {
  const fake = new FakeBotPort();
  fake.collectNewHarvestDropImplementation = (_target, _baseline, signal) =>
    new Promise((_resolve, reject) => {
      signal.addEventListener(
        "abort",
        () => reject(signal.reason),
        { once: true },
      );
    });
  const controller = new MinecraftController(() => fake);
  const connected = controller.start(CONFIG);
  fake.emit("spawn");
  await connected;

  const active = controller.executeGoal({
    goalId: "gather.nearby-log.v1",
  });
  for (
    let turn = 0;
    turn < 8 && fake.harvestCollectionCalls.length === 0;
    turn += 1
  ) {
    await Promise.resolve();
  }
  assert.equal(fake.harvestCollectionCalls.length, 1);
  await controller.emergencyStop();
  const result = await active;

  assert.equal(result.status, "failed");
  assert.equal(result.error.code, "E_MINECRAFT_SKILL_CANCELLED");
  assert.ok(fake.clearCalls >= 2);
});

test("emergency stop cancels an active harvest goal and clears controller state", async () => {
  const fake = new FakeBotPort();
  fake.digHarvestableLogImplementation = () => new Promise(() => {});
  const controller = new MinecraftController(() => fake);
  const connected = controller.start(CONFIG);
  fake.emit("spawn");
  await connected;

  const active = controller.executeGoal({
    goalId: "gather.nearby-log.v1",
  });
  for (let turn = 0; turn < 4 && fake.harvestCalls.length === 0; turn += 1) {
    await Promise.resolve();
  }
  assert.equal(fake.harvestCalls.length, 1);
  await controller.emergencyStop();
  const result = await active;

  assert.equal(result.status, "failed");
  assert.equal(result.error.code, "E_MINECRAFT_SKILL_CANCELLED");
  assert.equal(fake.harvestCalls.length, 1);
  assert.ok(fake.stopDiggingCalls >= 2);
  assert.ok(fake.clearCalls >= 2);
});

test("owner disconnect cancels active look without latching emergency stop", async () => {
  const fake = new FakeBotPort();
  fake.lookImplementation = () => new Promise(() => {});
  const controller = new MinecraftController(() => fake);
  const connected = controller.start(CONFIG);
  fake.emit("spawn");
  await connected;

  const active = controller.executeSkill({
    skillId: "look.v1",
    arguments: { yawRadians: 0.5, pitchRadians: 0.2 },
  });
  await Promise.resolve();
  await controller.disconnect();
  const result = await active;

  assert.equal(result.status, "failed");
  assert.equal(result.error.code, "E_MINECRAFT_SKILL_CANCELLED");
  assert.equal(controller.getStatus().emergencyStopped, false);
});

test("snapshot failure stays bounded and does not expose a vendor object", async () => {
  const fake = new FakeBotPort();
  fake.captureWorldState = () => {
    throw new Error("snapshot exploded");
  };
  const controller = new MinecraftController(() => fake);
  const connected = controller.start(CONFIG);
  fake.emit("spawn");
  await connected;

  const status = controller.getStatus();
  assert.equal(status.world, null);
  assert.deepEqual(status.lastError, {
    code: "E_MINECRAFT_SNAPSHOT",
    message: "snapshot exploded",
  });
});

test("look.v1 rejects unavailable or stale physics state before acting", async () => {
  for (const worldFreshness of [
    {
      physicsTickSequence: 0,
      ageMs: null,
      maximumAgeMs: 1_000,
      state: "unavailable",
    },
    {
      physicsTickSequence: 4,
      ageMs: 1_001,
      maximumAgeMs: 1_000,
      state: "stale",
    },
  ]) {
    const fake = new FakeBotPort();
    fake.worldFreshness = worldFreshness;
    const controller = new MinecraftController(() => fake);
    const connected = controller.start(CONFIG);
    fake.emit("spawn");
    await connected;

    const result = await controller.executeSkill({
      skillId: "look.v1",
      arguments: { yawRadians: 0.5, pitchRadians: 0.2 },
    });

    assert.equal(result.status, "failed");
    assert.equal(result.precondition.passed, false);
    assert.equal(result.error.code, "E_MINECRAFT_SKILL_STALE_STATE");
    assert.equal(fake.lookCalls.length, 0);
  }
});

test("look.v1 succeeds only after the normalized rotation verifies", async () => {
  const fake = new FakeBotPort();
  const controller = new MinecraftController(() => fake);
  const connected = controller.start(CONFIG);
  fake.emit("spawn");
  await connected;

  const result = await controller.executeSkill({
    skillId: "look.v1",
    arguments: {
      yawRadians: 1.2,
      pitchRadians: -0.25,
    },
  });

  assert.equal(result.status, "succeeded");
  assert.equal(result.attempts, 1);
  assert.equal(result.precondition.passed, true);
  assert.equal(result.postcondition.passed, true);
  assert.deepEqual(fake.lookCalls, [
    { yawRadians: 1.2, pitchRadians: -0.25 },
  ]);
});

test("look.v1 fails when Mineflayer resolves without satisfying state", async () => {
  const fake = new FakeBotPort();
  fake.lookImplementation = async () => {};
  const controller = new MinecraftController(() => fake);
  const connected = controller.start(CONFIG);
  fake.emit("spawn");
  await connected;

  const result = await controller.executeSkill({
    skillId: "look.v1",
    arguments: {
      yawRadians: 2,
      pitchRadians: 0.4,
    },
  });

  assert.equal(result.status, "failed");
  assert.equal(result.postcondition.passed, false);
  assert.equal(result.error.code, "E_MINECRAFT_SKILL_POSTCONDITION");
  assert.equal(fake.lookCalls.length, 1);
});

test("look.v1 reports vendor failure without retry", async () => {
  const fake = new FakeBotPort();
  fake.lookImplementation = async () => {
    throw new Error("look packet failed");
  };
  const controller = new MinecraftController(() => fake);
  const connected = controller.start(CONFIG);
  fake.emit("spawn");
  await connected;

  const result = await controller.executeSkill({
    skillId: "look.v1",
    arguments: {
      yawRadians: 0.1,
      pitchRadians: 0.1,
    },
  });

  assert.equal(result.status, "failed");
  assert.equal(result.error.code, "E_MINECRAFT_SKILL_ACTION");
  assert.equal(fake.lookCalls.length, 1);
});

test("look.v1 enforces its fixed timeout without retry", async (context) => {
  context.mock.timers.enable({ apis: ["setTimeout"] });
  const fake = new FakeBotPort();
  fake.lookImplementation = () => new Promise(() => {});
  const controller = new MinecraftController(() => fake);
  const connected = controller.start(CONFIG);
  fake.emit("spawn");
  await connected;

  const active = controller.executeSkill({
    skillId: "look.v1",
    arguments: {
      yawRadians: 0.1,
      pitchRadians: 0.1,
    },
  });
  await Promise.resolve();
  context.mock.timers.tick(2_001);
  const result = await active;

  assert.equal(result.status, "failed");
  assert.equal(result.error.code, "E_MINECRAFT_SKILL_TIMEOUT");
  assert.equal(fake.lookCalls.length, 1);
});

test("look.v1 enforces online and single-active-skill preconditions", async () => {
  const offline = new MinecraftController(() => new FakeBotPort());
  const offlineResult = await offline.executeSkill({
    skillId: "look.v1",
    arguments: { yawRadians: 0, pitchRadians: 0 },
  });
  assert.equal(offlineResult.error.code, "E_MINECRAFT_SKILL_PRECONDITION");

  const fake = new FakeBotPort();
  let releaseLook;
  fake.lookImplementation = () =>
    new Promise((resolve) => {
      releaseLook = resolve;
    });
  const controller = new MinecraftController(() => fake);
  const connected = controller.start(CONFIG);
  fake.emit("spawn");
  await connected;

  const active = controller.executeSkill({
    skillId: "look.v1",
    arguments: { yawRadians: 0.5, pitchRadians: 0 },
  });
  await Promise.resolve();
  const busy = await controller.executeSkill({
    skillId: "look.v1",
    arguments: { yawRadians: 0.6, pitchRadians: 0 },
  });
  assert.equal(busy.error.code, "E_MINECRAFT_SKILL_BUSY");
  releaseLook();
  await active;
});

test("emergency stop cancels an active look skill and never retries", async () => {
  const fake = new FakeBotPort();
  fake.lookImplementation = () => new Promise(() => {});
  const controller = new MinecraftController(() => fake);
  const connected = controller.start(CONFIG);
  fake.emit("spawn");
  await connected;

  const active = controller.executeSkill({
    skillId: "look.v1",
    arguments: { yawRadians: 0.5, pitchRadians: 0.2 },
  });
  await Promise.resolve();
  await controller.emergencyStop();
  const result = await active;

  assert.equal(result.status, "failed");
  assert.equal(result.error.code, "E_MINECRAFT_SKILL_CANCELLED");
  assert.equal(fake.lookCalls.length, 1);
  assert.equal(fake.quitCalls, 1);
});

test("move.step.v1 moves one cardinal step and verifies normalized displacement", async () => {
  const fake = new FakeBotPort();
  const controller = new MinecraftController(() => fake);
  const connected = controller.start(CONFIG);
  fake.emit("spawn");
  await connected;

  const result = await controller.executeSkill({
    skillId: "move.step.v1",
    arguments: { direction: "east", distanceBlocks: 1 },
  });

  assert.equal(result.status, "succeeded");
  assert.equal(result.postcondition.passed, true);
  assert.ok(result.postcondition.observed.forwardProgressBlocks >= 1);
  assert.ok(result.postcondition.observed.lateralDriftBlocks <= 0.001);
  assert.ok(result.postcondition.progress.physicsTicksObserved >= 10);
  assert.equal(result.postcondition.progress.stagnantTicksObserved, 0);
  assert.ok(result.postcondition.progress.maximumForwardProgressBlocks >= 1);
  assert.deepEqual(fake.lookCalls[0], {
    yawRadians: -Math.PI / 2,
    pitchRadians: 0,
  });
  assert.deepEqual(fake.controlCalls, [
    { control: "forward", enabled: true },
  ]);
  assert.equal(fake.forwardEnabled, false);
  assert.equal(fake.clearCalls, 1);
});

test("move.step.v1 fails blocked movement after 20 ticks without retry", async () => {
  const fake = new FakeBotPort();
  fake.physicsTickImplementation = async () => {};
  const controller = new MinecraftController(() => fake);
  const connected = controller.start(CONFIG);
  fake.emit("spawn");
  await connected;

  const result = await controller.executeSkill({
    skillId: "move.step.v1",
    arguments: { direction: "north", distanceBlocks: 1 },
  });

  assert.equal(result.status, "failed");
  assert.equal(result.error.code, "E_MINECRAFT_SKILL_BLOCKED");
  assert.equal(result.attempts, 1);
  assert.equal(result.postcondition.progress.physicsTicksObserved, 20);
  assert.equal(result.postcondition.progress.stagnantTicksObserved, 20);
  assert.equal(result.postcondition.progress.maximumForwardProgressBlocks, 0);
  assert.equal(result.postcondition.observed.forwardProgressBlocks, 0);
  assert.equal(fake.clearCalls, 1);
});

test("move.step.v1 rejects stale physics state before enabling forward", async () => {
  const fake = new FakeBotPort();
  fake.worldFreshness = {
    physicsTickSequence: 12,
    ageMs: 1_250,
    maximumAgeMs: 1_000,
    state: "stale",
  };
  const controller = new MinecraftController(() => fake);
  const connected = controller.start(CONFIG);
  fake.emit("spawn");
  await connected;

  const result = await controller.executeSkill({
    skillId: "move.step.v1",
    arguments: { direction: "north", distanceBlocks: 1 },
  });

  assert.equal(result.status, "failed");
  assert.equal(result.precondition.passed, false);
  assert.equal(result.error.code, "E_MINECRAFT_SKILL_STALE_STATE");
  assert.equal(result.postcondition.progress.physicsTicksObserved, 0);
  assert.equal(fake.controlCalls.length, 0);
  assert.equal(fake.lookCalls.length, 0);
});

test("move.step.v1 rejects lateral drift in its postcondition", async () => {
  const fake = new FakeBotPort();
  fake.physicsTickImplementation = async () => {
    fake.world = structuredClone(fake.world);
    fake.world.player.position.z -= 0.2;
    fake.world.player.position.x += 0.1;
  };
  const controller = new MinecraftController(() => fake);
  const connected = controller.start(CONFIG);
  fake.emit("spawn");
  await connected;

  const result = await controller.executeSkill({
    skillId: "move.step.v1",
    arguments: { direction: "north", distanceBlocks: 1 },
  });

  assert.equal(result.status, "failed");
  assert.equal(result.error.code, "E_MINECRAFT_SKILL_POSTCONDITION");
  assert.ok(result.postcondition.observed.lateralDriftBlocks > 0.35);
  assert.ok(result.postcondition.progress.physicsTicksObserved > 0);
  assert.ok(result.postcondition.progress.maximumForwardProgressBlocks >= 1);
  assert.equal(fake.clearCalls, 1);
});

test("move.step.v1 requires an on-ground player", async () => {
  const fake = new FakeBotPort();
  fake.world = structuredClone(fake.world);
  fake.world.player.onGround = false;
  const controller = new MinecraftController(() => fake);
  const connected = controller.start(CONFIG);
  fake.emit("spawn");
  await connected;

  const result = await controller.executeSkill({
    skillId: "move.step.v1",
    arguments: { direction: "south", distanceBlocks: 0.5 },
  });

  assert.equal(result.status, "failed");
  assert.equal(result.error.code, "E_MINECRAFT_SKILL_PRECONDITION");
  assert.equal(fake.controlCalls.length, 0);
});

test("emergency stop cancels move.step.v1 and clears movement controls", async () => {
  const fake = new FakeBotPort();
  fake.physicsTickImplementation = () => new Promise(() => {});
  const controller = new MinecraftController(() => fake);
  const connected = controller.start(CONFIG);
  fake.emit("spawn");
  await connected;

  const active = controller.executeSkill({
    skillId: "move.step.v1",
    arguments: { direction: "west", distanceBlocks: 1 },
  });
  await Promise.resolve();
  await Promise.resolve();
  await controller.emergencyStop();
  const result = await active;

  assert.equal(result.status, "failed");
  assert.equal(result.error.code, "E_MINECRAFT_SKILL_CANCELLED");
  assert.deepEqual(result.postcondition.progress, {
    physicsTicksObserved: 0,
    stagnantTicksObserved: 0,
    maximumForwardProgressBlocks: 0,
  });
  assert.equal(fake.forwardEnabled, false);
  assert.ok(fake.clearCalls >= 1);
});

test("owner disconnect cancels move.step.v1 without latching emergency", async () => {
  const fake = new FakeBotPort();
  fake.physicsTickImplementation = () => new Promise(() => {});
  const controller = new MinecraftController(() => fake);
  const connected = controller.start(CONFIG);
  fake.emit("spawn");
  await connected;

  const active = controller.executeSkill({
    skillId: "move.step.v1",
    arguments: { direction: "west", distanceBlocks: 1 },
  });
  await Promise.resolve();
  await Promise.resolve();
  await controller.disconnect();
  const result = await active;

  assert.equal(result.status, "failed");
  assert.equal(result.error.code, "E_MINECRAFT_SKILL_CANCELLED");
  assert.equal(result.postcondition.progress.physicsTicksObserved, 0);
  assert.equal(controller.getStatus().emergencyStopped, false);
  assert.equal(controller.getStatus().phase, "disconnected");
  assert.equal(fake.forwardEnabled, false);
});

test("move.step.v1 enforces its fixed timeout and clears controls", async (context) => {
  context.mock.timers.enable({ apis: ["setTimeout"] });
  const fake = new FakeBotPort();
  fake.physicsTickImplementation = () => new Promise(() => {});
  const controller = new MinecraftController(() => fake);
  const connected = controller.start(CONFIG);
  fake.emit("spawn");
  await connected;

  const active = controller.executeSkill({
    skillId: "move.step.v1",
    arguments: { direction: "south", distanceBlocks: 2 },
  });
  await Promise.resolve();
  await Promise.resolve();
  context.mock.timers.tick(4_001);
  const result = await active;

  assert.equal(result.status, "failed");
  assert.equal(result.error.code, "E_MINECRAFT_SKILL_TIMEOUT");
  assert.equal(result.attempts, 1);
  assert.deepEqual(result.postcondition.progress, {
    physicsTicksObserved: 0,
    stagnantTicksObserved: 0,
    maximumForwardProgressBlocks: 0,
  });
  assert.equal(fake.forwardEnabled, false);
  assert.equal(fake.clearCalls, 1);
});

test("move.to.v1 turns toward a nearby diagonal coordinate and verifies it", async () => {
  const fake = new FakeBotPort();
  const controller = new MinecraftController(() => fake);
  const connected = controller.start(CONFIG);
  fake.emit("spawn");
  await connected;

  const result = await controller.executeSkill({
    skillId: "move.to.v1",
    arguments: { targetX: 1.75, targetZ: 1.25 },
  });

  assert.equal(result.status, "succeeded");
  assert.equal(result.skillId, "move.to.v1");
  assert.deepEqual(result.postcondition.expected, {
    targetX: 1.75,
    targetZ: 1.25,
  });
  assert.ok(result.postcondition.targetDistanceBlocks > 1);
  assert.ok(result.postcondition.observed.remainingDistanceBlocks <= 0.11);
  assert.ok(result.postcondition.observed.lateralDriftBlocks <= 0.001);
  assert.ok(result.postcondition.progress.physicsTicksObserved > 0);
  assert.equal(fake.lookCalls.length, 1);
  assert.equal(fake.clearCalls, 1);
});

test("move.to.v1 rejects targets that are too near or too far before acting", async () => {
  for (const target of [
    { targetX: 1.1, targetZ: 2 },
    { targetX: 4, targetZ: 2 },
  ]) {
    const fake = new FakeBotPort();
    const controller = new MinecraftController(() => fake);
    const connected = controller.start(CONFIG);
    fake.emit("spawn");
    await connected;

    const result = await controller.executeSkill({
      skillId: "move.to.v1",
      arguments: target,
    });

    assert.equal(result.status, "failed");
    assert.equal(result.precondition.passed, false);
    assert.equal(result.error.code, "E_MINECRAFT_SKILL_PRECONDITION");
    assert.equal(result.postcondition.targetDistanceBlocks, null);
    assert.equal(fake.lookCalls.length, 0);
    assert.equal(fake.controlCalls.length, 0);
  }
});

test("move.to.v1 rejects stale physics state before resolving the target", async () => {
  const fake = new FakeBotPort();
  fake.worldFreshness = {
    physicsTickSequence: 4,
    ageMs: 1_001,
    maximumAgeMs: 1_000,
    state: "stale",
  };
  const controller = new MinecraftController(() => fake);
  const connected = controller.start(CONFIG);
  fake.emit("spawn");
  await connected;

  const result = await controller.executeSkill({
    skillId: "move.to.v1",
    arguments: { targetX: 1, targetZ: 1 },
  });

  assert.equal(result.status, "failed");
  assert.equal(result.precondition.passed, false);
  assert.equal(result.error.code, "E_MINECRAFT_SKILL_STALE_STATE");
  assert.equal(fake.lookCalls.length, 0);
});

test("move.to.v1 reports blocked movement after 20 ticks without retry", async () => {
  const fake = new FakeBotPort();
  fake.physicsTickImplementation = async () => {};
  const controller = new MinecraftController(() => fake);
  const connected = controller.start(CONFIG);
  fake.emit("spawn");
  await connected;

  const result = await controller.executeSkill({
    skillId: "move.to.v1",
    arguments: { targetX: 1, targetZ: 1 },
  });

  assert.equal(result.status, "failed");
  assert.equal(result.error.code, "E_MINECRAFT_SKILL_BLOCKED");
  assert.equal(result.attempts, 1);
  assert.equal(result.postcondition.progress.physicsTicksObserved, 20);
  assert.equal(result.postcondition.progress.stagnantTicksObserved, 20);
  assert.equal(fake.clearCalls, 1);
});

test("move.to.v1 fails postcondition when movement drifts away from target axis", async () => {
  const fake = new FakeBotPort();
  fake.physicsTickImplementation = async () => {
    fake.world = structuredClone(fake.world);
    fake.world.player.position.x += 0.1;
    fake.world.player.position.z -= 0.1;
  };
  const controller = new MinecraftController(() => fake);
  const connected = controller.start(CONFIG);
  fake.emit("spawn");
  await connected;

  const result = await controller.executeSkill({
    skillId: "move.to.v1",
    arguments: { targetX: 1, targetZ: 1 },
  });

  assert.equal(result.status, "failed");
  assert.equal(result.error.code, "E_MINECRAFT_SKILL_POSTCONDITION");
  assert.ok(result.postcondition.observed.lateralDriftBlocks > 0.35);
  assert.equal(fake.clearCalls, 1);
});

test("owner disconnect cancels move.to.v1 and clears controls", async () => {
  const fake = new FakeBotPort();
  fake.physicsTickImplementation = () => new Promise(() => {});
  const controller = new MinecraftController(() => fake);
  const connected = controller.start(CONFIG);
  fake.emit("spawn");
  await connected;

  const active = controller.executeSkill({
    skillId: "move.to.v1",
    arguments: { targetX: 2, targetZ: 2 },
  });
  await Promise.resolve();
  await Promise.resolve();
  await controller.disconnect();
  const result = await active;

  assert.equal(result.status, "failed");
  assert.equal(result.error.code, "E_MINECRAFT_SKILL_CANCELLED");
  assert.equal(result.attempts, 1);
  assert.equal(fake.forwardEnabled, false);
  assert.equal(controller.getStatus().emergencyStopped, false);
});

test("move.to.v1 enforces the shared fixed timeout", async (context) => {
  context.mock.timers.enable({ apis: ["setTimeout"] });
  const fake = new FakeBotPort();
  fake.physicsTickImplementation = () => new Promise(() => {});
  const controller = new MinecraftController(() => fake);
  const connected = controller.start(CONFIG);
  fake.emit("spawn");
  await connected;

  const active = controller.executeSkill({
    skillId: "move.to.v1",
    arguments: { targetX: 2, targetZ: 2 },
  });
  await Promise.resolve();
  await Promise.resolve();
  context.mock.timers.tick(4_001);
  const result = await active;

  assert.equal(result.status, "failed");
  assert.equal(result.error.code, "E_MINECRAFT_SKILL_TIMEOUT");
  assert.equal(result.attempts, 1);
  assert.equal(fake.forwardEnabled, false);
  assert.equal(fake.clearCalls, 1);
});
