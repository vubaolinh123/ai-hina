import Ajv2020 from "ajv/dist/2020";

import catalog from "../catalog.v1.json";
import compatibilityPolicy from "../compatibility-policy.v1.json";
import {
  CATALOG_DIGEST,
  CATALOG_VERSION,
  EVENT_SCHEMA_MODULES,
  EVENT_SCHEMA_FILES,
  EVENT_TYPES,
  HINA_CONTRACT_ECHO_V1,
  MAX_JSON_NESTING_DEPTH,
  MAX_JSON_ENVELOPE_BYTES,
  SUPPORT_SCHEMA_MODULES,
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
  MAX_JSON_NESTING_DEPTH,
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
const maxIntegerTokenDigits = 16;

const ajv = new Ajv2020({
  allErrors: true,
  coerceTypes: false,
  removeAdditional: false,
  strict: true,
  useDefaults: false,
});

for (const schema of SUPPORT_SCHEMA_MODULES) {
  ajv.addSchema(schema);
}
const validators = Object.fromEntries(
  EVENT_TYPES.map((eventType) => [eventType, ajv.compile(EVENT_SCHEMA_MODULES[eventType])]),
) as Record<EventType, ReturnType<typeof ajv.compile>>;

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
    const scanError = scanJsonText(text);
    if (scanError !== undefined) {
      return { ok: false, code: "E_SCHEMA_WRONG_TYPE", detail: scanError };
    }
    return validateEnvelope(JSON.parse(text));
  } catch (error) {
    return { ok: false, code: "E_SCHEMA_WRONG_TYPE", detail: String(error) };
  }
}

export function validateEnvelope(value: unknown): ValidationResult {
  let canonicalJson: string;
  try {
    const semanticError = findStructuralStringOrDepthError(value);
    if (semanticError !== undefined) {
      return { ok: false, code: "E_SCHEMA_WRONG_TYPE", detail: semanticError };
    }
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
  if (keyword === "if" || keyword === "then" || schemaPath.includes("/allOf/")) {
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
  const structuralError = findStructuralStringOrDepthError(value);
  if (structuralError !== undefined) {
    throw new TypeError(structuralError);
  }
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

function findStructuralStringOrDepthError(value: unknown): string | undefined {
  const stack: Array<{ value: unknown; depth: number }> = [{ value, depth: 0 }];
  while (stack.length > 0) {
    const item = stack.pop();
    if (item === undefined) {
      continue;
    }
    if (item.depth > MAX_JSON_NESTING_DEPTH) {
      return `JSON nesting exceeds ${MAX_JSON_NESTING_DEPTH}`;
    }
    if (typeof item.value === "string") {
      if (hasUnpairedSurrogate(item.value)) {
        return "string contains an unpaired UTF-16 surrogate";
      }
      continue;
    }
    if (item.value === null || typeof item.value !== "object") {
      continue;
    }
    if (Array.isArray(item.value)) {
      for (const child of item.value) {
        stack.push({ value: child, depth: item.depth + 1 });
      }
      continue;
    }
    for (const [key, child] of Object.entries(item.value as Record<string, unknown>)) {
      if (hasUnpairedSurrogate(key)) {
        return "object member name contains an unpaired UTF-16 surrogate";
      }
      stack.push({ value: child, depth: item.depth + 1 });
    }
  }
  return undefined;
}

function hasUnpairedSurrogate(value: string): boolean {
  for (let index = 0; index < value.length; index += 1) {
    const code = value.charCodeAt(index);
    if (code >= 0xd800 && code <= 0xdbff) {
      const next = value.charCodeAt(index + 1);
      if (!(next >= 0xdc00 && next <= 0xdfff)) {
        return true;
      }
      index += 1;
    } else if (code >= 0xdc00 && code <= 0xdfff) {
      return true;
    }
  }
  return false;
}

function scanJsonText(text: string): string | undefined {
  let index = 0;

  function skipWhitespace(): void {
    while (index < text.length && /[\t\n\r ]/u.test(text[index] ?? "")) {
      index += 1;
    }
  }

  function parseValue(depth: number): string | undefined {
    if (depth > MAX_JSON_NESTING_DEPTH) {
      return `JSON nesting exceeds ${MAX_JSON_NESTING_DEPTH}`;
    }
    skipWhitespace();
    const char = text[index];
    if (char === "{") {
      return parseObject(depth);
    }
    if (char === "[") {
      return parseArray(depth);
    }
    if (char === '"') {
      const parsed = parseString();
      return typeof parsed === "string" ? undefined : parsed.error;
    }
    if (char === "-" || (char !== undefined && char >= "0" && char <= "9")) {
      return parseNumber();
    }
    for (const literal of ["true", "false", "null"]) {
      if (text.startsWith(literal, index)) {
        index += literal.length;
        return undefined;
      }
    }
    return "malformed JSON";
  }

  function parseObject(depth: number): string | undefined {
    index += 1;
    const keys = new Set<string>();
    skipWhitespace();
    if (text[index] === "}") {
      index += 1;
      return undefined;
    }
    while (index < text.length) {
      skipWhitespace();
      const key = parseString();
      if (typeof key !== "string") {
        return key.error;
      }
      if (hasUnpairedSurrogate(key)) {
        return "object member name contains an unpaired UTF-16 surrogate";
      }
      if (keys.has(key)) {
        return `duplicate JSON object member: ${key}`;
      }
      keys.add(key);
      skipWhitespace();
      if (text[index] !== ":") {
        return "malformed JSON";
      }
      index += 1;
      const valueError = parseValue(depth + 1);
      if (valueError !== undefined) {
        return valueError;
      }
      skipWhitespace();
      if (text[index] === "}") {
        index += 1;
        return undefined;
      }
      if (text[index] !== ",") {
        return "malformed JSON";
      }
      index += 1;
    }
    return "malformed JSON";
  }

  function parseArray(depth: number): string | undefined {
    index += 1;
    skipWhitespace();
    if (text[index] === "]") {
      index += 1;
      return undefined;
    }
    while (index < text.length) {
      const valueError = parseValue(depth + 1);
      if (valueError !== undefined) {
        return valueError;
      }
      skipWhitespace();
      if (text[index] === "]") {
        index += 1;
        return undefined;
      }
      if (text[index] !== ",") {
        return "malformed JSON";
      }
      index += 1;
    }
    return "malformed JSON";
  }

  function parseString(): string | { error: string } {
    const start = index;
    if (text[index] !== '"') {
      return { error: "malformed JSON" };
    }
    index += 1;
    while (index < text.length) {
      const char = text[index];
      if (char === '"') {
        index += 1;
        const literal = text.slice(start, index);
        try {
          return JSON.parse(literal) as string;
        } catch {
          return { error: "malformed JSON" };
        }
      }
      if (char === "\\") {
        index += 1;
        if (text[index] === "u") {
          const hex = text.slice(index + 1, index + 5);
          if (!/^[0-9a-fA-F]{4}$/u.test(hex)) {
            return { error: "malformed JSON" };
          }
          index += 5;
        } else if ('"\\/bfnrt'.includes(text[index] ?? "")) {
          index += 1;
        } else {
          return { error: "malformed JSON" };
        }
      } else {
        const code = char?.charCodeAt(0) ?? 0;
        if (code <= 0x1f) {
          return { error: "malformed JSON" };
        }
        index += 1;
      }
    }
    return { error: "malformed JSON" };
  }

  function parseNumber(): string | undefined {
    const start = index;
    if (text[index] === "-") {
      index += 1;
    }
    if (text[index] === "0") {
      index += 1;
    } else if (text[index] !== undefined && text[index] >= "1" && text[index] <= "9") {
      while (text[index] !== undefined && text[index] >= "0" && text[index] <= "9") {
        index += 1;
      }
    } else {
      return "malformed JSON";
    }
    const integerDigits = text.slice(start, index).replace("-", "").replace(/^0+$/u, "0");
    if (!text.slice(start, index).includes(".") && integerDigits.length > maxIntegerTokenDigits) {
      return "integer token exceeds JavaScript-safe boundary";
    }
    if (text[index] === ".") {
      index += 1;
      if (!(text[index] !== undefined && text[index] >= "0" && text[index] <= "9")) {
        return "malformed JSON";
      }
      while (text[index] !== undefined && text[index] >= "0" && text[index] <= "9") {
        index += 1;
      }
    }
    if (text[index] === "e" || text[index] === "E") {
      index += 1;
      if (text[index] === "+" || text[index] === "-") {
        index += 1;
      }
      if (!(text[index] !== undefined && text[index] >= "0" && text[index] <= "9")) {
        return "malformed JSON";
      }
      while (text[index] !== undefined && text[index] >= "0" && text[index] <= "9") {
        index += 1;
      }
    }
    return undefined;
  }

  const error = parseValue(1);
  if (error !== undefined) {
    return error;
  }
  skipWhitespace();
  return index === text.length ? undefined : "malformed JSON";
}
