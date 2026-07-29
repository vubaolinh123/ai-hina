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
