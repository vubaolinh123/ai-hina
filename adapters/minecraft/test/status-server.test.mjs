import assert from "node:assert/strict";
import test from "node:test";

import {
  MinecraftController,
  startMinecraftStatusServer,
} from "../dist/index.js";

async function request(server, path, method = "GET") {
  const response = await fetch(
    `http://${server.host}:${server.port}${path}`,
    { method },
  );
  return {
    status: response.status,
    allow: response.headers.get("allow"),
    cacheControl: response.headers.get("cache-control"),
    body: await response.json(),
  };
}

test("serves only bounded read-only status routes on loopback", async (context) => {
  const controller = new MinecraftController(() => {
    throw new Error("factory must not run for status-only test");
  });
  const server = await startMinecraftStatusServer(controller, 0);
  context.after(() => server.close());

  assert.equal(server.host, "127.0.0.1");
  assert.ok(server.port > 0);

  const health = await request(server, "/health");
  assert.equal(health.status, 200);
  assert.equal(health.cacheControl, "no-store");
  assert.deepEqual(health.body, {
    status: "ok",
    phase: "disconnected",
    emergencyStopped: false,
  });

  const status = await request(server, "/v1/minecraft/status");
  assert.equal(status.status, 200);
  assert.equal(status.body.schemaVersion, 1);
  assert.equal(status.body.world, null);

  const mutation = await request(
    server,
    "/v1/minecraft/status",
    "POST",
  );
  assert.equal(mutation.status, 405);
  assert.equal(mutation.allow, "GET");
  assert.equal(mutation.body.error.code, "E_MINECRAFT_STATUS_METHOD");

  const missing = await request(server, "/debug");
  assert.equal(missing.status, 404);
  assert.equal(missing.body.error.code, "E_MINECRAFT_STATUS_NOT_FOUND");
});
