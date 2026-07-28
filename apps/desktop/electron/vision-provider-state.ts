export const VISION_PROVIDER_STATE_MAX_BYTES = 24_576;

export type PersistedVisionProvider = "disabled" | "ollama_local" | "ollama_cloud";

export type PersistedVisionProviderState = {
  schemaVersion: 1;
  provider: PersistedVisionProvider;
  model: string | null;
  encryptedApiKey: string | null;
};

const MODEL_PATTERN = /^[^\u0000-\u001f\u007f]{1,160}$/u;
const BASE64_PATTERN = /^(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?$/u;

export function parseVisionProviderState(
  raw: string,
): PersistedVisionProviderState | null {
  if (
    typeof raw !== "string"
    || Buffer.byteLength(raw, "utf8") > VISION_PROVIDER_STATE_MAX_BYTES
  ) {
    return null;
  }
  let value: unknown;
  try {
    value = JSON.parse(raw);
  } catch {
    return null;
  }
  if (
    !value
    || typeof value !== "object"
    || Array.isArray(value)
    || Object.keys(value).some(
      (key) => !["schemaVersion", "provider", "model", "encryptedApiKey"].includes(key),
    )
  ) {
    return null;
  }
  const record = value as Record<string, unknown>;
  if (
    record.schemaVersion !== 1
    || !["disabled", "ollama_local", "ollama_cloud"].includes(
      String(record.provider),
    )
    || !validModel(record.model)
    || !validEncryptedKey(record.encryptedApiKey)
  ) {
    return null;
  }
  if (
    record.provider === "disabled"
    && (record.model !== null || record.encryptedApiKey !== null)
  ) {
    return null;
  }
  if (record.provider !== "disabled" && record.model === null) return null;
  if (record.provider === "ollama_cloud" && record.encryptedApiKey === null) {
    return null;
  }
  return {
    schemaVersion: 1,
    provider: record.provider as PersistedVisionProvider,
    model: record.model as string | null,
    encryptedApiKey: record.encryptedApiKey as string | null,
  };
}

export function serializeVisionProviderState(
  state: PersistedVisionProviderState,
): string {
  const parsed = parseVisionProviderState(JSON.stringify(state));
  if (!parsed) {
    throw new Error("E_DESKTOP_VISION_STATE: provider state is invalid");
  }
  return `${JSON.stringify(parsed)}\n`;
}

function validModel(value: unknown): boolean {
  return value === null
    || (
      typeof value === "string"
      && value === value.trim()
      && MODEL_PATTERN.test(value)
    );
}

function validEncryptedKey(value: unknown): boolean {
  return value === null
    || (
      typeof value === "string"
      && value.length >= 4
      && value.length <= 16_384
      && value.length % 4 === 0
      && BASE64_PATTERN.test(value)
    );
}
