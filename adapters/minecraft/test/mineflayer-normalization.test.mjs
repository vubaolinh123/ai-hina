import assert from "node:assert/strict";
import test from "node:test";

import {
  MINECRAFT_SNAPSHOT_LIMITS,
  MINECRAFT_WORLD_FRESHNESS_MAX_AGE_MS,
} from "../dist/index.js";
import {
  evaluateWorldStateFreshness,
  normalizeMineflayerWorldState,
  PhysicsFreshnessTracker,
  selectBestHarvestTool,
} from "../dist/mineflayer-client.js";

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

test("physics freshness is unavailable, fresh and stale at fixed boundaries", () => {
  assert.deepEqual(evaluateWorldStateFreshness(0, null, 5_000), {
    physicsTickSequence: 0,
    ageMs: null,
    maximumAgeMs: MINECRAFT_WORLD_FRESHNESS_MAX_AGE_MS,
    state: "unavailable",
  });
  assert.deepEqual(evaluateWorldStateFreshness(7, 4_000, 5_000), {
    physicsTickSequence: 7,
    ageMs: 1_000,
    maximumAgeMs: MINECRAFT_WORLD_FRESHNESS_MAX_AGE_MS,
    state: "fresh",
  });
  assert.deepEqual(evaluateWorldStateFreshness(8, 4_000, 5_000.001), {
    physicsTickSequence: 8,
    ageMs: 1_000.001,
    maximumAgeMs: MINECRAFT_WORLD_FRESHNESS_MAX_AGE_MS,
    state: "stale",
  });
});

test("physics freshness tracker advances only on recorded ticks", () => {
  const tracker = new PhysicsFreshnessTracker();
  assert.equal(tracker.read(5_000).state, "unavailable");

  tracker.recordTick(5_000);
  assert.deepEqual(tracker.read(5_250), {
    physicsTickSequence: 1,
    ageMs: 250,
    maximumAgeMs: MINECRAFT_WORLD_FRESHNESS_MAX_AGE_MS,
    state: "fresh",
  });

  tracker.recordTick(5_500);
  assert.deepEqual(tracker.read(6_501), {
    physicsTickSequence: 2,
    ageMs: 1_001,
    maximumAgeMs: MINECRAFT_WORLD_FRESHNESS_MAX_AGE_MS,
    state: "stale",
  });
});

test("harvest tool selection chooses the fixed highest-priority owned axe only", () => {
  const wooden = { name: "wooden_axe", marker: "wood" };
  const iron = { name: "iron_axe", marker: "iron" };
  const netherite = { name: "netherite_axe", marker: "netherite" };

  assert.equal(
    selectBestHarvestTool([
      null,
      { name: "diamond_pickaxe" },
      wooden,
      iron,
      { name: "stick" },
      netherite,
    ]),
    netherite,
  );
  assert.equal(
    selectBestHarvestTool([{ name: "diamond_pickaxe" }, { name: "stick" }]),
    null,
  );
});
