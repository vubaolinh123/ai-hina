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
  | "runtime.health"
  | "chat.status";

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
  "chat.status": { method: "GET", path: "/v1/chat/status" },
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

const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[4-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

function validateUuid(value: unknown, code: string): string {
  if (typeof value !== "string" || !UUID_PATTERN.test(value)) {
    throw new Error(`${code}: identifier is invalid`);
  }
  return value;
}

function validateChatText(value: unknown): string {
  if (typeof value !== "string" || value.trim().length < 1 || value.length > 16_384) {
    throw new Error("E_DESKTOP_CHAT_REQUEST: text is invalid");
  }
  return value.trim();
}

export async function requestChatStatus(): Promise<JsonObject> {
  return requestControl("chat.status" as ControlOperation);
}

export async function requestChatStart(raw: unknown): Promise<JsonObject> {
  if (!isObject(raw) || Object.keys(raw).some((key) => !["sessionId", "source", "text"].includes(key))
    || Object.keys(raw).length !== 3
    || raw.source !== "owner.console") {
    throw new Error("E_DESKTOP_CHAT_REQUEST: fields are invalid");
  }
  return requestPath("POST", "/v1/chat/turns", {
    sessionId: validateUuid(raw.sessionId, "E_DESKTOP_CHAT_REQUEST"),
    source: "owner.console",
    text: validateChatText(raw.text),
  });
}

export async function requestChatTurn(turnId: unknown): Promise<JsonObject> {
  return requestPath("GET", `/v1/chat/turns/${validateUuid(turnId, "E_DESKTOP_CHAT_REQUEST")}`);
}

export async function requestChatCancel(turnId: unknown): Promise<JsonObject> {
  return requestPath(
    "POST",
    `/v1/chat/turns/${validateUuid(turnId, "E_DESKTOP_CHAT_REQUEST")}/cancel`,
    {},
  );
}

export async function requestSpeechSynthesis(raw: unknown): Promise<Uint8Array> {
  if (!isObject(raw)
    || Object.keys(raw).length !== 4
    || !["text", "utteranceId", "sessionId", "source"].every((key) => key in raw)
    || raw.source !== "owner.console") {
    throw new Error("E_DESKTOP_TTS_REQUEST: fields are invalid");
  }
  validateUuid(raw.utteranceId, "E_DESKTOP_TTS_REQUEST");
  if (raw.sessionId !== null) validateUuid(raw.sessionId, "E_DESKTOP_TTS_REQUEST");
  const response = await requestBinaryPath("POST", "/v1/tts/synthesis", raw);
  if (new TextDecoder().decode(response.subarray(0, 4)) !== "RIFF") {
    throw new Error("E_DESKTOP_TTS_RESPONSE: response is not WAV");
  }
  return response;
}

export async function requestSpeechTranscription(
  rawAudio: unknown,
  sessionId: unknown,
  options: {
    baseUrl?: string;
    fetchImpl?: typeof fetch;
  } = {},
): Promise<JsonObject> {
  const audio = validateWavAudio(rawAudio);
  const validatedSessionId = validateUuid(sessionId, "E_DESKTOP_STT_REQUEST");
  const baseUrl = parseControlBaseUrl(
    options.baseUrl
      ?? process.env.HINA_CONTROL_BASE_URL
      ?? DEFAULT_CONTROL_BASE,
  );
  const fetchImpl = options.fetchImpl ?? fetch;
  let response: Response;
  try {
    response = await fetchImpl(`${baseUrl}/v1/speech/transcriptions`, {
      method: "POST",
      cache: "no-store",
      headers: {
        Accept: "application/json",
        "Content-Type": "audio/wav",
        "X-Hina-Correlation-Id": crypto.randomUUID(),
        "X-Hina-Session-Id": validatedSessionId,
        "X-Hina-Source": "owner.desktop",
      },
      body: audio.buffer.slice(
        audio.byteOffset,
        audio.byteOffset + audio.byteLength,
      ) as ArrayBuffer,
      signal: AbortSignal.timeout(120_000),
    });
  } catch {
    throw new Error("E_DESKTOP_CONTROL_OFFLINE: Hina control plane is unavailable");
  }
  const text = await response.text();
  if (new TextEncoder().encode(text).byteLength > MAX_RESPONSE_BYTES) {
    throw new Error("E_DESKTOP_RESPONSE: speech response exceeds the desktop limit");
  }
  let result: unknown;
  try {
    result = JSON.parse(text);
  } catch {
    throw new Error("E_DESKTOP_RESPONSE: speech response is not valid JSON");
  }
  if (!isObject(result)) {
    throw new Error("E_DESKTOP_RESPONSE: speech response must be an object");
  }
  if (!response.ok) {
    const code = typeof result.errorCode === "string"
      ? result.errorCode.slice(0, 64)
      : `HTTP_${response.status}`;
    const message = typeof result.message === "string"
      ? result.message.slice(0, 192)
      : "speech transcription failed";
    throw new Error(`${code}: ${message}`);
  }
  return result;
}

async function requestPath(
  method: "GET" | "POST",
  path: string,
  payload?: JsonObject,
): Promise<JsonObject> {
  const baseUrl = parseControlBaseUrl(
    process.env.HINA_CONTROL_BASE_URL ?? DEFAULT_CONTROL_BASE,
  );
  let response: Response;
  try {
    response = await fetch(`${baseUrl}${path}`, {
      method,
      cache: "no-store",
      headers: { Accept: "application/json", ...(payload ? { "Content-Type": "application/json" } : {}) },
      body: payload ? JSON.stringify(payload) : undefined,
      signal: AbortSignal.timeout(REQUEST_TIMEOUT_MILLISECONDS),
    });
  } catch {
    throw new Error("E_DESKTOP_CONTROL_OFFLINE: Hina control plane is unavailable");
  }
  const text = await response.text();
  let result: unknown;
  try {
    result = JSON.parse(text);
  } catch {
    throw new Error("E_DESKTOP_RESPONSE: control response is not valid JSON");
  }
  if (!isObject(result)) throw new Error("E_DESKTOP_RESPONSE: control response must be an object");
  if (!response.ok) {
    throw new Error(`${typeof result.errorCode === "string" ? result.errorCode : `HTTP_${response.status}`}: ${typeof result.message === "string" ? result.message : "control request failed"}`);
  }
  return result;
}

async function requestBinaryPath(
  method: "GET" | "POST",
  path: string,
  payload: JsonObject,
): Promise<Uint8Array> {
  const baseUrl = parseControlBaseUrl(
    process.env.HINA_CONTROL_BASE_URL ?? DEFAULT_CONTROL_BASE,
  );
  let response: Response;
  try {
    response = await fetch(`${baseUrl}${path}`, {
      method,
      cache: "no-store",
      headers: { Accept: "audio/wav", "Content-Type": "application/json" },
      body: JSON.stringify(payload),
      signal: AbortSignal.timeout(120_000),
    });
  } catch {
    throw new Error("E_DESKTOP_CONTROL_OFFLINE: Hina control plane is unavailable");
  }
  const bytes = new Uint8Array(await response.arrayBuffer());
  if (bytes.byteLength > 8 * 1024 * 1024) throw new Error("E_DESKTOP_RESPONSE: audio response exceeds desktop limit");
  if (!response.ok) {
    const text = new TextDecoder().decode(bytes);
    let result: unknown;
    try { result = JSON.parse(text); } catch { result = null; }
    const record = isObject(result) ? result : {};
    throw new Error(`${typeof record.errorCode === "string" ? record.errorCode : `HTTP_${response.status}`}: ${typeof record.message === "string" ? record.message : "speech synthesis failed"}`);
  }
  return bytes;
}

function validateWavAudio(raw: unknown): Uint8Array {
  const audio = raw instanceof Uint8Array
    ? raw
    : raw instanceof ArrayBuffer
      ? new Uint8Array(raw)
      : null;
  if (!audio || audio.byteLength < 44 || audio.byteLength > 1_048_576) {
    throw new Error("E_DESKTOP_STT_REQUEST: WAV audio must be between 44 bytes and 1 MiB");
  }
  const riff = new TextDecoder().decode(audio.subarray(0, 4));
  const wave = new TextDecoder().decode(audio.subarray(8, 12));
  if (riff !== "RIFF" || wave !== "WAVE") {
    throw new Error("E_DESKTOP_STT_REQUEST: audio must be a RIFF/WAVE payload");
  }
  return audio;
}

function isObject(value: unknown): value is JsonObject {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
