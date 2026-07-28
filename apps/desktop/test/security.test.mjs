import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { join } from "node:path";
import test from "node:test";

const ROOT = new URL("..", import.meta.url);
const read = (path) => readFileSync(new URL(path, ROOT), "utf8");
const readOperatorRenderer = () => [
  read("src/App.vue"),
  read("src/dashboard/DashboardNav.vue"),
  read("src/dashboard/pages/OverviewPage.vue"),
  read("src/dashboard/pages/ChatPage.vue"),
  read("src/dashboard/pages/PerceptionPage.vue"),
  read("src/dashboard/pages/ResourcesPage.vue"),
  read("src/dashboard/pages/SpeechPage.vue"),
  read("src/dashboard/pages/Live2DPage.vue"),
  read("src/dashboard/pages/AvatarPage.vue"),
  read("src/dashboard/pages/RuntimePage.vue"),
  read("src/composables/use-avatar-runtime.ts"),
].join("\n");
const require = createRequire(import.meta.url);
const control = require("../dist-electron/control-client.js");

test("desktop warms the one 8B brain through the bounded GPU fast path", () => {
  const launcher = read("../../tools/dev/Start-HinaDesktop.ps1");
  const providerBootstrap = read("../../tools/dev/Start-HinaModelProvider.ps1");
  assert.match(
    launcher,
    /&\s+\$modelScript\s+-PullMissingModel\s+-StartupCheck/,
  );
  assert.match(providerBootstrap, /keep_alive\s*=\s*0/);
  assert.match(providerBootstrap, /num_predict\s*=\s*8/);
  assert.match(providerBootstrap, /num_gpu\s*=\s*999/);
  assert.match(providerBootstrap, /Elapsed\.TotalSeconds\s+-ge\s+10/);
});

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
    "onWidgetHover",
    "getAvatarStatus",
    "applyAvatarCue",
    "resetAvatar",
    "getSafetyStatus",
    "applySafetyControl",
    "getRuntimeHealth",
    "getVTubeStudioStatus",
    "connectVTubeStudio",
    "disconnectVTubeStudio",
    "refreshVTubeStudio",
    "triggerVTubeStudioHotkey",
    "moveVTubeStudioModel",
    "getSpoutStatus",
    "getVisionProviderStatus",
    "discoverVisionModels",
    "configureVisionProvider",
    "clearVisionApiKey",
    "getResourceStatus",
    "controlResourceModel",
    "listScreenCaptureSources",
    "captureScreenSource",
    "onScreenCaptureProgress",
  ]) {
    assert.match(preload, new RegExp(`${method}:`));
  }
});

test("Ollama Cloud vision key stays behind OS-encrypted operator IPC", () => {
  const main = read("electron/main.ts");
  const preload = read("electron/preload.ts");
  const client = read("electron/control-client.ts");
  const renderer = readOperatorRenderer();

  assert.match(main, /safeStorage\.isEncryptionAvailable\(\)/);
  assert.match(main, /safeStorage\.encryptString/);
  assert.match(main, /safeStorage\.decryptString/);
  assert.match(main, /hina-vision-provider\.v1\.json/);
  assert.match(main, /E_DESKTOP_VISION_AUTHORITY: operator window required/);
  assert.match(main, /rendererCanReadStoredKey:\s*false/);
  assert.match(main, /runtimeVisionRecord\.apiKeyConfigured !== true/);
  assert.doesNotMatch(preload, /decryptString|encryptedApiKey/);
  assert.match(client, /https?:/);
  assert.match(client, /\/v1\/perception\/vision\/configure/);
  assert.match(renderer, /type="password"/);
  assert.match(renderer, /autocomplete="off"/);
  assert.match(renderer, /API key đã được lưu/);
  assert.match(renderer, /Ghi đè API key và giữ model này/);
  assert.match(renderer, /selectableVisionModels/);
  assert.doesNotMatch(renderer, /localStorage|sessionStorage/);
});

test("Vue renderer has no direct network, Electron, Node or storage access", () => {
  const renderer = [
    readOperatorRenderer(),
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

test("operator dashboard keeps page markup modular and chat input reachable", () => {
  const app = read("src/App.vue");
  const nav = read("src/dashboard/DashboardNav.vue");
  const overview = read("src/dashboard/pages/OverviewPage.vue");
  const chat = read("src/dashboard/pages/ChatPage.vue");
  const perception = read("src/dashboard/pages/PerceptionPage.vue");
  const resources = read("src/dashboard/pages/ResourcesPage.vue");
  const speech = read("src/dashboard/pages/SpeechPage.vue");
  const live2d = read("src/dashboard/pages/Live2DPage.vue");
  const avatar = read("src/dashboard/pages/AvatarPage.vue");
  const runtime = read("src/dashboard/pages/RuntimePage.vue");
  const avatarRuntime = read("src/composables/use-avatar-runtime.ts");
  const style = read("src/style.css");

  assert.match(app, /import DashboardNav from "\.\/dashboard\/DashboardNav\.vue"/);
  assert.match(app, /import OverviewPage from "\.\/dashboard\/pages\/OverviewPage\.vue"/);
  assert.match(app, /import ChatPage from "\.\/dashboard\/pages\/ChatPage\.vue"/);
  assert.match(app, /import PerceptionPage from "\.\/dashboard\/pages\/PerceptionPage\.vue"/);
  assert.match(app, /import ResourcesPage from "\.\/dashboard\/pages\/ResourcesPage\.vue"/);
  assert.match(app, /import SpeechPage from "\.\/dashboard\/pages\/SpeechPage\.vue"/);
  assert.match(app, /import Live2DPage from "\.\/dashboard\/pages\/Live2DPage\.vue"/);
  assert.match(app, /import AvatarPage from "\.\/dashboard\/pages\/AvatarPage\.vue"/);
  assert.match(app, /import RuntimePage from "\.\/dashboard\/pages\/RuntimePage\.vue"/);
  assert.match(app, /import \{ useAvatarRuntime \} from "\.\/composables\/use-avatar-runtime"/);
  assert.match(app, /\} = useAvatarRuntime\(\);/);
  assert.doesNotMatch(
    app,
    /function (?:refreshAvatar|refreshSafety|refreshWidget|applyWidgetControl|preview|resetAvatar|toggleMute|toggleEmergency|retryVrm)\(/,
  );
  assert.doesNotMatch(
    app,
    /window\.hinaDesktop\.(?:getAvatarStatus|getWidgetStatus|applyWidgetControl|applyAvatarCue|resetAvatar)/,
  );
  assert.doesNotMatch(app, /<nav class="desktop-nav"/);
  assert.doesNotMatch(app, /class="screen-capture-panel"/);
  assert.doesNotMatch(app, /class="resource-summary-grid"/);
  assert.doesNotMatch(app, /class="speech-test-grid"/);
  assert.doesNotMatch(app, /class="live2d-grid"/);
  assert.doesNotMatch(app, /class="stage-grid"/);
  assert.doesNotMatch(app, /class="widget-settings-card"/);
  assert.match(nav, /Live2D \/ VTube Studio/);
  assert.match(overview, /Mở chat với Hina/);
  assert.match(chat, /Context hội thoại của Hina/);
  assert.match(chat, /ref="messageList"/);
  assert.match(chat, /followLatestMessage/);
  assert.match(chat, /Bạn muốn nói gì với Hina\?/);
  assert.match(perception, /Chụp toàn bộ nguồn đã chọn và gửi Hina/);
  assert.match(perception, /visionPreferenceTouched/);
  assert.match(perception, /Renderer không thể đọc ngược key đã lưu/);
  assert.doesNotMatch(perception, /window\.hinaDesktop|\bfetch\s*\(|from\s+["']electron["']/);
  assert.match(resources, /MODEL RESIDENCY/);
  assert.match(resources, /Force load/);
  assert.match(resources, /emit\('controlModel'/);
  assert.doesNotMatch(resources, /window\.hinaDesktop|\bfetch\s*\(|from\s+["']electron["']/);
  assert.match(speech, /MIC → LOCAL STT REALTIME/);
  assert.match(speech, /TEXT → OMNIVOICE VIETNAMESE GPU/);
  assert.match(speech, /emit\('startMic'\)/);
  assert.doesNotMatch(speech, /window\.hinaDesktop|\bfetch\s*\(|getUserMedia|from\s+["']electron["']/);
  assert.match(live2d, /VTubeStudioSpout/);
  assert.match(live2d, /emit\('triggerHotkey'/);
  assert.doesNotMatch(live2d, /window\.hinaDesktop|\bfetch\s*\(|\bWebSocket\b|from\s+["']electron["']/);
  assert.match(avatar, /AVATAR RENDERER \/ LOCAL ONLY/);
  assert.match(avatar, /emit\('vrmPerformance'/);
  assert.doesNotMatch(avatar, /window\.hinaDesktop|\bfetch\s*\(|\bWebSocket\b|from\s+["']electron["']/);
  assert.match(runtime, /Quản lý widget avatar/);
  assert.match(runtime, /emit\('widgetControl'/);
  assert.doesNotMatch(runtime, /window\.hinaDesktop|\bfetch\s*\(|\bWebSocket\b|from\s+["']electron["']/);
  assert.match(avatarRuntime, /window\.hinaDesktop\.getAvatarStatus/);
  assert.match(avatarRuntime, /window\.hinaDesktop\.applyWidgetControl/);
  assert.match(avatarRuntime, /window\.hinaDesktop\.applySafetyControl/);
  assert.doesNotMatch(avatarRuntime, /from\s+["']electron["']|\bfetch\s*\(|node:|localStorage|sessionStorage|indexedDB|process\.env/);
  assert.match(style, /\.chat-composer[\s\S]*position:\s*sticky/);
  assert.match(style, /\.chat-layout[\s\S]*grid-template-columns:\s*1fr/);
});

test("resource telemetry and owner controls stay behind typed operator IPC", () => {
  const main = read("electron/main.ts");
  const preload = read("electron/preload.ts");
  const client = read("electron/control-client.ts");
  const monitor = read("electron/resource-monitor.ts");
  const renderer = readOperatorRenderer();

  assert.match(main, /CHANNELS\.resourcesStatus/);
  assert.match(main, /E_DESKTOP_RESOURCE_AUTHORITY: operator window required/);
  assert.match(main, /requestControl\("resources\.status"\)/);
  assert.match(main, /CHANNELS\.resourcesControl/);
  assert.match(main, /requestResourceModelControl/);
  assert.match(preload, /getResourceStatus:/);
  assert.match(preload, /controlResourceModel:/);
  assert.match(client, /"resources\.status":\s*\{\s*method:\s*"GET",\s*path:\s*"\/v1\/resources\/status"/);
  assert.match(client, /"resources\.model":\s*\{\s*method:\s*"POST",\s*path:\s*"\/v1\/resources\/models\/control"/);
  assert.match(client, /ownerConfirmed:\s*true/);
  assert.match(monitor, /ModelTransitionTracker/);
  assert.match(monitor, /historyPersistence|transitionHistory/);
  assert.doesNotMatch(renderer, /child_process|nvidia-smi|process\.memoryUsage|node:os/);
});

test("full-frame screen capture stays in Electron main behind one-use grants", () => {
  const main = read("electron/main.ts");
  const preload = read("electron/preload.ts");
  const capture = read("electron/screen-capture.ts");
  const client = read("electron/control-client.ts");
  const renderer = readOperatorRenderer();

  assert.match(main, /desktopCapturer\.getSources/);
  assert.match(main, /E_DESKTOP_CAPTURE_AUTHORITY: operator window required/);
  assert.match(main, /E_DESKTOP_CAPTURE_DISABLED: enable Quan sát màn hình/);
  assert.match(main, /requestControl\("safety\.status"\)/);
  assert.match(main, /captureGrantStore\.consume/);
  assert.match(main, /requestPerceptionSnapshot/);
  assert.match(preload, /listScreenCaptureSources:/);
  assert.match(preload, /captureScreenSource:/);
  assert.match(preload, /onScreenCaptureProgress:/);
  assert.match(main, /CHANNELS\.captureProgress/);
  assert.match(renderer, /handleScreenCaptureProgress/);
  assert.doesNotMatch(preload, /desktopCapturer|sourceId/);
  assert.match(capture, /CAPTURE_GRANT_TTL_MILLISECONDS\s*=\s*60_000/);
  assert.match(capture, /CAPTURE_MAX_SIDES/);
  assert.match(capture, /persistence:\s*false/);
  assert.match(client, /"X-Hina-Source":\s*"owner\.desktop"/);
  assert.match(client, /"X-Hina-Owner-Confirmed":\s*"true"/);
  assert.match(renderer, /screenCaptureMaxSide\s*=\s*ref<640 \| 960 \| 1280>\(960\)/);
  assert.match(renderer, /sessionId:\s*chatSessionId/);
  assert.match(renderer, /askHinaAboutLastCapture/);
  assert.match(
    renderer,
    /screenCaptureAnalyzeVision\.value\s*=\s*\n?\s*visionProviderStatus\.value\.runtime\.available/,
  );
  assert.match(renderer, /Model vision chưa trả được kết quả/);
  assert.match(renderer, /visionAnalysisErrorCode/);
  assert.match(renderer, /Chụp toàn bộ nguồn đã chọn và gửi Hina/);
  assert.doesNotMatch(renderer, /getDisplayMedia|desktopCapturer|sourceId/);
});

test("VTube Studio stays in the main process behind operator-only typed IPC", () => {
  const main = read("electron/main.ts");
  const preload = read("electron/preload.ts");
  const client = read("electron/vtube-studio-client.ts");
  const app = readOperatorRenderer();
  assert.match(main, /E_VTS_AUTHORITY: operator window required/);
  assert.match(main, /VTS_TOKEN_STATE_MAX_BYTES/);
  assert.match(main, /hina-vtube-studio-token\.v1\.json/);
  assert.doesNotMatch(preload, /authenticationToken|WebSocket/);
  assert.match(client, /ws:\/\/127\.0\.0\.1:8001/);
  assert.match(client, /VTubeStudioPublicAPI/);
  assert.match(client, /AuthenticationTokenRequest/);
  assert.match(client, /AuthenticationRequest/);
  assert.match(client, /HotkeyTriggerRequest/);
  assert.match(client, /MoveModelRequest/);
  assert.match(client, /hiyoriBundled:\s*false/);
  assert.doesNotMatch(client, /wss?:\/\/(?!127\.0\.0\.1)/);
  assert.match(app, /Live2D \/ VTube Studio/);
  assert.match(app, /connectVTubeStudio/);
  assert.match(app, /triggerVTubeStudioHotkey/);
  assert.match(app, /moveVTubeStudioModel/);
  assert.match(app, /Hiyori là sample của Live2D/);
  assert.match(app, /VRM local vẫn là fallback/);
});

test("Spout2 frame bridge is fixed to loopback and the allowlisted sender", () => {
  const main = read("electron/main.ts");
  const preload = read("electron/preload.ts");
  const bridge = read("electron/spout-bridge.ts");
  const worker = read("../../tools/dev/vts_spout_bridge.py");
  const widget = read("src/DesktopWidget.vue");

  assert.match(main, /CHANNELS\.spoutStatus/);
  assert.match(preload, /getSpoutStatus:/);
  assert.match(bridge, /const SENDER_NAME = "VTubeStudioSpout"/);
  assert.match(bridge, /http:\/\/127\.0\.0\.1:\$\{port\}/);
  assert.match(bridge, /shell:\s*false/);
  assert.match(bridge, /liru==0\.2\.6/);
  assert.match(bridge, /moderngl==5\.12\.0/);
  assert.match(bridge, /Pillow==11\.3\.0/);
  assert.match(worker, /\("127\.0\.0\.1", port\)/);
  assert.match(worker, /SENDER_NAME = "VTubeStudioSpout"/);
  assert.match(worker, /MAX_FRAME_BYTES = 4 \* 1024 \* 1024/);
  assert.match(worker, /receiver_needs_reconnect/);
  assert.match(worker, /receiver = liru\.Receiver\(SENDER_NAME\)/);
  assert.doesNotMatch(worker, /\b(?:open|write_text|write_bytes)\s*\(/);
  assert.match(widget, /class="spout-frame"/);
  assert.match(widget, /showVrmFallback/);
  assert.match(widget, /getSpoutStatus/);
  assert.match(widget, /next\.state === "ready"/);
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
  assert.match(main, /CHANNELS\.widgetHover/);
  assert.match(main, /getCursorScreenPoint/);
  assert.match(main, /startWidgetHoverWatcher/);
  assert.match(main, /stopWidgetHoverWatcher/);
  const preloadSource = read("electron/preload.ts");
  assert.match(preloadSource, /onWidgetHover:/);
  assert.match(preloadSource, /removeListener\(CHANNELS\.widgetHover/);

  assert.match(widget, /class="desktop-widget"/);
  assert.match(widget, /class="widget-avatar-surface"/);
  assert.match(widget, /class="widget-control widget-voice-button"/);
  assert.match(widget, /id="widgetMicButton"/);
  assert.match(widget, /id="widgetAutoListenButton"/);
  assert.equal((widget.match(/\bclass="widget-control\b/g) ?? []).length, 3);
  assert.match(widget, /Voice ·/);
  assert.match(widget, /Nói với Hina/);
  assert.match(widget, /Auto nghe/);
  assert.match(widget, /action:\s*"set_mute"/);
  assert.match(widget, /avatar\.value\?\.viseme/);
  assert.match(widget, /avatar\.value(?:\?\.|\.)intensity/);
  assert.match(widget, /getUserMedia/);
  assert.match(widget, /transcribeSpeech/);
  assert.match(widget, /monitorAutoListen/);
  assert.match(widget, /onWidgetHover/);
  assert.match(widget, /await new Promise<void>/);
  assert.doesNotMatch(widget, /ScriptProcessorNode|createScriptProcessor/);
  assert.match(widget, /encodePcmWav/);
  const app = readOperatorRenderer();
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
  assert.match(style, /\.widget-auto-listen-button[\s\S]*-webkit-app-region:\s*no-drag/);
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
  const avatar = read("src/dashboard/pages/AvatarPage.vue");
  const avatarRuntime = read("src/composables/use-avatar-runtime.ts");
  const main = read("electron/main.ts");
  assert.match(
    app,
    /defineAsyncComponent\(\(\)\s*=>\s*import\("\.\/VrmStage\.vue"\)\)/,
  );
  assert.match(app, /:stage-component="VrmStage"/);
  assert.match(avatar, /:key="props\.vrmStageKey"/);
  assert.match(avatar, /'vrm-stage-hidden': !props\.vrmReady/);
  assert.doesNotMatch(avatar, /v-show="props\.vrmReady"/);
  assert.match(avatarRuntime, /function retryVrm\(\)/);
  assert.match(avatarRuntime, /function retryConnection\(\)/);
  assert.match(avatar, /id="retryVrmButton"/);
  assert.match(avatarRuntime, /setInterval\(refreshAvatar, 250\)/);
  assert.match(avatarRuntime, /vrmStageKey\.value \+= 1/);
  assert.match(avatar, /@performance="emit\('vrmPerformance', \$event\)"/);
  assert.match(avatar, /frameTimeP95Ms/);
  assert.match(avatar, /droppedFramePercent/);
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
  assert.deepEqual(
    control.validateSafetyControl({
      action: "set_feature",
      feature: "perception",
      enabled: true,
    }),
    { action: "set_feature", feature: "perception", enabled: true },
  );
  assert.throws(
    () => control.validateSafetyControl({
      action: "set_feature",
      feature: "streamOutput",
      enabled: true,
    }),
    /only the perception feature/,
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

test("control client sends bounded PNG only to the fixed perception route", async () => {
  const png = new Uint8Array(33);
  png.set([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]);
  let request = null;
  const result = await control.requestPerceptionSnapshot(
    png,
    {
      sessionId: "55555555-5555-4555-8555-555555555555",
      label: "Minecraft",
      analyzeVision: true,
      visionQuestion: "Có nguy hiểm nào gần nhân vật?",
    },
    {
      baseUrl: "http://127.0.0.1:8765",
      fetchImpl: async (url, options) => {
        request = { url, options };
        return new Response(
          JSON.stringify({ status: "observed", correlationId: "test" }),
          {
            status: 200,
            headers: { "Content-Type": "application/json" },
          },
        );
      },
    },
  );
  assert.equal(result.status, "observed");
  assert.equal(request.url, "http://127.0.0.1:8765/v1/perception/snapshots");
  assert.equal(request.options.method, "POST");
  assert.equal(request.options.headers["Content-Type"], "image/png");
  assert.equal(
    request.options.headers["X-Hina-Session-Id"],
    "55555555-5555-4555-8555-555555555555",
  );
  assert.equal(request.options.headers["X-Hina-Source"], "owner.desktop");
  assert.equal(request.options.headers["X-Hina-Owner-Confirmed"], "true");
  assert.equal(request.options.headers["X-Hina-Vision-Analyze"], "true");
  await assert.rejects(
    control.requestPerceptionSnapshot(
      new Uint8Array(33),
      {
        sessionId: "55555555-5555-4555-8555-555555555555",
        label: null,
        analyzeVision: false,
        visionQuestion: null,
      },
    ),
    /snapshot must be a PNG/,
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
  assert.match(html, /img-src[^;]*http:\/\/127\.0\.0\.1:\*/);
  assert.match(html, /connect-src[^;]*http:\/\/127\.0\.0\.1:\*/);
  assert.match(html, /object-src 'none'/);
  assert.match(html, /form-action 'none'/);
  assert.match(html, /frame-ancestors 'none'/);
  assert.doesNotMatch(html, /https:\/\/|wss:\/\/|http:\/\/(?!127\.0\.0\.1:\*)/);
  assert.doesNotMatch(html, /connect-src[^;]*(?:data:|https:\/\/|wss:\/\/)/);
});
