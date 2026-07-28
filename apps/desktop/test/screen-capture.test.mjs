import assert from "node:assert/strict";
import test from "node:test";

import {
  CaptureGrantStore,
  fitWithinLongEdge,
  validateFullFrameCaptureRequest,
} from "../dist-electron/screen-capture.js";

const UUIDS = [
  "11111111-1111-4111-8111-111111111111",
  "22222222-2222-4222-8222-222222222222",
  "33333333-3333-4333-8333-333333333333",
  "44444444-4444-4444-8444-444444444444",
  "55555555-5555-4555-8555-555555555555",
  "66666666-6666-4666-8666-666666666666",
  "77777777-7777-4777-8777-777777777777",
  "88888888-8888-4888-8888-888888888888",
];

function source(overrides = {}) {
  return {
    sourceId: "screen:1:0",
    name: "Screen 1",
    kind: "screen",
    previewDataUrl: "data:image/png;base64,iVBORw0KGgo=",
    previewWidth: 320,
    previewHeight: 180,
    ...overrides,
  };
}

test("capture grants expose opaque tokens, expire and are single-use", () => {
  let now = 1_000;
  let uuidIndex = 0;
  const store = new CaptureGrantStore({
    clock: () => now,
    uuid: () => UUIDS[uuidIndex++],
    ttlMilliseconds: 2_000,
  });
  const listing = store.issue([source()]);
  assert.equal(listing.grantSessionId, UUIDS[0]);
  assert.equal(listing.sources[0].sourceToken, UUIDS[1]);
  assert.equal(listing.persistence, false);
  assert.equal("sourceId" in listing.sources[0], false);
  assert.doesNotMatch(JSON.stringify(listing), /screen:1:0/);

  const selected = store.consume(UUIDS[0], UUIDS[1]);
  assert.equal(selected.sourceId, "screen:1:0");
  assert.throws(
    () => store.consume(UUIDS[0], UUIDS[1]),
    /E_DESKTOP_CAPTURE_GRANT/,
  );

  const expiring = store.issue([source({ sourceId: "window:7:0" })]);
  now = expiring.expiresAtUnixMilliseconds;
  assert.throws(
    () => store.consume(expiring.grantSessionId, expiring.sources[0].sourceToken),
    /E_DESKTOP_CAPTURE_GRANT/,
  );
});

test("a new picker result revokes the previous transient source list", () => {
  let uuidIndex = 0;
  const store = new CaptureGrantStore({
    uuid: () => UUIDS[uuidIndex++],
  });
  const oldListing = store.issue([source()]);
  const currentListing = store.issue([
    source({ sourceId: "window:9:0", name: "Minecraft" }),
  ]);
  assert.throws(
    () => store.consume(
      oldListing.grantSessionId,
      oldListing.sources[0].sourceToken,
    ),
    /E_DESKTOP_CAPTURE_GRANT/,
  );
  assert.equal(
    store.consume(
      currentListing.grantSessionId,
      currentListing.sources[0].sourceToken,
    ).sourceId,
    "window:9:0",
  );
});

test("full-frame request accepts only bounded explicit fields and presets", () => {
  const request = validateFullFrameCaptureRequest({
    sessionId: UUIDS[2],
    grantSessionId: UUIDS[0],
    sourceToken: UUIDS[1],
    maxSide: 960,
    label: "Cửa sổ Minecraft",
    analyzeOcr: true,
    analyzeVision: true,
    visionQuestion: "Nhân vật đang ở đâu?",
  });
  assert.deepEqual(request, {
    sessionId: UUIDS[2],
    grantSessionId: UUIDS[0],
    sourceToken: UUIDS[1],
    maxSide: 960,
    label: "Cửa sổ Minecraft",
    analyzeOcr: true,
    analyzeVision: true,
    visionQuestion: "Nhân vật đang ở đâu?",
  });
  assert.throws(
    () => validateFullFrameCaptureRequest({ ...request, maxSide: 1920 }),
    /maxSide/,
  );
  assert.throws(
    () => validateFullFrameCaptureRequest({ ...request, sessionId: "not-a-uuid" }),
    /chat session/,
  );
  assert.throws(
    () => validateFullFrameCaptureRequest({
      ...request,
      analyzeVision: false,
    }),
    /vision question requires/,
  );
  assert.throws(
    () => validateFullFrameCaptureRequest({ ...request, sourceId: "screen:1:0" }),
    /fields are invalid/,
  );
});

test("full-frame resize preserves composition and never enlarges", () => {
  assert.deepEqual(fitWithinLongEdge(3_840, 2_160, 960), {
    width: 960,
    height: 540,
  });
  assert.deepEqual(fitWithinLongEdge(1_080, 1_920, 640), {
    width: 360,
    height: 640,
  });
  assert.deepEqual(fitWithinLongEdge(640, 360, 960), {
    width: 640,
    height: 360,
  });
});
