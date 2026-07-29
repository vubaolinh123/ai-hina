import { isIP } from "node:net";

const DEFAULT_BASE_URL = "http://127.0.0.1:8766";
const MAX_RESPONSE_BYTES = 65_536;
const DEFAULT_TIMEOUT_MILLISECONDS = 5_000;
const CONNECT_TIMEOUT_MILLISECONDS = 125_000;
const SOURCE = "owner.desktop";

type JsonObject = Record<string, unknown>;
type RequestOptions = {
  baseUrl?: string;
  controlToken?: string;
  fetchImpl?: typeof fetch;
  timeoutMilliseconds?: number;
};

function isObject(value: unknown): value is JsonObject {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isPrivateIpv4(host: string): boolean {
  const parts = host.split(".").map((part) => Number.parseInt(part, 10));
  if (parts.length !== 4 || parts.some((part) => !Number.isInteger(part))) {
    return false;
  }
  const [first, second] = parts;
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
  const first = Number.parseInt(normalized.split(":")[0] ?? "", 16);
  return (
    Number.isInteger(first) &&
    ((first >= 0xfc00 && first <= 0xfdff) ||
      (first >= 0xfe80 && first <= 0xfebf))
  );
}

function validatePrivateHost(value: unknown): string {
  if (typeof value !== "string") {
    throw new Error("E_DESKTOP_MINECRAFT_INPUT: host must be a string");
  }
  const host = value.trim().toLowerCase();
  const version = isIP(host);
  if (
    host !== "localhost" &&
    !(
      (version === 4 && isPrivateIpv4(host)) ||
      (version === 6 && isPrivateIpv6(host))
    )
  ) {
    throw new Error(
      "E_DESKTOP_MINECRAFT_INPUT: target must be localhost or a private IP",
    );
  }
  return host;
}

export function parseMinecraftBaseUrl(raw = DEFAULT_BASE_URL): string {
  let parsed: URL;
  try {
    parsed = new URL(raw);
  } catch {
    throw new Error("E_DESKTOP_MINECRAFT_URL: service URL is invalid");
  }
  if (
    parsed.protocol !== "http:" ||
    parsed.hostname !== "127.0.0.1" ||
    parsed.username ||
    parsed.password ||
    parsed.pathname !== "/" ||
    parsed.search ||
    parsed.hash
  ) {
    throw new Error(
      "E_DESKTOP_MINECRAFT_URL: service must use numeric loopback HTTP",
    );
  }
  const port = Number(parsed.port || 80);
  if (!Number.isInteger(port) || port < 1 || port > 65_535) {
    throw new Error("E_DESKTOP_MINECRAFT_URL: service port is invalid");
  }
  return `${parsed.protocol}//${parsed.hostname}:${port}`;
}

function validateControlToken(value: string | undefined): string {
  if (
    value === undefined ||
    value.length < 43 ||
    value.length > 256 ||
    /[^A-Za-z0-9_-]/u.test(value)
  ) {
    throw new Error(
      "E_DESKTOP_MINECRAFT_AUTHORITY: ephemeral control token is unavailable",
    );
  }
  return value;
}

export function validateMinecraftConnectInput(value: unknown): JsonObject {
  if (!isObject(value)) {
    throw new Error("E_DESKTOP_MINECRAFT_INPUT: connection must be an object");
  }
  const fields = Object.keys(value).sort().join(",");
  if (
    fields !== "host,port,username,version" ||
    typeof value.port !== "number" ||
    !Number.isInteger(value.port) ||
    value.port < 1 ||
    value.port > 65_535 ||
    typeof value.username !== "string" ||
    !/^[A-Za-z0-9_]{3,16}$/u.test(value.username) ||
    (value.version !== null &&
      (typeof value.version !== "string" ||
        !/^[0-9]+\.[0-9]+(?:\.[0-9]+)?$/u.test(value.version)))
  ) {
    throw new Error(
      "E_DESKTOP_MINECRAFT_INPUT: connection fields are invalid",
    );
  }
  return {
    host: validatePrivateHost(value.host),
    ownerConfirmed: true,
    port: value.port,
    source: SOURCE,
    username: value.username,
    version: value.version,
  };
}

export function validateMinecraftGoalInput(value: unknown): JsonObject {
  if (
    !isObject(value) ||
    Object.keys(value).sort().join(",") !== "goalId" ||
    value.goalId !== "harvest.nearby-log.v1"
  ) {
    throw new Error("E_DESKTOP_MINECRAFT_GOAL: goal is not in the fixed allowlist");
  }
  return {
    goalId: "harvest.nearby-log.v1",
    ownerConfirmed: true,
    source: SOURCE,
  };
}

async function requestMinecraft(
  path: string,
  method: "GET" | "POST",
  payload: JsonObject | undefined,
  options: RequestOptions,
): Promise<JsonObject> {
  const baseUrl = parseMinecraftBaseUrl(options.baseUrl ?? DEFAULT_BASE_URL);
  const token = validateControlToken(
    options.controlToken ?? process.env.HINA_MINECRAFT_CONTROL_TOKEN,
  );
  const timeoutMilliseconds =
    options.timeoutMilliseconds ??
    (path === "/v1/minecraft/connect"
      ? CONNECT_TIMEOUT_MILLISECONDS
      : path === "/v1/minecraft/goals/execute"
        ? 15_000
      : DEFAULT_TIMEOUT_MILLISECONDS);
  if (
    !Number.isInteger(timeoutMilliseconds) ||
    timeoutMilliseconds < 1 ||
    timeoutMilliseconds > CONNECT_TIMEOUT_MILLISECONDS
  ) {
    throw new Error("E_DESKTOP_MINECRAFT_TIMEOUT: timeout is invalid");
  }
  let response: Response;
  try {
    response = await (options.fetchImpl ?? fetch)(`${baseUrl}${path}`, {
      method,
      cache: "no-store",
      headers: {
        Accept: "application/json",
        Authorization: `Bearer ${token}`,
        "X-Hina-Source": SOURCE,
        ...(payload === undefined
          ? {}
          : { "Content-Type": "application/json" }),
      },
      body: payload === undefined ? undefined : JSON.stringify(payload),
      signal: AbortSignal.timeout(timeoutMilliseconds),
    });
  } catch (error) {
    const name =
      error &&
      typeof error === "object" &&
      "name" in error &&
      typeof error.name === "string"
        ? error.name
        : "";
    if (name === "TimeoutError" || name === "AbortError") {
      throw new Error(
        `E_DESKTOP_MINECRAFT_TIMEOUT: service did not answer within ${timeoutMilliseconds} ms`,
      );
    }
    throw new Error(
      "E_DESKTOP_MINECRAFT_OFFLINE: Minecraft control service is unavailable",
    );
  }
  const declaredLength = Number(response.headers.get("content-length") || 0);
  if (declaredLength > MAX_RESPONSE_BYTES) {
    throw new Error(
      "E_DESKTOP_MINECRAFT_RESPONSE: response exceeds the desktop limit",
    );
  }
  const text = await response.text();
  if (new TextEncoder().encode(text).byteLength > MAX_RESPONSE_BYTES) {
    throw new Error(
      "E_DESKTOP_MINECRAFT_RESPONSE: response exceeds the desktop limit",
    );
  }
  let result: unknown;
  try {
    result = JSON.parse(text);
  } catch {
    throw new Error(
      "E_DESKTOP_MINECRAFT_RESPONSE: response is not valid JSON",
    );
  }
  if (!isObject(result)) {
    throw new Error(
      "E_DESKTOP_MINECRAFT_RESPONSE: response must be an object",
    );
  }
  if (!response.ok) {
    const code =
      typeof result.errorCode === "string"
        ? result.errorCode.slice(0, 64)
        : `HTTP_${response.status}`;
    const message =
      typeof result.message === "string"
        ? result.message.slice(0, 192)
        : "Minecraft control request failed";
    throw new Error(`${code}: ${message}`);
  }
  return result;
}

export function requestMinecraftStatus(
  options: RequestOptions = {},
): Promise<JsonObject> {
  return requestMinecraft("/v1/minecraft/status", "GET", undefined, options);
}

export function requestMinecraftConnect(
  input: unknown,
  options: RequestOptions = {},
): Promise<JsonObject> {
  return requestMinecraft(
    "/v1/minecraft/connect",
    "POST",
    validateMinecraftConnectInput(input),
    options,
  );
}

export function requestMinecraftDisconnect(
  options: RequestOptions = {},
): Promise<JsonObject> {
  return requestMinecraft(
    "/v1/minecraft/disconnect",
    "POST",
    {
      action: "disconnect",
      ownerConfirmed: true,
      source: SOURCE,
    },
    options,
  );
}

export function requestMinecraftGoal(
  input: unknown,
  options: RequestOptions = {},
): Promise<JsonObject> {
  return requestMinecraft(
    "/v1/minecraft/goals/execute",
    "POST",
    validateMinecraftGoalInput(input),
    options,
  );
}

export function requestMinecraftEmergencyStop(
  options: RequestOptions = {},
): Promise<JsonObject> {
  return requestMinecraft(
    "/v1/minecraft/emergency-stop",
    "POST",
    {
      action: "emergency_stop",
      ownerConfirmed: true,
      source: SOURCE,
    },
    options,
  );
}
