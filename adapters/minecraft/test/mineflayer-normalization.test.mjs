import assert from "node:assert/strict";
import test from "node:test";

import { MINECRAFT_SNAPSHOT_LIMITS } from "../dist/index.js";
import { normalizeMineflayerWorldState } from "../dist/mineflayer-client.js";

function point(x, y, z) {
  return {
    x,
    y,
    z,
    distanceTo(other) {
      return Math.hypot(x - other.x, y - other.y, z - other.z);
    },
  };
}

test("normalizes and bounds Mineflayer state without chat or plugin payloads", () => {
  const player = {
    id: 1,
    type: "player",
    name: "player",
    username: "Hina",
    position: point(0, 64, 0),
    velocity: point(0, 0, 0),
    yaw: 1.23456,
    pitch: 0.2,
    onGround: true,
  };
  const entities = { player };
  for (let index = 0; index < 40; index += 1) {
    entities[`e${index}`] = {
      id: index + 2,
      type: "mob",
      name: index === 0 ? "zombie\u0000hidden" : "zombie",
      username: undefined,
      position: point(index + 1, 64, 0),
      health: 20,
      metadata: { shouldNotLeak: true },
    };
  }
  const slots = Array.from({ length: 50 }, (_, index) => ({
    name: "cobblestone",
    displayName: `Cobblestone ${index}`,
    count: 64,
    metadata: 0,
    nbt: { shouldNotLeak: true },
  }));
  const rawBot = {
    entity: player,
    entities,
    inventory: { slots },
    game: { dimension: "overworld", gameMode: "survival" },
    time: { timeOfDay: 1234, isDay: true },
    version: "1.21.8",
    username: "Hina",
    health: 20,
    food: 19,
    foodSaturation: 5,
    oxygenLevel: 20,
    chat: { shouldNotLeak: true },
    scoreboard: { shouldNotLeak: true },
  };

  const state = normalizeMineflayerWorldState(rawBot);
  const serialized = JSON.stringify(state);
  assert.equal(
    state.inventory.length,
    MINECRAFT_SNAPSHOT_LIMITS.inventoryEntries,
  );
  assert.equal(
    state.nearbyEntities.length,
    MINECRAFT_SNAPSHOT_LIMITS.nearbyEntities,
  );
  assert.equal(state.nearbyEntities[0].name, "zombiehidden");
  assert.equal(state.player.yaw, 1.235);
  assert.equal(serialized.includes("shouldNotLeak"), false);
  assert.equal(serialized.includes("scoreboard"), false);
  assert.equal(serialized.includes("chat"), false);
  assert.equal(serialized.includes("nbt"), false);
});
