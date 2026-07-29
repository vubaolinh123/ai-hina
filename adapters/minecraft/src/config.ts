import { isIP } from "node:net";

import {
  MinecraftAdapterError,
  type MinecraftConnectionConfig,
} from "./contracts.js";

const DEFAULTS = Object.freeze({
  host: "127.0.0.1",
  port: 25565,
  username: "Hina",
  connectTimeoutMs: 30_000,
  statusPort: 8766,
});

const ARG_TO_FIELD = Object.freeze({
  "--host": "host",
  "--port": "port",
  "--username": "username",
  "--version": "version",
  "--connect-timeout-ms": "connectTimeoutMs",
  "--status-port": "statusPort",
} as const);

const ENV_TO_FIELD = Object.freeze({
  HINA_MINECRAFT_HOST: "host",
  HINA_MINECRAFT_PORT: "port",
  HINA_MINECRAFT_USERNAME: "username",
  HINA_MINECRAFT_VERSION: "version",
  HINA_MINECRAFT_CONNECT_TIMEOUT_MS: "connectTimeoutMs",
  HINA_MINECRAFT_STATUS_PORT: "statusPort",
} as const);

type ConfigField = (typeof ARG_TO_FIELD)[keyof typeof ARG_TO_FIELD];
type RawConfig = Partial<Record<ConfigField, string>>;

function parseInteger(
  value: string | undefined,
  field: string,
  fallback: number,
  minimum: number,
  maximum: number,
): number {
  if (value === undefined) {
    return fallback;
  }
  if (!/^[0-9]+$/.test(value)) {
    throw new MinecraftAdapterError(
      "E_MINECRAFT_CONFIG",
      `${field} must be an integer`,
    );
  }
  const parsed = Number.parseInt(value, 10);
  if (parsed < minimum || parsed > maximum) {
    throw new MinecraftAdapterError(
      "E_MINECRAFT_CONFIG",
      `${field} must be between ${minimum} and ${maximum}`,
    );
  }
  return parsed;
}

function isPrivateIpv4(host: string): boolean {
  const octets = host.split(".").map((part) => Number.parseInt(part, 10));
  if (octets.length !== 4 || octets.some((part) => !Number.isInteger(part))) {
    return false;
  }
  const [first, second] = octets;
  return (
    first === 10 ||
    first === 127 ||
    (first === 172 && second !== undefined && second >= 16 && second <= 31) ||
    (first === 192 && second === 168)
  );
}

function isPrivateIpv6(host: string): boolean {
  const normalized = host.toLowerCase();
  if (normalized === "::1") {
    return true;
  }
  const firstGroup = normalized.split(":")[0];
  if (firstGroup === undefined || firstGroup.length === 0) {
    return false;
  }
  const firstValue = Number.parseInt(firstGroup, 16);
  return (
    (firstValue >= 0xfc00 && firstValue <= 0xfdff) ||
    (firstValue >= 0xfe80 && firstValue <= 0xfebf)
  );
}

export function validatePrivateMinecraftHost(value: string): string {
  const host = value.trim().toLowerCase();
  if (host === "localhost") {
    return host;
  }
  const ipVersion = isIP(host);
  const allowed =
    (ipVersion === 4 && isPrivateIpv4(host)) ||
    (ipVersion === 6 && isPrivateIpv6(host));
  if (!allowed) {
    throw new MinecraftAdapterError(
      "E_MINECRAFT_PUBLIC_TARGET",
      "Minecraft target must be localhost or a private IP address",
    );
  }
  return host;
}

function readEnvironment(environment: NodeJS.ProcessEnv): RawConfig {
  const result: RawConfig = {};
  for (const [environmentKey, field] of Object.entries(ENV_TO_FIELD)) {
    const value = environment[environmentKey];
    if (value !== undefined && value.trim().length > 0) {
      result[field as ConfigField] = value.trim();
    }
  }
  return result;
}

function readArguments(argumentsList: readonly string[]): RawConfig {
  const result: RawConfig = {};
  const seen = new Set<string>();
  for (let index = 0; index < argumentsList.length; index += 2) {
    const key = argumentsList[index];
    const value = argumentsList[index + 1];
    if (
      key === undefined ||
      !(key in ARG_TO_FIELD) ||
      value === undefined ||
      value.startsWith("--")
    ) {
      throw new MinecraftAdapterError(
        "E_MINECRAFT_CONFIG",
        `Unknown or incomplete Minecraft argument: ${key ?? "<missing>"}`,
      );
    }
    if (seen.has(key)) {
      throw new MinecraftAdapterError(
        "E_MINECRAFT_CONFIG",
        `Duplicate Minecraft argument: ${key}`,
      );
    }
    seen.add(key);
    result[ARG_TO_FIELD[key as keyof typeof ARG_TO_FIELD]] = value;
  }
  return result;
}

export function parseMinecraftConnectionConfig(
  argumentsList: readonly string[],
  environment: NodeJS.ProcessEnv = process.env,
): MinecraftConnectionConfig {
  const raw = {
    ...readEnvironment(environment),
    ...readArguments(argumentsList),
  };
  const username = (raw.username ?? DEFAULTS.username).trim();
  if (!/^[A-Za-z0-9_]{3,16}$/.test(username)) {
    throw new MinecraftAdapterError(
      "E_MINECRAFT_CONFIG",
      "username must contain 3-16 Minecraft-safe characters",
    );
  }
  const version = raw.version?.trim();
  if (
    version !== undefined &&
    !/^[0-9]+\.[0-9]+(?:\.[0-9]+)?$/.test(version)
  ) {
    throw new MinecraftAdapterError(
      "E_MINECRAFT_CONFIG",
      "version must use a numeric Minecraft version such as 1.21.8",
    );
  }

  return {
    host: validatePrivateMinecraftHost(raw.host ?? DEFAULTS.host),
    port: parseInteger(raw.port, "port", DEFAULTS.port, 1, 65_535),
    username,
    ...(version === undefined ? {} : { version }),
    connectTimeoutMs: parseInteger(
      raw.connectTimeoutMs,
      "connectTimeoutMs",
      DEFAULTS.connectTimeoutMs,
      1_000,
      120_000,
    ),
    statusPort: parseInteger(
      raw.statusPort,
      "statusPort",
      DEFAULTS.statusPort,
      1,
      65_535,
    ),
  };
}

export function validateMinecraftConnectionInput(
  value: unknown,
  statusPort: number,
): MinecraftConnectionConfig {
  if (
    typeof value !== "object" ||
    value === null ||
    Array.isArray(value)
  ) {
    throw new MinecraftAdapterError(
      "E_MINECRAFT_CONFIG",
      "Minecraft connection must be an object",
    );
  }
  const raw = value as Record<string, unknown>;
  const expected = [
    "host",
    "ownerConfirmed",
    "port",
    "source",
    "username",
    "version",
  ];
  const actual = Object.keys(raw).sort();
  if (
    actual.length !== expected.length ||
    actual.some((field, index) => field !== expected[index]) ||
    raw.source !== "owner.desktop" ||
    raw.ownerConfirmed !== true ||
    typeof raw.host !== "string" ||
    typeof raw.username !== "string" ||
    typeof raw.port !== "number" ||
    !Number.isInteger(raw.port) ||
    (raw.version !== null && typeof raw.version !== "string")
  ) {
    throw new MinecraftAdapterError(
      "E_MINECRAFT_CONFIG",
      "Minecraft connection fields are invalid",
    );
  }
  return parseMinecraftConnectionConfig(
    [
      "--host",
      raw.host,
      "--port",
      String(raw.port),
      "--username",
      raw.username,
      ...(raw.version === null ? [] : ["--version", raw.version]),
      "--status-port",
      String(statusPort),
    ],
    {},
  );
}
