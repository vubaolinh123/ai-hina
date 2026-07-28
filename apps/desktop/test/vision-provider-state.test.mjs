import assert from "node:assert/strict";
import { createRequire } from "node:module";
import test from "node:test";

const require = createRequire(import.meta.url);
const {
  VISION_PROVIDER_STATE_MAX_BYTES,
  parseVisionProviderState,
  serializeVisionProviderState,
} = require("../dist-electron/vision-provider-state.js");

test("vision provider state retains only encrypted key material", () => {
  const raw = serializeVisionProviderState({
    schemaVersion: 1,
    provider: "ollama_cloud",
    model: "gemini-3-flash-preview:cloud",
    encryptedApiKey: Buffer.from("ciphertext-only").toString("base64"),
  });
  const parsed = parseVisionProviderState(raw);
  assert.deepEqual(parsed, {
    schemaVersion: 1,
    provider: "ollama_cloud",
    model: "gemini-3-flash-preview:cloud",
    encryptedApiKey: Buffer.from("ciphertext-only").toString("base64"),
  });
  assert.doesNotMatch(raw, /owner-api-key/);

  const localWithRememberedCloudKey = parseVisionProviderState(
    serializeVisionProviderState({
      schemaVersion: 1,
      provider: "ollama_local",
      model: "qwen3.5:4b",
      encryptedApiKey: Buffer.from("remembered-cloud-cipher").toString("base64"),
    }),
  );
  assert.equal(
    localWithRememberedCloudKey?.encryptedApiKey,
    Buffer.from("remembered-cloud-cipher").toString("base64"),
  );
});

test("vision provider state fails closed on extra fields, plaintext or oversize", () => {
  assert.equal(parseVisionProviderState(JSON.stringify({
    schemaVersion: 1,
    provider: "ollama_cloud",
    model: "vision:cloud",
    encryptedApiKey: null,
  })), null);
  assert.equal(parseVisionProviderState(JSON.stringify({
    schemaVersion: 1,
    provider: "disabled",
    model: null,
    encryptedApiKey: Buffer.from("orphan-cipher").toString("base64"),
  })), null);
  assert.equal(parseVisionProviderState(JSON.stringify({
    schemaVersion: 1,
    provider: "ollama_cloud",
    model: "vision:cloud",
    encryptedApiKey: "owner-plaintext-key",
  })), null);
  assert.equal(parseVisionProviderState(JSON.stringify({
    schemaVersion: 1,
    provider: "ollama_cloud",
    model: "vision:cloud",
    encryptedApiKey: Buffer.from("cipher").toString("base64"),
    apiKey: "owner-plaintext-key",
  })), null);
  assert.equal(
    parseVisionProviderState("x".repeat(VISION_PROVIDER_STATE_MAX_BYTES + 1)),
    null,
  );
});
