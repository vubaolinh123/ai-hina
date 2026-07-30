import assert from "node:assert/strict";
import test from "node:test";

import {
  MinecraftController,
  startMinecraftStatusServer,
} from "../dist/index.js";

const TOKEN = "abcdefghijklmnopqrstuvwxyz0123456789ABCDEFG";

function createControllerStub() {
  let phase = "disconnected";
  let emergencyStopped = false;
  const calls = [];
  const status = () => ({
    schemaVersion: 1,
    phase,
    emergencyStopped,
    sequence: calls.length,
    target: null,
    connectedAt: null,
    capturedAt: "2026-07-29T00:00:00.000Z",
    world: null,
    worldFreshness: null,
    lastError: null,
  });
  return {
    calls,
    getStatus: status,
    async start(config) {
      calls.push({ action: "connect", config });
      phase = "online";
      return status();
    },
    async disconnect() {
      calls.push({ action: "disconnect" });
      phase = "disconnected";
      return {
        alreadyDisconnected: false,
        localActionsStoppedAt: "2026-07-29T00:00:00.000Z",
        dispatchDurationMs: 1,
      };
    },
    async executeGoal(request) {
      calls.push({ action: "goal", request });
      return {
        schemaVersion: 1,
        executionId: 1,
        goalId: "harvest.nearby-log.v3",
        status: "succeeded",
        startedAt: "2026-07-29T00:00:00.000Z",
        finishedAt: "2026-07-29T00:00:00.001Z",
        durationMs: 1,
        attempts: 1,
        precondition: { passed: true },
        target: {
          name: "oak_log",
          position: { x: 1, y: 64, z: 1 },
          distanceBlocks: 1,
        },
        postcondition: {
          kind: "targeted_allowlisted_log_absent",
          passed: true,
          targetStillPresent: false,
        },
        error: null,
      };
    },
    async emergencyStop() {
      calls.push({ action: "emergency_stop" });
      phase = "stopped";
      emergencyStopped = true;
      return {
        alreadyStopped: false,
        localActionsStoppedAt: "2026-07-29T00:00:00.000Z",
        dispatchDurationMs: 1,
      };
    },
  };
}

async function request(
  server,
  path,
  {
    method = "GET",
    body,
    token,
    source = "owner.desktop",
  } = {},
) {
  const headers = {};
  if (body !== undefined) {
    headers["content-type"] = "application/json";
  }
  if (token !== undefined) {
    headers.authorization = `Bearer ${token}`;
  }
  if (source !== undefined) {
    headers["x-hina-source"] = source;
  }
  const response = await fetch(
    `http://${server.host}:${server.port}${path}`,
    {
      method,
      headers,
      body:
        typeof body === "string"
          ? body
          : body === undefined
            ? undefined
            : JSON.stringify(body),
    },
  );
  return {
    status: response.status,
    allow: response.headers.get("allow"),
    cacheControl: response.headers.get("cache-control"),
    body: await response.json(),
  };
}

test("serves bounded read-only status on loopback without control authority", async (context) => {
  const controller = new MinecraftController(() => {
    throw new Error("factory must not run for status-only test");
  });
  const server = await startMinecraftStatusServer(controller, 0);
  context.after(() => server.close());

  assert.equal(server.host, "127.0.0.1");
  assert.ok(server.port > 0);
  assert.equal(server.controlEnabled, false);

  const health = await request(server, "/health");
  assert.equal(health.status, 200);
  assert.equal(health.cacheControl, "no-store");
  assert.deepEqual(health.body, {
    status: "ok",
    phase: "disconnected",
    emergencyStopped: false,
    controlEnabled: false,
  });

  const status = await request(server, "/v1/minecraft/status");
  assert.equal(status.status, 200);
  assert.equal(status.body.schemaVersion, 1);
  assert.equal(status.body.world, null);

  const mutation = await request(server, "/v1/minecraft/goals/execute", {
    method: "POST",
    body: {
      goalId: "harvest.nearby-log.v3",
      ownerConfirmed: true,
      source: "owner.desktop",
    },
  });
  assert.equal(mutation.status, 401);
  assert.equal(mutation.body.errorCode, "E_MINECRAFT_CONTROL_AUTHORITY");

  const missing = await request(server, "/debug");
  assert.equal(missing.status, 404);
  assert.equal(missing.body.errorCode, "E_MINECRAFT_STATUS_NOT_FOUND");
});

test("authenticated service exposes only fixed owner operations and one static goal", async (context) => {
  const controller = createControllerStub();
  const server = await startMinecraftStatusServer(controller, {
    port: 0,
    controlToken: TOKEN,
  });
  context.after(() => server.close());

  const connect = await request(server, "/v1/minecraft/connect", {
    method: "POST",
    token: TOKEN,
    body: {
      host: "127.0.0.1",
      ownerConfirmed: true,
      port: 25565,
      source: "owner.desktop",
      username: "Hina",
      version: null,
    },
  });
  assert.equal(connect.status, 200);
  assert.equal(controller.calls[0].config.statusPort, server.port);

  const goal = await request(server, "/v1/minecraft/goals/execute", {
    method: "POST",
    token: TOKEN,
    body: {
      goalId: "harvest.nearby-log.v3",
      ownerConfirmed: true,
      source: "owner.desktop",
    },
  });
  assert.equal(goal.status, 200);
  assert.equal(goal.body.status, "succeeded");
  assert.deepEqual(controller.calls[1], {
    action: "goal",
    request: { goalId: "harvest.nearby-log.v3" },
  });

  const disconnect = await request(server, "/v1/minecraft/disconnect", {
    method: "POST",
    token: TOKEN,
    body: {
      action: "disconnect",
      ownerConfirmed: true,
      source: "owner.desktop",
    },
  });
  assert.equal(disconnect.status, 200);

  const emergency = await request(server, "/v1/minecraft/emergency-stop", {
    method: "POST",
    token: TOKEN,
    body: {
      action: "emergency_stop",
      ownerConfirmed: true,
      source: "owner.desktop",
    },
  });
  assert.equal(emergency.status, 200);
  assert.deepEqual(
    controller.calls.map((call) => call.action),
    ["connect", "goal", "disconnect", "emergency_stop"],
  );
});

test("goal mutations reject bad authority, schema and retired manual routes", async (context) => {
  const controller = createControllerStub();
  const server = await startMinecraftStatusServer(controller, {
    port: 0,
    controlToken: TOKEN,
  });
  context.after(() => server.close());

  const wrongToken = await request(server, "/v1/minecraft/goals/execute", {
    method: "POST",
    token: `${TOKEN}x`,
    body: {
      goalId: "harvest.nearby-log.v3",
      ownerConfirmed: true,
      source: "owner.desktop",
    },
  });
  assert.equal(wrongToken.status, 401);

  const extraField = await request(server, "/v1/minecraft/goals/execute", {
    method: "POST",
    token: TOKEN,
    body: {
      goalId: "harvest.nearby-log.v3",
      ownerConfirmed: true,
      source: "owner.desktop",
      injected: true,
    },
  });
  assert.equal(extraField.status, 400);
  assert.equal(extraField.body.errorCode, "E_MINECRAFT_CONTROL_SCHEMA");

  const unknownGoal = await request(server, "/v1/minecraft/goals/execute", {
    method: "POST",
    token: TOKEN,
    body: {
      goalId: "move.to.v1",
      ownerConfirmed: true,
      source: "owner.desktop",
    },
  });
  assert.equal(unknownGoal.status, 400);
  assert.equal(unknownGoal.body.errorCode, "E_MINECRAFT_CONTROL_SCHEMA");

  const retiredGoal = await request(server, "/v1/minecraft/goals/execute", {
    method: "POST",
    token: TOKEN,
    body: {
      goalId: "harvest.nearby-log.v1",
      ownerConfirmed: true,
      source: "owner.desktop",
    },
  });
  assert.equal(retiredGoal.status, 400);
  assert.equal(retiredGoal.body.errorCode, "E_MINECRAFT_CONTROL_SCHEMA");

  const retiredManualRoute = await request(server, "/v1/minecraft/skills/move-step", {
    method: "POST",
    token: TOKEN,
    body: {
      goalId: "harvest.nearby-log.v3",
      ownerConfirmed: true,
      source: "owner.desktop",
    },
  });
  assert.equal(retiredManualRoute.status, 404);
  assert.equal(retiredManualRoute.body.errorCode, "E_MINECRAFT_STATUS_NOT_FOUND");

  const oversized = await request(server, "/v1/minecraft/connect", {
    method: "POST",
    token: TOKEN,
    body: JSON.stringify({ padding: "x".repeat(8_300) }),
  });
  assert.equal(oversized.status, 413);
  assert.equal(oversized.body.errorCode, "E_MINECRAFT_CONTROL_BOUNDS");
  assert.equal(controller.calls.length, 0);
});
