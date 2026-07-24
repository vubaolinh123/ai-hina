import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { join } from "node:path";
import test from "node:test";

const ROOT = new URL("..", import.meta.url);
const read = (path) => readFileSync(new URL(path, ROOT), "utf8");
const require = createRequire(import.meta.url);
const control = require("../dist-electron/control-client.js");

test("BrowserWindow keeps renderer sandboxed and blocks navigation surfaces", () => {
  const main = read("electron/main.ts");
  assert.match(main, /nodeIntegration:\s*false/);
  assert.match(main, /contextIsolation:\s*true/);
  assert.match(main, /sandbox:\s*true/);
  assert.match(main, /webSecurity:\s*true/);
  assert.match(main, /webviewTag:\s*false/);
  assert.match(main, /setWindowOpenHandler/);
  assert.match(main, /setWindowOpenHandler\(\(\)\s*=>\s*\(\{\s*action:\s*"deny"\s*\}\)\)/);
  assert.match(main, /will-navigate/);
  assert.match(main, /will-attach-webview/);
  assert.match(main, /loadFile\(rendererPath\)/);
  assert.match(main, /event\.sender\s*!==\s*mainWindow\.webContents/);
  assert.match(main, /event\.senderFrame\s*!==\s*event\.sender\.mainFrame/);
  assert.match(main, /window\.hinaDesktop\.getRuntimeHealth\(\)/);
  assert.match(main, /window\.hinaDesktop\.getAvatarStatus\(\)/);
  assert.doesNotMatch(main, /executeJavaScript\([^)]*\$\{/s);
  assert.doesNotMatch(main, /loadURL\(/);
  assert.doesNotMatch(main, /openExternal|from\s+["']electron["'];?\s*.*\bshell\b/);
});

test("preload exposes named methods and never exposes raw ipcRenderer", () => {
  const preload = read("electron/preload.ts");
  assert.match(preload, /exposeInMainWorld\("hinaDesktop", hinaDesktop\)/);
  assert.doesNotMatch(preload, /exposeInMainWorld\([^,]+,\s*ipcRenderer/);
  assert.doesNotMatch(preload, /\bsend\s*:/);
  assert.doesNotMatch(preload, /shell|readFile|writeFile|exec\(/);
  for (const method of [
    "getAvatarStatus",
    "applyAvatarCue",
    "resetAvatar",
    "getSafetyStatus",
    "applySafetyControl",
    "getRuntimeHealth",
  ]) {
    assert.match(preload, new RegExp(`${method}:`));
  }
});

test("Vue renderer has no direct network, Electron, Node or storage access", () => {
  const renderer = [
    read("src/App.vue"),
    read("src/main.ts"),
  ].join("\n");
  assert.doesNotMatch(renderer, /\bfetch\s*\(/);
  assert.doesNotMatch(renderer, /from\s+["']electron["']/);
  assert.doesNotMatch(renderer, /node:|indexedDB|localStorage|sessionStorage/);
  assert.doesNotMatch(renderer, /sqlite|qdrant|modelPath|process\.env/i);
});

test("control client accepts numeric loopback only and validates mutations", () => {
  assert.equal(
    control.parseControlBaseUrl("http://127.0.0.1:8765"),
    "http://127.0.0.1:8765",
  );
  for (const invalid of [
    "https://127.0.0.1:8765",
    "http://localhost:8765",
    "http://0.0.0.0:8765",
    "http://user:pass@127.0.0.1:8765",
    "http://127.0.0.1:8765/v1",
  ]) {
    assert.throws(() => control.parseControlBaseUrl(invalid), /E_DESKTOP_CONTROL_URL/);
  }
  assert.deepEqual(
    control.validateAvatarCue({
      source: "owner.console",
      state: "thinking",
      mode: "manual-preview",
    }),
    {
      source: "owner.console",
      state: "thinking",
      mode: "manual-preview",
    },
  );
  assert.throws(
    () => control.validateAvatarCue({
      source: "conversation.service",
      state: "speaking",
      mode: "runtime",
    }),
    /E_DESKTOP_AVATAR_CUE/,
  );
  assert.deepEqual(
    control.validateSafetyControl({ action: "set_mute", enabled: true }),
    { action: "set_mute", enabled: true },
  );
  assert.throws(
    () => control.validateSafetyControl({ action: "execute", command: "whoami" }),
    /E_DESKTOP_SAFETY_CONTROL/,
  );
});

test("control client maps only fixed operations and bounds control responses", async () => {
  const calls = [];
  const fetchImpl = async (url, init) => {
    calls.push({ url, method: init.method, body: init.body });
    return new Response(JSON.stringify({ state: "idle", sequence: 4 }), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    });
  };
  assert.deepEqual(
    await control.requestControl("avatar.status", undefined, { fetchImpl }),
    { state: "idle", sequence: 4 },
  );
  assert.deepEqual(calls, [{
    url: "http://127.0.0.1:8765/v1/avatar/status",
    method: "GET",
    body: undefined,
  }]);
  await assert.rejects(
    control.requestControl("filesystem.read", { path: "secret" }, { fetchImpl }),
    /E_DESKTOP_OPERATION/,
  );
  await assert.rejects(
    control.requestControl("avatar.status", { extra: true }, { fetchImpl }),
    /GET operation cannot include a body/,
  );
  await assert.rejects(
    control.requestControl("avatar.status", undefined, {
      fetchImpl: async () => new Response("x".repeat(262_145), { status: 200 }),
    }),
    /control response exceeds the desktop limit/,
  );
  await assert.rejects(
    control.requestControl("avatar.status", undefined, {
      fetchImpl: async () => new Response(JSON.stringify({
        errorCode: `E_${"X".repeat(100)}`,
        message: "m".repeat(500),
      }), { status: 400 }),
    }),
    (error) => (
      error instanceof Error
      && error.message.startsWith("E_")
      && error.message.length <= 259
    ),
  );
});

test("renderer CSP denies network, objects, framing and form submission", () => {
  const html = read("index.html");
  assert.match(html, /connect-src 'none'/);
  assert.match(html, /object-src 'none'/);
  assert.match(html, /form-action 'none'/);
  assert.match(html, /frame-ancestors 'none'/);
});
