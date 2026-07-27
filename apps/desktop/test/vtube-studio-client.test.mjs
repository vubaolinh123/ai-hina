import assert from "node:assert/strict";
import { createRequire } from "node:module";
import test from "node:test";

const require = createRequire(import.meta.url);
const {
  VTubeStudioClient,
  VTS_TOKEN_STATE_MAX_BYTES,
  parseVTubeStudioTokenState,
  serializeVTubeStudioTokenState,
} = require("../dist-electron/vtube-studio-client.js");

class FakeWebSocket {
  readyState = 0;
  listeners = new Map();
  requests = [];

  constructor({ currentModelFrame = "json" } = {}) {
    this.currentModelFrame = currentModelFrame;
    queueMicrotask(() => {
      this.readyState = 1;
      this.emit("open", {});
    });
  }

  addEventListener(type, listener) {
    const existing = this.listeners.get(type) ?? [];
    existing.push(listener);
    this.listeners.set(type, existing);
  }

  send(raw) {
    const request = JSON.parse(raw);
    this.requests.push(request);
    const data = {
      AuthenticationTokenRequest: {
        authenticationToken: "owner-secret-token",
      },
      AuthenticationRequest: {
        authenticated: true,
        reason: "Authenticated",
      },
      CurrentModelRequest: {
        modelLoaded: true,
        modelName: "Hiyori",
        modelID: "model-hiyori",
        vtsModelName: "hiyori.model3.json",
      },
      HotkeysInCurrentModelRequest: {
        availableHotkeys: [
          { hotkeyID: "smile-id", name: "Smile", type: "ExpressionActivation" },
          { hotkeyID: "wave-id", name: "Wave", type: "TriggerAnimation" },
        ],
      },
      HotkeyTriggerRequest: {},
      MoveModelRequest: {},
    }[request.messageType];
    queueMicrotask(() => {
      if (
        request.messageType === "CurrentModelRequest"
        && this.currentModelFrame !== "json"
      ) {
        this.emit("message", {
          data: this.currentModelFrame === "empty" ? "" : "{not-json",
        });
        return;
      }
      this.emit("message", {
        data: JSON.stringify({
          apiName: "VTubeStudioPublicAPI",
          apiVersion: "1.0",
          requestID: request.requestID,
          messageType: request.messageType.replace("Request", "Response"),
          data,
        }),
      });
    });
  }

  close() {
    this.readyState = 3;
    this.emit("close", {});
  }

  emit(type, event) {
    for (const listener of this.listeners.get(type) ?? []) listener(event);
  }
}

function tokenStore(initial = null) {
  let value = initial;
  return {
    saved: [],
    cleared: 0,
    async load() {
      return value;
    },
    async save(token) {
      value = token;
      this.saved.push(token);
    },
    async clear() {
      value = null;
      this.cleared += 1;
    },
  };
}

test("token state is bounded, strict and deterministic", () => {
  const raw = serializeVTubeStudioTokenState("fixed-token");
  assert.deepEqual(JSON.parse(raw), {
    schemaVersion: "1.0",
    authenticationToken: "fixed-token",
  });
  assert.equal(parseVTubeStudioTokenState(raw), "fixed-token");
  for (const invalid of [
    "",
    "not-json",
    "[]",
    '{"schemaVersion":"2.0","authenticationToken":"x"}',
    '{"schemaVersion":"1.0","authenticationToken":"x","extra":true}',
    " ".repeat(VTS_TOKEN_STATE_MAX_BYTES + 1),
  ]) {
    assert.equal(parseVTubeStudioTokenState(invalid), null);
  }
});

test("connect authenticates, lists the selected model and never exposes token", async () => {
  const store = tokenStore("owner-secret-token");
  const sockets = [];
  const client = new VTubeStudioClient(store, (url) => {
    assert.equal(url, "ws://127.0.0.1:8001");
    const socket = new FakeWebSocket();
    sockets.push(socket);
    return socket;
  });

  const status = await client.connect(false);
  assert.equal(status.state, "connected");
  assert.equal(status.authenticated, true);
  assert.equal(status.model.name, "Hiyori");
  assert.deepEqual(
    status.hotkeys.map((hotkey) => hotkey.name),
    ["Smile", "Wave"],
  );
  assert.equal(status.hiyoriBundled, false);
  assert.equal(status.offlineFallback, "hina-vrm-widget");
  assert.doesNotMatch(JSON.stringify(status), /owner-secret-token/);
  assert.equal(
    sockets[0].requests.find(
      (request) => request.messageType === "AuthenticationRequest",
    ).data.authenticationToken,
    "owner-secret-token",
  );
});

test("permission, hotkeys and movement use fixed bounded operations", async () => {
  const store = tokenStore();
  const sockets = [];
  const client = new VTubeStudioClient(store, () => {
    const socket = new FakeWebSocket();
    sockets.push(socket);
    return socket;
  });

  const status = await client.connect(true);
  assert.equal(status.state, "connected");
  assert.deepEqual(store.saved, ["owner-secret-token"]);
  await client.triggerHotkey("smile-id");
  await assert.rejects(
    client.triggerHotkey("not-from-current-model"),
    /E_VTS_HOTKEY/,
  );
  await client.moveModel("chat");
  await assert.rejects(client.moveModel("arbitrary"), /E_VTS_MOVE/);

  const move = sockets[0].requests.find(
    (request) => request.messageType === "MoveModelRequest",
  );
  assert.deepEqual(Object.keys(move.data).sort(), [
    "positionX",
    "positionY",
    "rotation",
    "size",
    "timeInSeconds",
    "valuesAreRelativeToModel",
  ]);
  assert.equal(move.data.valuesAreRelativeToModel, false);
});

test("status stays honest when permission has not been requested", async () => {
  const client = new VTubeStudioClient(tokenStore(), () => new FakeWebSocket());
  const status = await client.connect(false);
  assert.equal(status.state, "needs_authorization");
  assert.equal(status.connected, false);
  assert.equal(status.authenticated, false);
  assert.equal(status.authorizationStored, false);
  await assert.rejects(client.refresh(), /E_VTS_AUTH_REQUIRED/);
});

test("empty CurrentModel frame means authenticated with no model loaded", async () => {
  const store = tokenStore("owner-secret-token");
  const sockets = [];
  const client = new VTubeStudioClient(store, () => {
    const socket = new FakeWebSocket({ currentModelFrame: "empty" });
    sockets.push(socket);
    return socket;
  });

  const status = await client.connect(false);
  assert.equal(status.state, "connected");
  assert.equal(status.connected, true);
  assert.equal(status.authenticated, true);
  assert.equal(status.model.loaded, false);
  assert.deepEqual(status.hotkeys, []);
  assert.equal(
    sockets[0].requests.some(
      (request) => request.messageType === "HotkeysInCurrentModelRequest",
    ),
    false,
  );
});

test("non-empty malformed VTube Studio frames still fail closed", async () => {
  const client = new VTubeStudioClient(
    tokenStore("owner-secret-token"),
    () => new FakeWebSocket({ currentModelFrame: "malformed" }),
  );

  await assert.rejects(client.connect(false), /E_VTS_PROTOCOL: response is invalid JSON/);
  const status = client.status();
  assert.equal(status.state, "error");
  assert.equal(status.authenticated, false);
  assert.equal(status.lastErrorCode, "E_VTS_PROTOCOL");
});
