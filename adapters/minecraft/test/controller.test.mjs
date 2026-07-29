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
  lookImplementation = async (yawRadians, pitchRadians) => {
    this.world = structuredClone(this.world);
    this.world.player.yaw = yawRadians;
    this.world.player.pitch = pitchRadians;
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

  async look(yawRadians, pitchRadians) {
    this.lookCalls.push({ yawRadians, pitchRadians });
    await this.lookImplementation(yawRadians, pitchRadians);
  }

  clearControlStates() {
    this.clearCalls += 1;
  }

  async stopDigging() {
    this.stopDiggingCalls += 1;
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
  assert.equal(controller.getStatus().phase, "error");
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
