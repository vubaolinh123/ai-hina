import assert from "node:assert/strict";
import test from "node:test";

import {
  parseMinecraftBaseUrl,
  requestMinecraftConnect,
  requestMinecraftDisconnect,
  requestMinecraftLook,
  requestMinecraftMove,
  requestMinecraftStatus,
} from "../dist-electron/minecraft-client.js";

const TOKEN = "abcdefghijklmnopqrstuvwxyz0123456789ABCDEFG";

function jsonResponse(payload, init = {}) {
  return new Response(JSON.stringify(payload), {
    status: init.status ?? 200,
    headers: {
      "content-type": "application/json",
      ...init.headers,
    },
  });
}

test("Minecraft client accepts only fixed numeric loopback HTTP", () => {
  assert.equal(
    parseMinecraftBaseUrl("http://127.0.0.1:8766"),
    "http://127.0.0.1:8766",
  );
  for (const unsafe of [
    "http://localhost:8766",
    "https://127.0.0.1:8766",
    "http://127.0.0.1:8766/path",
    "http://user@127.0.0.1:8766",
    "http://192.168.1.2:8766",
  ]) {
    assert.throws(
      () => parseMinecraftBaseUrl(unsafe),
      /E_DESKTOP_MINECRAFT_URL/,
    );
  }
});

test("Minecraft client requires an ephemeral secret before network I/O", async () => {
  let called = false;
  await assert.rejects(
    requestMinecraftStatus({
      controlToken: "",
      fetchImpl: async () => {
        called = true;
        return jsonResponse({});
      },
    }),
    /E_DESKTOP_MINECRAFT_AUTHORITY/,
  );
  assert.equal(called, false);
});

test("Minecraft client validates private connection before network I/O", () => {
  let called = false;
  assert.throws(
    () => requestMinecraftConnect(
      {
        host: "example.com",
        port: 25565,
        username: "Hina",
        version: null,
      },
      {
        controlToken: TOKEN,
        fetchImpl: async () => {
          called = true;
          return jsonResponse({});
        },
      },
    ),
    /E_DESKTOP_MINECRAFT_INPUT/,
  );
  assert.equal(called, false);
});

test("Minecraft mutations use fixed paths, authority headers and exact bodies", async () => {
  const requests = [];
  const fetchImpl = async (url, init) => {
    requests.push({
      url,
      method: init.method,
      authorization: init.headers.Authorization,
      source: init.headers["X-Hina-Source"],
      body: init.body === undefined ? null : JSON.parse(init.body),
    });
    return jsonResponse({ status: "ok" });
  };

  await requestMinecraftConnect(
    {
      host: "192.168.1.10",
      port: 25565,
      username: "Hina",
      version: "1.21.8",
    },
    { controlToken: TOKEN, fetchImpl },
  );
  await requestMinecraftLook(
    { yawRadians: 0.5, pitchRadians: -0.25 },
    { controlToken: TOKEN, fetchImpl },
  );
  await requestMinecraftMove(
    { direction: "north", distanceBlocks: 1.5 },
    { controlToken: TOKEN, fetchImpl },
  );
  await requestMinecraftDisconnect({ controlToken: TOKEN, fetchImpl });

  assert.deepEqual(
    requests.map((request) => request.url),
    [
      "http://127.0.0.1:8766/v1/minecraft/connect",
      "http://127.0.0.1:8766/v1/minecraft/skills/look",
      "http://127.0.0.1:8766/v1/minecraft/skills/move-step",
      "http://127.0.0.1:8766/v1/minecraft/disconnect",
    ],
  );
  assert.ok(
    requests.every(
      (request) =>
        request.method === "POST" &&
        request.authorization === `Bearer ${TOKEN}` &&
        request.source === "owner.desktop",
    ),
  );
  assert.deepEqual(requests[1].body, {
    arguments: { yawRadians: 0.5, pitchRadians: -0.25 },
    ownerConfirmed: true,
    skillId: "look.v1",
    source: "owner.desktop",
  });
  assert.deepEqual(requests[2].body, {
    arguments: { direction: "north", distanceBlocks: 1.5 },
    ownerConfirmed: true,
    skillId: "move.step.v1",
    source: "owner.desktop",
  });
});

test("Minecraft client rejects unsafe movement before network I/O", () => {
  let called = false;
  assert.throws(
    () =>
      requestMinecraftMove(
        { direction: "up", distanceBlocks: 99 },
        {
          controlToken: TOKEN,
          fetchImpl: async () => {
            called = true;
            return jsonResponse({});
          },
        },
      ),
    /E_DESKTOP_MINECRAFT_INPUT/,
  );
  assert.equal(called, false);
});

test("Minecraft client rejects oversized and invalid JSON responses", async () => {
  await assert.rejects(
    requestMinecraftStatus({
      controlToken: TOKEN,
      fetchImpl: async () =>
        new Response("{}", {
          headers: { "content-length": "65537" },
        }),
    }),
    /E_DESKTOP_MINECRAFT_RESPONSE/,
  );
  await assert.rejects(
    requestMinecraftStatus({
      controlToken: TOKEN,
      fetchImpl: async () => new Response("not json"),
    }),
    /E_DESKTOP_MINECRAFT_RESPONSE/,
  );
});
