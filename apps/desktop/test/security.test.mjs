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
  assert.match(main, /backgroundThrottling:\s*false/);
  assert.match(main, /opacity:\s*smoke \? 0 : 1/);
  assert.match(main, /skipTaskbar:\s*smoke/);
  assert.match(main, /setWindowOpenHandler/);
  assert.match(main, /attachRendererConsoleLogging/);
  assert.match(main, /console-message/);
  assert.match(main, /render-process-gone/);
  assert.match(main, /setWindowOpenHandler\(\(\)\s*=>\s*\(\{\s*action:\s*"deny"\s*\}\)\)/);
  assert.match(main, /will-navigate/);
  assert.match(main, /will-attach-webview/);
  assert.match(main, /loadFile\(rendererPath\)/);
  assert.match(main, /event\.sender\s*===\s*mainWindow\.webContents/);
  assert.match(main, /event\.sender\s*===\s*widgetWindow\.webContents/);
  assert.match(main, /event\.senderFrame\s*!==\s*event\.sender\.mainFrame/);
  assert.match(main, /window\.hinaDesktop\.getRuntimeHealth\(\)/);
  assert.match(main, /window\.hinaDesktop\.getAvatarStatus\(\)/);
  assert.match(main, /dataset\.vrmReady\s*===\s*"true"/);
  assert.match(main, /snapshot\.vrmLoaded\s*!==\s*true/);
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
    "getWindowMode",
    "getWidgetStatus",
    "applyWidgetControl",
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
    read("src/DesktopWidget.vue"),
    read("src/audio-utils.ts"),
    read("src/main.ts"),
    read("src/VrmStage.vue"),
    read("src/hina-presentation.mjs"),
    read("src/frame-metrics.mjs"),
  ].join("\n");
  assert.doesNotMatch(renderer, /\bfetch\s*\(/);
  assert.doesNotMatch(renderer, /from\s+["']electron["']/);
  assert.doesNotMatch(renderer, /node:|indexedDB|localStorage|sessionStorage/);
  assert.doesNotMatch(renderer, /sqlite|qdrant|modelPath|process\.env/i);
});

test("transparent widget keeps hover Voice/Mic controls and a native drag surface", () => {
  const main = read("electron/main.ts");
  const widget = read("src/DesktopWidget.vue");
  const style = read("src/style.css");

  assert.match(main, /frame:\s*false/);
  assert.match(main, /transparent:\s*true/);
  assert.match(main, /hasShadow:\s*false/);
  assert.match(main, /resizable:\s*false/);
  assert.match(main, /movable:\s*true/);
  assert.match(main, /alwaysOnTop:\s*true/);
  assert.match(main, /skipTaskbar:\s*true/);
  assert.match(main, /backgroundColor:\s*"#00000000"/);
  assert.match(main, /screen\.getPrimaryDisplay\(\)\.workArea/);
  assert.match(main, /setAlwaysOnTop\(true,\s*"floating"\)/);
  assert.match(main, /setVisibleOnAllWorkspaces\(true/);
  assert.match(main, /widgetWindow\.loadFile\(rendererPath\)/);
  assert.match(main, /CHANNELS\.windowMode/);
  assert.match(main, /CHANNELS\.widgetStatus/);
  assert.match(main, /CHANNELS\.widgetControl/);
  assert.match(main, /E_DESKTOP_WIDGET_AUTHORITY: operator window required/);
  assert.match(main, /reset_position/);
  assert.match(main, /scheduleWidgetPositionWrite/);

  assert.match(widget, /class="desktop-widget"/);
  assert.match(widget, /class="widget-avatar-surface"/);
  assert.match(widget, /class="widget-control widget-voice-button"/);
  assert.match(widget, /id="widgetMicButton"/);
  assert.equal((widget.match(/\bclass="widget-control\b/g) ?? []).length, 2);
  assert.match(widget, /Voice ·/);
  assert.match(widget, /Mic · Nói với Hina/);
  assert.match(widget, /action:\s*"set_mute"/);
  assert.match(widget, /avatar\.value\?\.viseme/);
  assert.match(widget, /avatar\.value(?:\?\.|\.)intensity/);
  assert.match(widget, /getUserMedia/);
  assert.match(widget, /transcribeSpeech/);
  assert.doesNotMatch(widget, /ScriptProcessorNode|createScriptProcessor/);
  assert.match(widget, /encodePcmWav/);
  const app = read("src/App.vue");
  assert.match(app, /Mic \/ STT \/ TTS/);
  assert.match(app, /speechStartMic/);
  assert.match(app, /speechTestTts/);
  assert.match(app, /transcribeSpeech/);
  assert.match(app, /synthesizeSpeech/);
  assert.match(app, /getUserMedia/);
  assert.doesNotMatch(app, /ScriptProcessorNode|createScriptProcessor/);
  assert.match(app, /Realtime/);
  const recorder = read("src/microphone-recorder.ts");
  assert.match(recorder, /AudioWorkletNode/);
  assert.match(recorder, /hina-audio-capture-worklet\.js/);

  assert.match(style, /\.widget-avatar-surface[\s\S]*-webkit-app-region:\s*drag/);
  assert.match(style, /\.widget-voice-button[\s\S]*-webkit-app-region:\s*no-drag/);
  assert.match(style, /\.widget-mic-button[\s\S]*-webkit-app-region:\s*no-drag/);
  assert.match(
    style,
    /\.widget-voice-controls[\s\S]*opacity:\s*0[\s\S]*visibility:\s*hidden[\s\S]*pointer-events:\s*none/,
  );
  const index = read("index.html");
  assert.match(index, /media-src 'self' blob:/);
  assert.match(style, /\.desktop-widget:hover \.widget-voice-controls/);
  assert.match(style, /\.desktop-widget:focus-within \.widget-voice-controls/);
  assert.match(
    style,
    /html\[data-window-mode="widget"\][\s\S]*background:\s*transparent/,
  );
});

test("VRM stage uses one fixed bundled asset and disposes graphics resources", () => {
  const stage = read("src/VrmStage.vue");
  assert.match(
    stage,
    /\.\.\/\.\.\/\.\.\/assets\/avatars\/vrm1-constraint-twist-sample\/VRM1_Constraint_Twist_Sample\.vrm/,
  );
  assert.match(stage, /loader\.register\(\(parser\)\s*=>\s*new VRMLoaderPlugin\(parser\)\)/);
  assert.match(stage, /loader\.loadAsync\(VRM_ASSET_URL\)/);
  assert.match(stage, /VRMUtils\.deepDispose\(vrm\.scene\)/);
  assert.match(stage, /renderer\?\.dispose\(\)/);
  assert.match(stage, /renderer\?\.forceContextLoss\(\)/);
  assert.match(stage, /resizeObserver\?\.disconnect\(\)/);
  assert.match(stage, /cancelAnimationFrame\(animationFrame\)/);
  assert.match(stage, /addEventListener\("webglcontextlost", handleWebglContextLost\)/);
  assert.match(stage, /removeEventListener\("webglcontextlost", handleWebglContextLost\)/);
  assert.match(stage, /createFrameMetrics\(\{/);
  assert.match(stage, /emit\("performance", performanceReport\)/);
  assert.match(stage, /applyHinaPalette\(loaded\.scene\)/);
  assert.match(stage, /addHinaAccessories\(loaded\)/);
  assert.match(stage, /createHinaPoseFrame\(props\.state, time\)/);
  assert.doesNotMatch(stage, /location\.|URLSearchParams|querySelector.*(?:url|path)/i);
  assert.doesNotMatch(stage, /https?:\/\//);
  assert.doesNotMatch(stage, /rotation\.y\s*=\s*Math\.PI/);
});

test("VRM is lazy-loaded and fixed-asset recovery exposes bounded real telemetry", () => {
  const app = read("src/App.vue");
  const main = read("electron/main.ts");
  assert.match(
    app,
    /defineAsyncComponent\(\(\)\s*=>\s*import\("\.\/VrmStage\.vue"\)\)/,
  );
  assert.match(app, /:key="vrmStageKey"/);
  assert.match(app, /'vrm-stage-hidden': !vrmReady/);
  assert.doesNotMatch(app, /v-show="vrmReady"/);
  assert.match(app, /function retryVrm\(\)/);
  assert.match(app, /function retryConnection\(\)/);
  assert.match(app, /id="retryVrmButton"/);
  assert.match(app, /setInterval\(refreshAvatar, 250\)/);
  assert.match(app, /vrmStageKey\.value \+= 1/);
  assert.match(app, /@performance="handleVrmPerformance"/);
  assert.match(app, /frameTimeP95Ms/);
  assert.match(app, /droppedFramePercent/);
  assert.doesNotMatch(app, /assetPath|modelPath|URLSearchParams|querySelector.*path/i);
  assert.match(main, /E_DESKTOP_PERFORMANCE_SMOKE_TIMEOUT/);
  assert.match(main, /getExtension\("WEBGL_lose_context"\)/);
  assert.match(main, /E_DESKTOP_VRM_RECOVERY_TIMEOUT/);
  assert.match(main, /snapshot\.performance\.droppedFramePercent > 5/);
  assert.match(main, /sampleCount < 30/);
  assert.match(main, /snapshot\.loadedTextureCount < 8/);
  assert.match(main, /snapshot\.styledMaterialCount < 13/);
  assert.match(main, /snapshot\.presentation !== "hina-kawaii-v0\.1"/);
  assert.match(main, /app\.quit\(\)/);
  assert.match(app, /addEventListener\("beforeunload", cleanupDesktop/);
  assert.match(app, /function stopPolling\(\)/);
});

test("motion profile covers every state and keeps unknown expressions neutral", () => {
  const motion = JSON.parse(read("src/avatar-motion.json"));
  assert.deepEqual(
    Object.keys(motion.states).sort(),
    ["error", "idle", "interrupted", "listening", "speaking", "thinking"],
  );
  for (const profile of Object.values(motion.states)) {
    assert.equal(typeof profile.expression, "string");
    assert.ok(profile.expressionWeight >= 0 && profile.expressionWeight <= 1);
    assert.ok(profile.breathAmplitude >= 0 && profile.breathAmplitude <= 0.02);
    assert.ok(profile.headAmplitude >= 0 && profile.headAmplitude <= 0.02);
    assert.equal("stateDrivenMouth" in profile, false);
  }
  assert.deepEqual(motion.expressionAliases, {
    neutral: "neutral",
    happy: "happy",
    curious: "surprised",
    focused: "neutral",
    concerned: "sad",
  });
  const stage = read("src/VrmStage.vue");
  assert.match(stage, /const expression = alias \?\? "neutral"/);
  assert.match(stage, /A:\s*"aa"/);
  assert.match(stage, /I:\s*"ih"/);
  assert.match(stage, /U:\s*"ou"/);
  assert.match(stage, /E:\s*"ee"/);
  assert.match(stage, /O:\s*"oh"/);
  assert.match(stage, /props\.viseme/);
  assert.match(stage, /props\.intensity/);
  assert.doesNotMatch(stage, /stateDrivenMouth/);
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

test("control client sends bounded microphone WAV only to the fixed speech route", async () => {
  const calls = [];
  const wav = new Uint8Array(44);
  wav.set(new TextEncoder().encode("RIFF"), 0);
  wav.set(new TextEncoder().encode("WAVE"), 8);
  const response = {
    status: "transcribed",
    transcript: "Xin chào Hina",
    speechDetected: true,
    processingMilliseconds: 12,
    correlationId: "11111111-1111-4111-8111-111111111111",
  };
  const result = await control.requestSpeechTranscription(
    wav,
    "22222222-2222-4222-8222-222222222222",
    {
      fetchImpl: async (url, init) => {
        calls.push({ url, init });
        return new Response(JSON.stringify(response), { status: 200 });
      },
    },
  );
  assert.deepEqual(result, response);
  assert.equal(calls[0].url, "http://127.0.0.1:8765/v1/speech/transcriptions");
  assert.equal(calls[0].init.headers["Content-Type"], "audio/wav");
  assert.equal(new Uint8Array(calls[0].init.body)[0], 0x52);
  await assert.rejects(
    control.requestSpeechTranscription(
      new Uint8Array(45),
      "22222222-2222-4222-8222-222222222222",
      { fetchImpl: async () => new Response("{}", { status: 200 }) },
    ),
    /E_DESKTOP_STT_REQUEST/,
  );
});

test("control client retries cleanly after a transient service restart", async () => {
  let attempts = 0;
  const fetchImpl = async () => {
    attempts += 1;
    if (attempts === 1) {
      throw new TypeError("connection refused");
    }
    return new Response(JSON.stringify({ status: "ready" }), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    });
  };
  await assert.rejects(
    control.requestControl("runtime.health", undefined, { fetchImpl }),
    /E_DESKTOP_CONTROL_OFFLINE/,
  );
  assert.deepEqual(
    await control.requestControl("runtime.health", undefined, { fetchImpl }),
    { status: "ready" },
  );
  assert.equal(attempts, 2);
});

test("renderer CSP denies network, objects, framing and form submission", () => {
  const html = read("index.html");
  assert.match(html, /connect-src 'self' blob:/);
  assert.match(html, /img-src 'self' data: blob:/);
  assert.match(html, /object-src 'none'/);
  assert.match(html, /form-action 'none'/);
  assert.match(html, /frame-ancestors 'none'/);
  assert.doesNotMatch(html, /https?:|wss?:/);
  assert.doesNotMatch(html, /connect-src[^;]*(?:data:|https?:|wss?:)/);
});
