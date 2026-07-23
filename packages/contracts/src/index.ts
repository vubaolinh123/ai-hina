import Ajv2020 from "ajv/dist/2020";

import catalog from "../catalog.v1.json";
import compatibilityPolicy from "../compatibility-policy.v1.json";
import envelopeSchema from "../schemas/v1/event-envelope.schema.json";
import mediaReferenceSchema from "../schemas/v1/media-reference.schema.json";
import echoPayloadSchema from "../schemas/v1/payloads/hina.contract.echo.v1.payload.schema.json";
import echoEnvelopeSchema from "../schemas/v1/events/hina.contract.echo.v1.schema.json";
import {
  CATALOG_DIGEST,
  CATALOG_VERSION,
  EVENT_SCHEMA_FILES,
  EVENT_TYPES,
  HINA_CONTRACT_ECHO_V1,
  MAX_JSON_ENVELOPE_BYTES,
  type EventEnvelopeV1,
  type EventType,
  type HinaContractEchoV1Envelope,
  type HinaContractEchoV1Payload,
  type MediaReference,
} from "./generated";

export {
  CATALOG_DIGEST,
  CATALOG_VERSION,
  EVENT_SCHEMA_FILES,
  EVENT_TYPES,
  HINA_CONTRACT_ECHO_V1,
  MAX_JSON_ENVELOPE_BYTES,
  catalog,
  compatibilityPolicy,
  type EventEnvelopeV1,
  type EventType,
  type HinaContractEchoV1Envelope,
  type HinaContractEchoV1Payload,
  type MediaReference,
};

export type ErrorCode =
  | "OK"
  | "E_SCHEMA_MISSING_REQUIRED"
  | "E_SCHEMA_WRONG_TYPE"
  | "E_SCHEMA_UNKNOWN_EVENT"
  | "E_SCHEMA_UNKNOWN_FIELD"
  | "E_SCHEMA_OVERSIZE"
  | "E_SCHEMA_INVALID_ID"
  | "E_SCHEMA_INLINE_BASE64"
  | "E_ROUNDTRIP_UNICODE_LOSS"
  | "E_GEN_DRIFT"
  | "E_FUZZ_ACCEPTED_INVALID"
  | "E_FUZZ_REJECTED_VALID"
  | "E_FUZZ_RUNTIME_CRASH"
  | "E_XLANG_ROUNDTRIP_MISMATCH"
  | "E_COMPAT_N_MINUS_1_UNSPECIFIED"
  | "E_FLAKY_SUITE"
  | "E_GATE_20_RUN_FAIL"
  | "E_PERF_P95_BUDGET";

export interface ValidationResult {
  ok: boolean;
  code: ErrorCode;
  canonicalJson?: string;
  detail?: string;
}

const inlineKeys = new Set(["base64", "bytes", "data", "dataUri", "file", "path", "raw", "uri", "url"]);
const minJsSafeInteger = -9_007_199_254_740_991;
const maxJsSafeInteger = 9_007_199_254_740_991;

const ajv = new Ajv2020({
  allErrors: true,
  coerceTypes: false,
  removeAdditional: false,
  strict: true,
  useDefaults: false,
});

ajv.addSchema(envelopeSchema);
ajv.addSchema(mediaReferenceSchema);
ajv.addSchema(echoPayloadSchema);
const validators = {
  [HINA_CONTRACT_ECHO_V1]: ajv.compile(echoEnvelopeSchema),
} satisfies Record<EventType, ReturnType<typeof ajv.compile>>;

export function canonicalizeEnvelope(value: unknown): string {
  return stableStringify(value);
}

export function validateEnvelopeBytes(raw: Uint8Array): ValidationResult {
  if (raw.byteLength > MAX_JSON_ENVELOPE_BYTES) {
    return { ok: false, code: "E_SCHEMA_OVERSIZE", detail: "raw JSON exceeds limit" };
  }
  let text: string;
  try {
    text = new TextDecoder("utf-8", { fatal: true }).decode(raw);
    return validateEnvelope(JSON.parse(text));
  } catch (error) {
    return { ok: false, code: "E_SCHEMA_WRONG_TYPE", detail: String(error) };
  }
}

export function validateEnvelope(value: unknown): ValidationResult {
  let canonicalJson: string;
  try {
    canonicalJson = canonicalizeEnvelope(value);
  } catch (error) {
    return { ok: false, code: "E_SCHEMA_WRONG_TYPE", detail: String(error) };
  }
  if (new TextEncoder().encode(canonicalJson).byteLength > MAX_JSON_ENVELOPE_BYTES) {
    return { ok: false, code: "E_SCHEMA_OVERSIZE", detail: "canonical JSON exceeds limit" };
  }
  if (!isRecord(value)) {
    return { ok: false, code: "E_SCHEMA_WRONG_TYPE", detail: "envelope must be object" };
  }
  const inlinePath = findInlineMedia(value);
  if (inlinePath !== undefined) {
    return { ok: false, code: "E_SCHEMA_INLINE_BASE64", detail: inlinePath };
  }
  const metadataNumberPath = findUnsafeMetadataNumber(value);
  if (metadataNumberPath !== undefined) {
    return { ok: false, code: "E_SCHEMA_WRONG_TYPE", detail: metadataNumberPath };
  }
  const eventType = value.type;
  if (eventType === undefined) {
    return { ok: false, code: "E_SCHEMA_MISSING_REQUIRED", detail: "type is required" };
  }
  if (typeof eventType !== "string") {
    return { ok: false, code: "E_SCHEMA_WRONG_TYPE", detail: "type must be string" };
  }
  if (!EVENT_TYPES.includes(eventType as EventType)) {
    return { ok: false, code: "E_SCHEMA_UNKNOWN_EVENT", detail: eventType };
  }
  const valid = validators[eventType as EventType](value);
  if (!valid) {
    return classifyAjvError(validators[eventType as EventType].errors ?? []);
  }
  return { ok: true, code: "OK", canonicalJson };
}

function classifyAjvError(errors: Array<{ keyword: string; instancePath: string; schemaPath: string; message?: string }>): ValidationResult {
  const error = errors[0];
  if (error === undefined) {
    return { ok: false, code: "E_SCHEMA_WRONG_TYPE", detail: "unknown validation failure" };
  }
  if (error.keyword === "required") {
    return { ok: false, code: "E_SCHEMA_MISSING_REQUIRED", detail: error.message };
  }
  if (error.keyword === "additionalProperties") {
    return { ok: false, code: "E_SCHEMA_UNKNOWN_FIELD", detail: error.message };
  }
  if (isIdentifierError(error.keyword, error.instancePath, error.schemaPath)) {
    return { ok: false, code: "E_SCHEMA_INVALID_ID", detail: error.message };
  }
  return { ok: false, code: "E_SCHEMA_WRONG_TYPE", detail: error.message };
}

function isIdentifierError(keyword: string, instancePath: string, schemaPath: string): boolean {
  if (keyword === "if" || keyword === "then") {
    return true;
  }
  const path = `${instancePath} ${schemaPath}`;
  return (
    keyword === "pattern" &&
    (path.includes("Id") ||
      path.includes("id") ||
      path.includes("occurredAt") ||
      path.includes("expiresAt") ||
      path.includes("deadline"))
  );
}

function findInlineMedia(value: Record<string, unknown>): string | undefined {
  const media = value.media;
  if (!Array.isArray(media)) {
    return undefined;
  }
  for (let index = 0; index < media.length; index += 1) {
    const item = media[index];
    if (!isRecord(item)) {
      continue;
    }
    for (const [key, child] of Object.entries(item)) {
      const childPath = `$.media[${index}].${key}`;
      if (inlineKeys.has(key)) {
        return childPath;
      }
      if (typeof child === "string" && child.toLowerCase().startsWith("data:")) {
        return childPath;
      }
    }
  }
  return undefined;
}

function findUnsafeMetadataNumber(value: Record<string, unknown>): string | undefined {
  const payload = value.payload;
  if (!isRecord(payload)) {
    return undefined;
  }
  const metadata = payload.metadata;
  if (!isRecord(metadata)) {
    return undefined;
  }
  for (const [key, child] of Object.entries(metadata)) {
    if (typeof child === "number" && (!Number.isInteger(child) || child < minJsSafeInteger || child > maxJsSafeInteger)) {
      return `$.payload.metadata.${key}`;
    }
  }
  return undefined;
}

function stableStringify(value: unknown): string {
  if (typeof value === "number" && !Number.isFinite(value)) {
    throw new TypeError("value is not JSON serializable");
  }
  if (value === null || typeof value !== "object") {
    const rendered = JSON.stringify(value);
    if (rendered === undefined) {
      throw new TypeError("value is not JSON serializable");
    }
    return rendered;
  }
  if (Array.isArray(value)) {
    return `[${value.map((item) => stableStringify(item)).join(",")}]`;
  }
  const entries = Object.entries(value as Record<string, unknown>).sort(([left], [right]) => compareCodePoints(left, right));
  return `{${entries.map(([key, child]) => `${JSON.stringify(key)}:${stableStringify(child)}`).join(",")}}`;
}

function compareCodePoints(left: string, right: string): number {
  const leftPoints = Array.from(left);
  const rightPoints = Array.from(right);
  const length = Math.min(leftPoints.length, rightPoints.length);
  for (let index = 0; index < length; index += 1) {
    const delta = (leftPoints[index]?.codePointAt(0) ?? 0) - (rightPoints[index]?.codePointAt(0) ?? 0);
    if (delta !== 0) {
      return delta;
    }
  }
  return leftPoints.length - rightPoints.length;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
