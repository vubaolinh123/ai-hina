const DEFAULT_CONTROL_BASE = "http://127.0.0.1:8765";
const REQUEST_TIMEOUT_MILLISECONDS = 5_000;
const MAX_RESPONSE_BYTES = 262_144;

type JsonObject = Record<string, unknown>;
type ControlOperation =
  | "avatar.status"
  | "avatar.cue"
  | "avatar.reset"
  | "safety.status"
  | "safety.control"
  | "runtime.health";

type OperationSpec = {
  method: "GET" | "POST";
  path: string;
};

const OPERATIONS: Readonly<Record<ControlOperation, OperationSpec>> = Object.freeze({
  "avatar.status": { method: "GET", path: "/v1/avatar/status" },
  "avatar.cue": { method: "POST", path: "/v1/avatar/cues" },
  "avatar.reset": { method: "POST", path: "/v1/avatar/reset" },
  "safety.status": { method: "GET", path: "/v1/safety/status" },
  "safety.control": { method: "POST", path: "/v1/safety/control" },
  "runtime.health": { method: "GET", path: "/v1/health" },
});

const AVATAR_STATES = new Set([
  "idle",
  "listening",
  "thinking",
  "speaking",
  "interrupted",
  "error",
]);
const AVATAR_CUE_FIELDS = new Set(["source", "state", "mode"]);
const SAFETY_ACTIONS = new Set(["set_mute", "emergency_stop", "emergency_reset"]);

export function parseControlBaseUrl(raw = DEFAULT_CONTROL_BASE): string {
  let parsed: URL;
  try {
    parsed = new URL(raw);
  } catch {
    throw new Error("E_DESKTOP_CONTROL_URL: control-plane URL is invalid");
  }
  if (
    parsed.protocol !== "http:"
    || parsed.hostname !== "127.0.0.1"
    || parsed.username
    || parsed.password
    || parsed.pathname !== "/"
    || parsed.search
    || parsed.hash
  ) {
    throw new Error("E_DESKTOP_CONTROL_URL: control plane must use numeric loopback HTTP");
  }
  const port = Number(parsed.port || 80);
  if (!Number.isInteger(port) || port < 1 || port > 65_535) {
    throw new Error("E_DESKTOP_CONTROL_URL: control-plane port is invalid");
  }
  return `${parsed.protocol}//${parsed.hostname}:${port}`;
}

export function validateAvatarCue(raw: unknown): JsonObject {
  if (!isObject(raw) || Object.keys(raw).some((key) => !AVATAR_CUE_FIELDS.has(key))) {
    throw new Error("E_DESKTOP_AVATAR_CUE: cue fields are invalid");
  }
  if (
    raw.source !== "owner.console"
    || typeof raw.state !== "string"
    || !AVATAR_STATES.has(raw.state)
    || raw.mode !== "manual-preview"
  ) {
    throw new Error("E_DESKTOP_AVATAR_CUE: only owner manual preview is allowed");
  }
  return {
    source: "owner.console",
    state: raw.state,
    mode: "manual-preview",
  };
}

export function validateSafetyControl(raw: unknown): JsonObject {
  if (!isObject(raw) || typeof raw.action !== "string" || !SAFETY_ACTIONS.has(raw.action)) {
    throw new Error("E_DESKTOP_SAFETY_CONTROL: safety action is invalid");
  }
  const expectedKeys = raw.action === "set_mute"
    ? new Set(["action", "enabled"])
    : new Set(["action"]);
  if (Object.keys(raw).some((key) => !expectedKeys.has(key))) {
    throw new Error("E_DESKTOP_SAFETY_CONTROL: safety control fields are invalid");
  }
  if (raw.action === "set_mute" && typeof raw.enabled !== "boolean") {
    throw new Error("E_DESKTOP_SAFETY_CONTROL: mute requires a boolean enabled field");
  }
  return raw.action === "set_mute"
    ? { action: raw.action, enabled: raw.enabled }
    : { action: raw.action };
}

export async function requestControl(
  operation: ControlOperation,
  payload?: JsonObject,
  options: {
    baseUrl?: string;
    fetchImpl?: typeof fetch;
  } = {},
): Promise<JsonObject> {
  const spec = OPERATIONS[operation];
  if (!spec) {
    throw new Error("E_DESKTOP_OPERATION: control operation is not allowlisted");
  }
  if (spec.method === "GET" && payload !== undefined) {
    throw new Error("E_DESKTOP_OPERATION: GET operation cannot include a body");
  }
  if (spec.method === "POST" && payload === undefined) {
    throw new Error("E_DESKTOP_OPERATION: POST operation requires a body");
  }
  const baseUrl = parseControlBaseUrl(
    options.baseUrl ?? process.env.HINA_CONTROL_BASE_URL ?? DEFAULT_CONTROL_BASE,
  );
  const fetchImpl = options.fetchImpl ?? fetch;
  let response: Response;
  try {
    response = await fetchImpl(`${baseUrl}${spec.path}`, {
      method: spec.method,
      cache: "no-store",
      headers: {
        Accept: "application/json",
        ...(payload ? { "Content-Type": "application/json" } : {}),
      },
      body: payload ? JSON.stringify(payload) : undefined,
      signal: AbortSignal.timeout(REQUEST_TIMEOUT_MILLISECONDS),
    });
  } catch {
    throw new Error("E_DESKTOP_CONTROL_OFFLINE: Hina control plane is unavailable");
  }
  const declaredLength = Number(response.headers.get("content-length") || 0);
  if (declaredLength > MAX_RESPONSE_BYTES) {
    throw new Error("E_DESKTOP_RESPONSE: control response exceeds the desktop limit");
  }
  const text = await response.text();
  if (new TextEncoder().encode(text).byteLength > MAX_RESPONSE_BYTES) {
    throw new Error("E_DESKTOP_RESPONSE: control response exceeds the desktop limit");
  }
  let result: unknown;
  try {
    result = JSON.parse(text);
  } catch {
    throw new Error("E_DESKTOP_RESPONSE: control response is not valid JSON");
  }
  if (!isObject(result)) {
    throw new Error("E_DESKTOP_RESPONSE: control response must be an object");
  }
  if (!response.ok) {
    const code = typeof result.errorCode === "string"
      ? result.errorCode.slice(0, 64)
      : `HTTP_${response.status}`;
    const message = typeof result.message === "string"
      ? result.message.slice(0, 192)
      : "control request failed";
    throw new Error(`${code}: ${message}`);
  }
  return result;
}

function isObject(value: unknown): value is JsonObject {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
