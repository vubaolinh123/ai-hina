import assert from "node:assert/strict";
import { readdirSync, readFileSync } from "node:fs";
import { test } from "node:test";

import {
  CATALOG_VERSION,
  EVENT_TYPES,
  canonicalizeEnvelope,
  compatibilityPolicy,
  validateEnvelope,
  validateEnvelopeBytes,
} from "../dist/index.js";

const fixture = (name) => JSON.parse(readFileSync(new URL(`../fixtures/golden/${name}`, import.meta.url), "utf8"));
const negativeManifest = () => JSON.parse(readFileSync(new URL("../fixtures/negative/manifest.v1.json", import.meta.url), "utf8"));
const MIN_JS_SAFE_INTEGER = -9_007_199_254_740_991;
const MAX_JS_SAFE_INTEGER = 9_007_199_254_740_991;

test("golden fixtures pass in Ajv strict runtime", () => {
  for (const name of ["global.echo.json", "session.echo.json", "turn.media.echo.json"]) {
    const result = validateEnvelopeBytes(readFileSync(new URL(`../fixtures/golden/${name}`, import.meta.url)));
    assert.equal(result.code, "OK", result.detail);
    assert.equal(result.ok, true);
  }
});

test("catalog constants expose only registered v1 event", () => {
  assert.equal(CATALOG_VERSION, "1.0");
  assert.deepEqual(EVENT_TYPES, ["hina.contract.echo.v1"]);
});

test("negative manifest fixtures fail with exact stable codes", () => {
  const manifest = negativeManifest();
  const expected = Object.fromEntries(manifest.fixtures.map((item) => [item.path, item.expectedCode]));
  const actualFiles = new Set(
    readdirSync(new URL("../fixtures/negative/", import.meta.url)).filter((name) => name.endsWith(".json") && name !== "manifest.v1.json"),
  );
  assert.deepEqual(actualFiles, new Set(Object.keys(expected)));
  for (const [name, expectedCode] of Object.entries(expected).sort()) {
    const result = validateEnvelopeBytes(readFileSync(new URL(`../fixtures/negative/${name}`, import.meta.url)));
    assert.equal(result.code, expectedCode, `${name}: ${result.detail ?? ""}`);
    assert.equal(result.ok, false);
  }
});

test("unknown event, fields, identifiers, and inline media fail closed", () => {
  const base = fixture("turn.media.echo.json");
  assert.equal(validateEnvelope({ ...base, type: "hina.contract.unknown.v1" }).code, "E_SCHEMA_UNKNOWN_EVENT");
  assert.equal(validateEnvelope({ ...base, unexpected: true }).code, "E_SCHEMA_UNKNOWN_FIELD");
  assert.equal(validateEnvelope({ ...base, causationId: base.causationId.toUpperCase() }).code, "E_SCHEMA_INVALID_ID");
  for (const [key, value] of [
    ["base64", "AAAA"],
    ["bytes", [1, 2, 3]],
    ["dataUri", "data:audio/wav;base64,AAAA"],
    ["path", "C:/tmp/audio.wav"],
    ["raw", [0, 1, 2]],
    ["url", "https://example.invalid/audio.wav"],
  ]) {
    assert.equal(validateEnvelope({ ...base, media: [{ ...base.media[0], [key]: value }] }).code, "E_SCHEMA_INLINE_BASE64");
  }
  assert.equal(
    validateEnvelope({
      ...base,
      payload: { ...base.payload, metadata: { url: "ordinary text, not a media locator" } },
    }).code,
    "OK",
  );
  assert.equal(validateEnvelope({ ...base, payload: { ...base.payload, metadata: { nan: Number.NaN } } }).code, "E_SCHEMA_WRONG_TYPE");
});

test("scope relationship failures use E_SCHEMA_INVALID_ID for every scope case", () => {
  const base = fixture("turn.media.echo.json");
  const cases = [
    { ...base, scope: "global", sessionId: base.sessionId },
    { ...base, scope: "global", sessionId: null, turnId: base.turnId },
    { ...base, scope: "session", sessionId: null, turnId: null },
    { ...base, scope: "session", turnId: base.turnId },
    { ...base, scope: "turn", sessionId: null },
    { ...base, scope: "turn", turnId: null },
    { ...base, scope: "turn", sessionId: null, turnId: null },
  ];
  for (const item of cases) {
    assert.equal(validateEnvelope(item).code, "E_SCHEMA_INVALID_ID");
  }
});

test("timestamp calendar validity rejects impossible UTC dates and times", () => {
  const base = fixture("global.echo.json");
  for (const field of ["occurredAt", "expiresAt", "deadline"]) {
    assert.equal(validateEnvelope({ ...base, [field]: "2024-02-29T23:59:59.123456Z" }).code, "OK");
    for (const timestamp of [
      "2026-00-01T00:00:00Z",
      "2026-13-01T00:00:00Z",
      "2026-02-29T00:00:00Z",
      "2024-02-30T00:00:00Z",
      "2026-04-31T00:00:00Z",
      "2026-01-01T24:00:00Z",
      "2026-01-01T00:60:00Z",
      "2026-01-01T00:00:60Z",
    ]) {
      assert.equal(validateEnvelope({ ...base, [field]: timestamp }).code, "E_SCHEMA_INVALID_ID", `${field} ${timestamp}`);
    }
  }
});

test("bounded boundary tokens reject controls and unsafe formatting", () => {
  const base = fixture("global.echo.json");
  for (const [field, value] of [
    ["source", "contracts\u0085test"],
    ["source", "contracts\u202etest"],
    ["idempotencyKey", "idem\u200b1"],
    ["streamId", "stream\u20661"],
  ]) {
    assert.notEqual(validateEnvelope({ ...base, [field]: value }).code, "OK", field);
  }
});

test("metadata numeric values are JavaScript-safe integers only", () => {
  const base = fixture("global.echo.json");
  for (const number of [MIN_JS_SAFE_INTEGER, 0, MAX_JS_SAFE_INTEGER]) {
    const result = validateEnvelope({ ...base, payload: { ...base.payload, metadata: { number } } });
    assert.equal(result.code, "OK", result.detail);
  }
  for (const number of [1.25, MAX_JS_SAFE_INTEGER + 1, MIN_JS_SAFE_INTEGER - 1]) {
    const result = validateEnvelope({ ...base, payload: { ...base.payload, metadata: { number } } });
    assert.equal(result.code, "E_SCHEMA_WRONG_TYPE", result.detail);
  }
  const rawFloat = Buffer.from(
    JSON.stringify({ ...base, payload: { ...base.payload, metadata: { number: 0 } } }).replace('"number":0', '"number":1.0'),
    "utf8",
  );
  const rawFloatResult = validateEnvelopeBytes(rawFloat);
  assert.equal(rawFloatResult.code, "OK", rawFloatResult.detail);
  assert.equal(JSON.parse(rawFloatResult.canonicalJson).payload.metadata.number, 1);
  const rawExponent = Buffer.from(
    JSON.stringify({ ...base, payload: { ...base.payload, metadata: { number: 0 } } }).replace('"number":0', '"number":1e2'),
    "utf8",
  );
  const rawExponentResult = validateEnvelopeBytes(rawExponent);
  assert.equal(rawExponentResult.code, "OK", rawExponentResult.detail);
  assert.equal(JSON.parse(rawExponentResult.canonicalJson).payload.metadata.number, 100);
  const rawSequenceFloat = Buffer.from(JSON.stringify({ ...base, sequence: 0 }).replace('"sequence":0', '"sequence":1.0'), "utf8");
  const rawSequenceFloatResult = validateEnvelopeBytes(rawSequenceFloat);
  assert.equal(rawSequenceFloatResult.code, "OK", rawSequenceFloatResult.detail);
  assert.equal(JSON.parse(rawSequenceFloatResult.canonicalJson).sequence, 1);
  for (const raw of [
    Buffer.from(JSON.stringify({ ...base, payload: { ...base.payload, metadata: { number: 0 } } }).replace('"number":0', '"number":1.25'), "utf8"),
    Buffer.from(
      JSON.stringify({ ...base, payload: { ...base.payload, metadata: { number: 0 } } }).replace(
        '"number":0',
        `"number":${MAX_JS_SAFE_INTEGER + 1}`,
      ),
      "utf8",
    ),
    Buffer.from(JSON.stringify({ ...base, sequence: 0 }).replace('"sequence":0', '"sequence":1.25'), "utf8"),
    Buffer.from(JSON.stringify({ ...base, sequence: 0 }).replace('"sequence":0', `"sequence":${MAX_JS_SAFE_INTEGER + 1}`), "utf8"),
  ]) {
    assert.equal(validateEnvelopeBytes(raw).code, "E_SCHEMA_WRONG_TYPE");
  }
});

test("Unicode canonical roundtrip preserves exact content", () => {
  const base = fixture("global.echo.json");
  const message = "Tiếng Việt NFD: Tiêng Việt; emoji 😀; RTL مرحبا";
  const mutated = {
    ...base,
    payload: {
      ...base.payload,
      message,
      metadata: {
        ascii: "first",
        "điểm": "Vietnamese key",
        "𐐷": "astral key",
        "😀": "emoji key",
      },
    },
  };
  const result = validateEnvelope(mutated);
  assert.equal(result.code, "OK", result.detail);
  assert.equal(JSON.parse(result.canonicalJson).payload.message, message);
  assert.equal(canonicalizeEnvelope(JSON.parse(result.canonicalJson)), result.canonicalJson);
  assert.match(result.canonicalJson, /"ascii":.*"điểm":.*"𐐷":.*"😀":/u);
});

test("raw and canonical oversize envelopes are rejected", () => {
  const base = fixture("global.echo.json");
  assert.equal(validateEnvelopeBytes(Buffer.alloc(1_048_577, 0x20)).code, "E_SCHEMA_OVERSIZE");
  assert.equal(validateEnvelopeBytes(Buffer.from([0xff])).code, "E_SCHEMA_WRONG_TYPE");
  const oversized = { ...base, payload: { ...base.payload, message: "a".repeat(1_048_576) } };
  assert.equal(validateEnvelope(oversized).code, "E_SCHEMA_OVERSIZE");
});

test("raw parser hazards fail closed without throwing", () => {
  const base = fixture("global.echo.json");
  const rawSequence = (token) => Buffer.from(JSON.stringify({ ...base, sequence: 0 }).replace('"sequence":0', `"sequence":${token}`), "utf8");
  const rawMessage = (token) =>
    Buffer.from(
      JSON.stringify({ ...base, payload: { ...base.payload, message: "placeholder" } }).replace('"message":"placeholder"', `"message":${token}`),
      "utf8",
    );
  for (const [label, raw] of [
    ["huge integer", rawSequence("1".repeat(5000))],
    ["excessive nesting", Buffer.from(`${"[".repeat(129)}0${"]".repeat(129)}`)],
    ["invalid utf8", Buffer.from([0xff])],
    ["malformed json", Buffer.from('{"type":')],
    ["escaped lone high surrogate", rawMessage('"\\ud800"')],
    ["escaped lone low surrogate", rawMessage('"\\ude00"')],
  ]) {
    assert.equal(validateEnvelopeBytes(raw).code, "E_SCHEMA_WRONG_TYPE", label);
  }
  assert.equal(validateEnvelope({ ...base, payload: { ...base.payload, message: "\ud800" } }).code, "E_SCHEMA_WRONG_TYPE");
  assert.equal(
    validateEnvelope({ ...base, payload: { ...base.payload, metadata: { ["\ud800"]: "bad" } } }).code,
    "E_SCHEMA_WRONG_TYPE",
  );
  const rawBadKey = Buffer.from(
    JSON.stringify({ ...base, payload: { ...base.payload, metadata: {} } }).replace('"metadata":{}', '"metadata":{"\\ud800":"bad"}'),
    "utf8",
  );
  assert.equal(validateEnvelopeBytes(rawBadKey).code, "E_SCHEMA_WRONG_TYPE");
  const astralKey = validateEnvelope({ ...base, payload: { ...base.payload, metadata: { ["😀"]: "valid" } } });
  assert.equal(astralKey.code, "OK", astralKey.detail);
  const validPair = validateEnvelopeBytes(rawMessage('"\\ud83d\\ude00"'));
  assert.equal(validPair.code, "OK", validPair.detail);
  assert.equal(JSON.parse(validPair.canonicalJson).payload.message, "😀");
});

test("compatibility policy explicitly documents initial n-1 disposition", () => {
  assert.equal(compatibilityPolicy.catalogVersion, "1.0");
  assert.equal(compatibilityPolicy.disposition, "initial_release");
  assert.deepEqual(compatibilityPolicy.supportedPreviousMajorVersions, []);
});

test("benchmark p50 p95 max remains inside M01-S1 budget", () => {
  const base = fixture("turn.media.echo.json");
  for (let index = 0; index < 25; index += 1) {
    validateEnvelope(base);
  }
  const durations = [];
  for (let index = 0; index < 250; index += 1) {
    const started = performance.now();
    const result = validateEnvelope(base);
    durations.push(performance.now() - started);
    assert.equal(result.code, "OK", result.detail);
  }
  durations.sort((left, right) => left - right);
  const metrics = {
    p50: durations[Math.floor(durations.length * 0.5)],
    p95: durations[Math.floor(durations.length * 0.95)],
    max: durations[durations.length - 1],
  };
  assert.ok(metrics.p95 <= 5, JSON.stringify(metrics));
});
