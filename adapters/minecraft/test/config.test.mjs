import assert from "node:assert/strict";
import test from "node:test";

import {
  MinecraftAdapterError,
  parseMinecraftConnectionConfig,
  validatePrivateMinecraftHost,
} from "../dist/index.js";

test("defaults to a local offline test target", () => {
  assert.deepEqual(parseMinecraftConnectionConfig([], {}), {
    host: "127.0.0.1",
    port: 25565,
    username: "Hina",
    connectTimeoutMs: 30_000,
    statusPort: 8766,
  });
});

test("CLI values override environment values", () => {
  const result = parseMinecraftConnectionConfig(
    [
      "--host",
      "192.168.1.25",
      "--port",
      "25570",
      "--username",
      "HinaBot",
      "--version",
      "1.21.8",
      "--connect-timeout-ms",
      "45000",
      "--status-port",
      "8877",
    ],
    {
      HINA_MINECRAFT_HOST: "10.0.0.2",
      HINA_MINECRAFT_PORT: "25566",
    },
  );
  assert.deepEqual(result, {
    host: "192.168.1.25",
    port: 25570,
    username: "HinaBot",
    version: "1.21.8",
    connectTimeoutMs: 45_000,
    statusPort: 8877,
  });
});

test("accepts only loopback and private address classes", () => {
  for (const host of [
    "localhost",
    "127.0.0.1",
    "127.12.2.3",
    "10.1.2.3",
    "172.16.0.1",
    "172.31.255.254",
    "192.168.2.4",
    "::1",
    "fd12::1",
    "fe80::1",
  ]) {
    assert.equal(validatePrivateMinecraftHost(host), host);
  }
});

test("rejects public IPs, DNS names and malformed targets", () => {
  for (const host of [
    "8.8.8.8",
    "172.32.0.1",
    "example.com",
    "play.example.com",
    "0.0.0.0",
    "::",
    "::ffff:127.0.0.1",
  ]) {
    assert.throws(
      () => validatePrivateMinecraftHost(host),
      (error) =>
        error instanceof MinecraftAdapterError &&
        error.code === "E_MINECRAFT_PUBLIC_TARGET",
    );
  }
});

test("fails closed on duplicate, unknown or unsafe config", () => {
  for (const args of [
    ["--host", "127.0.0.1", "--host", "10.0.0.1"],
    ["--online-auth", "true"],
    ["--port"],
    ["--username", "x"],
    ["--version", "latest"],
    ["--status-port", "0"],
    ["--connect-timeout-ms", "999"],
  ]) {
    assert.throws(
      () => parseMinecraftConnectionConfig(args, {}),
      (error) =>
        error instanceof MinecraftAdapterError &&
        error.code === "E_MINECRAFT_CONFIG",
    );
  }
});
