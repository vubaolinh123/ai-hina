import {
  app,
  BrowserWindow,
  desktopCapturer,
  ipcMain,
  safeStorage,
  screen,
  session,
  type IpcMainInvokeEvent,
  type NativeImage,
} from "electron";
import { mkdir, readFile, stat, unlink, writeFile } from "node:fs/promises";
import { dirname, join } from "node:path";
import {
  requestControl,
  requestChatCancel,
  requestChatStart,
  requestChatStatus,
  requestChatTurn,
  requestPerceptionSnapshot,
  requestSpeechSynthesis,
  requestSpeechTranscription,
  requestVisionConfigure,
  requestVisionDisable,
  requestVisionModelDiscovery,
  requestVisionStatus,
  validateVisionApiKey,
  validateVisionModel,
  validateVisionProvider,
  validateAvatarCue,
  validateSafetyControl,
  requestResourceModelControl,
} from "./control-client";
import {
  WIDGET_STATE_MAX_BYTES,
  clampWidgetPosition,
  defaultWidgetPosition,
  parseWidgetPosition,
  serializeWidgetPosition,
  type Point,
  type Size,
  type WorkArea,
} from "./widget-state";
import {
  VTS_TOKEN_STATE_MAX_BYTES,
  VTubeStudioClient,
  parseVTubeStudioTokenState,
  serializeVTubeStudioTokenState,
} from "./vtube-studio-client";
import {
  SpoutBridge,
  type SpoutBridgeStatus,
} from "./spout-bridge";
import {
  VISION_PROVIDER_STATE_MAX_BYTES,
  parseVisionProviderState,
  serializeVisionProviderState,
  type PersistedVisionProviderState,
} from "./vision-provider-state";
import {
  ModelTransitionTracker,
  augmentResourceStatus,
} from "./resource-monitor";
import {
  CaptureGrantStore,
  MAX_CAPTURE_SOURCES,
  fitWithinLongEdge,
  validateFullFrameCaptureRequest,
  type CaptureMaxSide,
  type CaptureSourceCandidate,
  type CaptureSourceKind,
} from "./screen-capture";

const CHANNELS = Object.freeze({
  windowMode: "hina:window:mode",
  widgetStatus: "hina:widget:status",
  widgetControl: "hina:widget:control",
  widgetHover: "hina:widget:hover",
  avatarStatus: "hina:avatar:status",
  avatarCue: "hina:avatar:cue",
  avatarReset: "hina:avatar:reset",
  safetyStatus: "hina:safety:status",
  safetyControl: "hina:safety:control",
  runtimeHealth: "hina:runtime:health",
  chatStatus: "hina:chat:status",
  chatStart: "hina:chat:start",
  chatTurn: "hina:chat:turn",
  chatCancel: "hina:chat:cancel",
  speechTranscribe: "hina:speech:transcribe",
  speechStatus: "hina:speech:status",
  ttsStatus: "hina:tts:status",
  ttsSynthesize: "hina:tts:synthesize",
  vtubeStatus: "hina:vtube:status",
  vtubeConnect: "hina:vtube:connect",
  vtubeDisconnect: "hina:vtube:disconnect",
  vtubeRefresh: "hina:vtube:refresh",
  vtubeHotkey: "hina:vtube:hotkey",
  vtubeMove: "hina:vtube:move",
  spoutStatus: "hina:spout:status",
  visionStatus: "hina:vision:status",
  visionDiscover: "hina:vision:discover",
  visionConfigure: "hina:vision:configure",
  visionClearKey: "hina:vision:clear-key",
  resourcesStatus: "hina:resources:status",
  resourcesControl: "hina:resources:control",
  captureSources: "hina:capture:sources",
  captureSubmit: "hina:capture:submit",
  captureProgress: "hina:capture:progress",
});

const WIDGET_SIZE: Size = Object.freeze({ width: 440, height: 620 });
const WIDGET_STATE_FILENAME = "hina-widget-state.v1.json";
const VTS_TOKEN_STATE_FILENAME = "hina-vtube-studio-token.v1.json";
const VISION_PROVIDER_STATE_FILENAME = "hina-vision-provider.v1.json";
const resourceTransitionTracker = new ModelTransitionTracker(100);
const captureGrantStore = new CaptureGrantStore();

let mainWindow: BrowserWindow | null = null;
let widgetWindow: BrowserWindow | null = null;
let smokeTimer: NodeJS.Timeout | null = null;
let widgetPositionTimer: NodeJS.Timeout | null = null;
let widgetHoverTimer: NodeJS.Timeout | null = null;
let widgetHoverInside = false;
let vtubeStudioClient: VTubeStudioClient | null = null;
let spoutBridge: SpoutBridge | null = null;
let shutdownPending = false;
let visionRestoreTimer: NodeJS.Timeout | null = null;

type DesktopWindowMode = "operator" | "widget";
type WidgetControlAction = "show" | "hide" | "reset_position";
type CaptureProgressPhase = "capturing" | "encoding" | "analyzing";
type CaptureProgress = {
  phase: CaptureProgressPhase;
  requestedMaxSide: CaptureMaxSide;
  sourceName: string;
  width?: number;
  height?: number;
  bytes?: number;
};

function captureElapsedMilliseconds(startedAt: number): number {
  return Math.max(0, Math.round((performance.now() - startedAt) * 10) / 10);
}

function captureSourceKind(sourceId: string): CaptureSourceKind | null {
  if (sourceId.startsWith("screen:")) return "screen";
  if (sourceId.startsWith("window:")) return "window";
  return null;
}

function captureSourceName(raw: string, index: number): string {
  const cleaned = raw
    .replace(/[\u0000-\u001f\u007f]/gu, "")
    .trim()
    .slice(0, 160);
  return cleaned || `Nguồn màn hình ${index + 1}`;
}

async function requirePerceptionFeatureEnabled(): Promise<void> {
  const status = await requestControl("safety.status");
  const state = (
    status.state
    && typeof status.state === "object"
    && !Array.isArray(status.state)
  )
    ? status.state as Record<string, unknown>
    : {};
  const featureFlags = (
    state.featureFlags
    && typeof state.featureFlags === "object"
    && !Array.isArray(state.featureFlags)
  )
    ? state.featureFlags as Record<string, unknown>
    : {};
  if (featureFlags.perception !== true) {
    throw new Error(
      "E_DESKTOP_CAPTURE_DISABLED: enable Quan sát màn hình before listing or capturing",
    );
  }
}

async function listDesktopCaptureSources(): Promise<ReturnType<CaptureGrantStore["issue"]>> {
  await requirePerceptionFeatureEnabled();
  let sources: Awaited<ReturnType<typeof desktopCapturer.getSources>>;
  try {
    sources = await desktopCapturer.getSources({
      types: ["screen", "window"],
      thumbnailSize: { width: 320, height: 180 },
      fetchWindowIcons: false,
    });
  } catch {
    throw new Error("E_DESKTOP_CAPTURE_SOURCES: cannot enumerate desktop sources");
  }
  const candidates: CaptureSourceCandidate[] = [];
  for (const [index, source] of sources.entries()) {
    if (candidates.length >= MAX_CAPTURE_SOURCES) break;
    const kind = captureSourceKind(source.id);
    if (!kind || source.thumbnail.isEmpty()) continue;
    const size = source.thumbnail.getSize();
    const previewDataUrl = source.thumbnail.toDataURL();
    if (previewDataUrl.length > 384_000) continue;
    candidates.push({
      sourceId: source.id,
      name: captureSourceName(source.name, index),
      kind,
      previewDataUrl,
      previewWidth: size.width,
      previewHeight: size.height,
    });
  }
  return captureGrantStore.issue(candidates);
}

function encodeBoundedCapture(
  source: NativeImage,
  maxSide: CaptureMaxSide,
): {
  png: Uint8Array;
  width: number;
  height: number;
} {
  if (source.isEmpty()) {
    throw new Error("E_DESKTOP_CAPTURE_IMAGE: selected source returned no image");
  }
  const sourceSize = source.getSize();
  let size = fitWithinLongEdge(sourceSize.width, sourceSize.height, maxSide);
  let image = (
    size.width === sourceSize.width && size.height === sourceSize.height
      ? source
      : source.resize({ ...size, quality: "best" })
  );
  for (let attempt = 0; attempt < 6; attempt += 1) {
    const png = image.toPNG();
    if (png.byteLength <= 1_000_000) {
      return {
        png: new Uint8Array(png),
        width: size.width,
        height: size.height,
      };
    }
    size = {
      width: Math.max(64, Math.round(size.width * 0.75)),
      height: Math.max(64, Math.round(size.height * 0.75)),
    };
    image = source.resize({ ...size, quality: "best" });
  }
  throw new Error("E_DESKTOP_CAPTURE_IMAGE: cannot encode snapshot below 1 MB");
}

async function submitDesktopCapture(
  raw: unknown,
  onProgress?: (progress: CaptureProgress) => void,
): Promise<Record<string, unknown>> {
  await requirePerceptionFeatureEnabled();
  const request = validateFullFrameCaptureRequest(raw);
  const grant = captureGrantStore.consume(
    request.grantSessionId,
    request.sourceToken,
  );
  const totalStartedAt = performance.now();
  onProgress?.({
    phase: "capturing",
    requestedMaxSide: request.maxSide,
    sourceName: grant.name,
  });
  const sourceLookupStartedAt = performance.now();
  let sources: Awaited<ReturnType<typeof desktopCapturer.getSources>>;
  try {
    sources = await desktopCapturer.getSources({
      types: [grant.kind],
      thumbnailSize: {
        width: request.maxSide,
        height: request.maxSide,
      },
      fetchWindowIcons: false,
    });
  } catch {
    throw new Error("E_DESKTOP_CAPTURE_IMAGE: selected source cannot be captured");
  }
  const selected = sources.find((source) => source.id === grant.sourceId);
  if (!selected || selected.thumbnail.isEmpty()) {
    throw new Error(
      "E_DESKTOP_CAPTURE_SOURCE: selected source disappeared; refresh the source list",
    );
  }
  const sourceLookupMilliseconds = captureElapsedMilliseconds(sourceLookupStartedAt);
  onProgress?.({
    phase: "encoding",
    requestedMaxSide: request.maxSide,
    sourceName: grant.name,
  });
  const encodingStartedAt = performance.now();
  const encoded = encodeBoundedCapture(selected.thumbnail, request.maxSide);
  const encodingMilliseconds = captureElapsedMilliseconds(encodingStartedAt);
  onProgress?.({
    phase: "analyzing",
    requestedMaxSide: request.maxSide,
    sourceName: grant.name,
    width: encoded.width,
    height: encoded.height,
    bytes: encoded.png.byteLength,
  });
  const runtimeStartedAt = performance.now();
  const result = await requestPerceptionSnapshot(encoded.png, {
    sessionId: request.sessionId,
    label: request.label,
    analyzeVision: request.analyzeVision,
    visionQuestion: request.visionQuestion,
  });
  const runtimeMilliseconds = captureElapsedMilliseconds(runtimeStartedAt);
  return {
    ...result,
    desktopCapture: {
      sourceName: grant.name,
      sourceKind: grant.kind,
      fullFrame: true,
      requestedMaxSide: request.maxSide,
      width: encoded.width,
      height: encoded.height,
      bytes: encoded.png.byteLength,
      automatic: false,
      persistedByDesktop: false,
      timings: {
        sourceLookupMilliseconds,
        encodingMilliseconds,
        runtimeMilliseconds,
        totalMilliseconds: captureElapsedMilliseconds(totalStartedAt),
      },
    },
  };
}

function availableWorkAreas(): WorkArea[] {
  return screen.getAllDisplays().map((display) => ({
    x: display.workArea.x,
    y: display.workArea.y,
    width: display.workArea.width,
    height: display.workArea.height,
  }));
}

function primaryWidgetPosition(): Point {
  return defaultWidgetPosition(
    screen.getPrimaryDisplay().workArea,
    WIDGET_SIZE,
  );
}

function widgetStatePath(): string {
  return join(app.getPath("userData"), WIDGET_STATE_FILENAME);
}

function vtubeStudioTokenPath(): string {
  return join(app.getPath("userData"), VTS_TOKEN_STATE_FILENAME);
}

function visionProviderStatePath(): string {
  return join(app.getPath("userData"), VISION_PROVIDER_STATE_FILENAME);
}

type LoadedVisionProviderState = {
  persisted: PersistedVisionProviderState;
  apiKey: string | null;
};

async function loadVisionProviderState(): Promise<LoadedVisionProviderState> {
  let raw: string;
  try {
    const path = visionProviderStatePath();
    const details = await stat(path);
    if (details.size > VISION_PROVIDER_STATE_MAX_BYTES) {
      throw new Error("E_DESKTOP_VISION_STATE: persisted state is oversized");
    }
    raw = await readFile(path, "utf8");
  } catch (error) {
    if (
      error
      && typeof error === "object"
      && "code" in error
      && error.code === "ENOENT"
    ) {
      return {
        persisted: {
          schemaVersion: 1,
          provider: "disabled",
          model: null,
          encryptedApiKey: null,
        },
        apiKey: null,
      };
    }
    throw new Error("E_DESKTOP_VISION_STATE: cannot read persisted provider state");
  }
  const persisted = parseVisionProviderState(raw);
  if (!persisted) {
    throw new Error("E_DESKTOP_VISION_STATE: persisted provider state is invalid");
  }
  let apiKey: string | null = null;
  if (persisted.encryptedApiKey !== null) {
    if (!safeStorage.isEncryptionAvailable()) {
      throw new Error("E_DESKTOP_VISION_ENCRYPTION: OS secret storage is unavailable");
    }
    try {
      apiKey = validateVisionApiKey(
        safeStorage.decryptString(
          Buffer.from(persisted.encryptedApiKey, "base64"),
        ),
      );
    } catch {
      throw new Error("E_DESKTOP_VISION_ENCRYPTION: stored API key cannot be decrypted");
    }
  }
  return { persisted, apiKey };
}

async function saveVisionProviderState(
  provider: "ollama_local" | "ollama_cloud",
  model: string,
  apiKey: string | null,
  previousEncryptedKey: string | null,
): Promise<void> {
  let encryptedApiKey = previousEncryptedKey;
  if (apiKey !== null) {
    if (!safeStorage.isEncryptionAvailable()) {
      throw new Error("E_DESKTOP_VISION_ENCRYPTION: OS secret storage is unavailable");
    }
    encryptedApiKey = safeStorage.encryptString(
      validateVisionApiKey(apiKey),
    ).toString("base64");
  }
  const state: PersistedVisionProviderState = {
    schemaVersion: 1,
    provider,
    model: validateVisionModel(model),
    encryptedApiKey,
  };
  const path = visionProviderStatePath();
  await mkdir(dirname(path), { recursive: true });
  await writeFile(path, serializeVisionProviderState(state), {
    encoding: "utf8",
    mode: 0o600,
  });
}

async function clearPersistedVisionApiKey(): Promise<void> {
  const current = await loadVisionProviderState();
  const state: PersistedVisionProviderState = current.persisted.provider === "ollama_local"
    ? {
      ...current.persisted,
      encryptedApiKey: null,
    }
    : {
      schemaVersion: 1,
      provider: "disabled",
      model: null,
      encryptedApiKey: null,
    };
  const path = visionProviderStatePath();
  await mkdir(dirname(path), { recursive: true });
  await writeFile(path, serializeVisionProviderState(state), {
    encoding: "utf8",
    mode: 0o600,
  });
}

async function syncPersistedVisionProvider(): Promise<Record<string, unknown> | null> {
  const state = await loadVisionProviderState();
  if (state.persisted.provider === "disabled" || state.persisted.model === null) {
    return null;
  }
  return requestVisionConfigure(
    state.persisted.provider,
    state.persisted.model,
    state.apiKey,
  );
}

function scheduleVisionProviderRestore(attempt = 0): void {
  if (visionRestoreTimer || shutdownPending) return;
  visionRestoreTimer = setTimeout(() => {
    visionRestoreTimer = null;
    void syncPersistedVisionProvider().catch((error) => {
      const message = error instanceof Error ? error.message : "E_DESKTOP_VISION_RESTORE";
      console.warn(`[hina-desktop] ${message.split(":")[0]}`);
      if (attempt < 7 && message.includes("E_DESKTOP_CONTROL_OFFLINE")) {
        scheduleVisionProviderRestore(attempt + 1);
      }
    });
  }, attempt === 0 ? 0 : Math.min(1_000 * 2 ** (attempt - 1), 30_000));
}

function getVTubeStudioClient(): VTubeStudioClient {
  if (vtubeStudioClient) return vtubeStudioClient;
  vtubeStudioClient = new VTubeStudioClient({
    async load(): Promise<string | null> {
      try {
        const path = vtubeStudioTokenPath();
        const details = await stat(path);
        if (details.size > VTS_TOKEN_STATE_MAX_BYTES) return null;
        return parseVTubeStudioTokenState(await readFile(path, "utf8"));
      } catch (error) {
        if (
          error
          && typeof error === "object"
          && "code" in error
          && error.code === "ENOENT"
        ) {
          return null;
        }
        console.warn("[hina-desktop] E_VTS_TOKEN_READ");
        return null;
      }
    },
    async save(token: string): Promise<void> {
      const path = vtubeStudioTokenPath();
      await mkdir(dirname(path), { recursive: true });
      await writeFile(path, serializeVTubeStudioTokenState(token), "utf8");
    },
    async clear(): Promise<void> {
      try {
        await unlink(vtubeStudioTokenPath());
      } catch (error) {
        if (
          !error
          || typeof error !== "object"
          || !("code" in error)
          || error.code !== "ENOENT"
        ) {
          console.warn("[hina-desktop] E_VTS_TOKEN_CLEAR");
        }
      }
    },
  });
  return vtubeStudioClient;
}

function getSpoutBridge(): SpoutBridge {
  if (spoutBridge) return spoutBridge;
  const smoke = process.env.HINA_DESKTOP_SMOKE === "1";
  spoutBridge = new SpoutBridge({
    repoRoot: join(__dirname, "..", "..", ".."),
    enabled: !smoke || process.env.HINA_DESKTOP_SMOKE_SPOUT === "1",
    uvPath: process.env.HINA_UV_PATH || undefined,
    log: (level, message) => {
      if (level === "error") {
        console.error(message);
      } else if (level === "warn") {
        console.warn(message);
      } else {
        console.log(message);
      }
    },
  });
  return spoutBridge;
}

async function loadWidgetPosition(): Promise<Point> {
  const fallback = primaryWidgetPosition();
  if (process.env.HINA_DESKTOP_SMOKE === "1") return fallback;
  try {
    const path = widgetStatePath();
    const details = await stat(path);
    if (details.size > WIDGET_STATE_MAX_BYTES) {
      console.warn("[hina-desktop] E_DESKTOP_WIDGET_STATE_OVERSIZED");
      return fallback;
    }
    const parsed = parseWidgetPosition(await readFile(path, "utf8"));
    if (!parsed) {
      console.warn("[hina-desktop] E_DESKTOP_WIDGET_STATE_INVALID");
      return fallback;
    }
    return clampWidgetPosition(parsed, WIDGET_SIZE, availableWorkAreas());
  } catch (error) {
    if (
      error
      && typeof error === "object"
      && "code" in error
      && error.code === "ENOENT"
    ) {
      return fallback;
    }
    console.warn("[hina-desktop] E_DESKTOP_WIDGET_STATE_READ");
    return fallback;
  }
}

async function persistWidgetPosition(): Promise<void> {
  if (
    process.env.HINA_DESKTOP_SMOKE === "1"
    || !widgetWindow
    || widgetWindow.isDestroyed()
  ) {
    return;
  }
  try {
    const [x = 0, y = 0] = widgetWindow.getPosition();
    const path = widgetStatePath();
    await mkdir(dirname(path), { recursive: true });
    await writeFile(path, serializeWidgetPosition({ x, y }), "utf8");
  } catch {
    console.error("[hina-desktop] E_DESKTOP_WIDGET_STATE_WRITE");
  }
}

function scheduleWidgetPositionWrite(): void {
  if (process.env.HINA_DESKTOP_SMOKE === "1") return;
  if (widgetPositionTimer) {
    clearTimeout(widgetPositionTimer);
  }
  widgetPositionTimer = setTimeout(() => {
    widgetPositionTimer = null;
    void persistWidgetPosition();
  }, 250);
}

function sendWidgetHover(inside: boolean): void {
  widgetHoverInside = inside;
  if (widgetWindow && !widgetWindow.isDestroyed()) {
    widgetWindow.webContents.send(CHANNELS.widgetHover, inside);
  }
}

function pollWidgetHover(): void {
  if (!widgetWindow || widgetWindow.isDestroyed() || !widgetWindow.isVisible()) {
    if (widgetHoverInside) sendWidgetHover(false);
    return;
  }
  const cursor = screen.getCursorScreenPoint();
  const bounds = widgetWindow.getBounds();
  const inside =
    cursor.x >= bounds.x
    && cursor.x < bounds.x + bounds.width
    && cursor.y >= bounds.y
    && cursor.y < bounds.y + bounds.height;
  if (inside !== widgetHoverInside) {
    sendWidgetHover(inside);
  }
}

// The widget avatar surface uses -webkit-app-region: drag, which Windows treats
// as non-client area: the renderer never receives real mouse events there, so
// CSS :hover/pointerenter cannot reveal the Voice/Mic controls. The main
// process watches the OS cursor against the window bounds instead and pushes
// hover state to the widget renderer over IPC.
function startWidgetHoverWatcher(): void {
  if (process.env.HINA_DESKTOP_SMOKE === "1" || widgetHoverTimer) return;
  widgetHoverTimer = setInterval(pollWidgetHover, 130);
}

function stopWidgetHoverWatcher(): void {
  if (widgetHoverTimer) {
    clearInterval(widgetHoverTimer);
    widgetHoverTimer = null;
  }
}

function validateWidgetControl(value: unknown): WidgetControlAction {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new Error("E_DESKTOP_WIDGET_CONTROL: control must be an object");
  }
  const record = value as Record<string, unknown>;
  if (
    Object.keys(record).join(",") !== "action"
    || !["show", "hide", "reset_position"].includes(String(record.action))
  ) {
    throw new Error("E_DESKTOP_WIDGET_CONTROL: action is not allowlisted");
  }
  return record.action as WidgetControlAction;
}

function getWidgetStatus(): {
  available: true;
  visible: boolean;
  alwaysOnTop: boolean;
  position: Point;
} {
  if (!widgetWindow || widgetWindow.isDestroyed()) {
    throw new Error("E_DESKTOP_WIDGET_WINDOW: widget window is unavailable");
  }
  const [x = 0, y = 0] = widgetWindow.getPosition();
  return {
    available: true,
    visible: widgetWindow.isVisible(),
    alwaysOnTop: widgetWindow.isAlwaysOnTop(),
    position: { x, y },
  };
}

function assertTrustedSender(event: IpcMainInvokeEvent): DesktopWindowMode {
  if (event.senderFrame !== event.sender.mainFrame) {
    throw new Error("E_DESKTOP_IPC_SENDER: IPC is limited to the desktop main frame");
  }
  if (mainWindow && event.sender === mainWindow.webContents) {
    return "operator";
  }
  if (widgetWindow && event.sender === widgetWindow.webContents) {
    return "widget";
  }
  throw new Error("E_DESKTOP_IPC_SENDER: IPC is limited to a known desktop window");
}

function hardenWindow(target: BrowserWindow): void {
  target.webContents.setWindowOpenHandler(() => ({ action: "deny" }));
  target.webContents.on("will-navigate", (event, url) => {
    if (url !== target.webContents.getURL()) {
      event.preventDefault();
    }
  });
  target.webContents.on("will-attach-webview", (event) => {
    event.preventDefault();
  });
}

function attachRendererConsoleLogging(target: BrowserWindow, name: "operator" | "widget"): void {
  target.webContents.on("console-message", (details) => {
    if (details.message.includes("frame-ancestors") && details.message.includes("ignored")) {
      return;
    }
    if (details.level !== "warning" && details.level !== "error") return;
    const prefix = details.level === "error" ? "ERROR" : "WARN";
    console.error(
      `[hina-renderer:${name}:${prefix}] ${details.message.slice(0, 512)} ` +
      `(source=${details.sourceId.slice(0, 160)}:${details.lineNumber})`,
    );
  });
  target.webContents.on("render-process-gone", (_event, details) => {
    console.error(`[hina-renderer:${name}:GONE] reason=${details.reason} exitCode=${details.exitCode}`);
  });
}

function registerIpcHandlers(): void {
  ipcMain.handle(CHANNELS.windowMode, (event) => assertTrustedSender(event));
  ipcMain.handle(CHANNELS.widgetStatus, (event) => {
    if (assertTrustedSender(event) !== "operator") {
      throw new Error("E_DESKTOP_WIDGET_AUTHORITY: operator window required");
    }
    return getWidgetStatus();
  });
  ipcMain.handle(CHANNELS.widgetControl, (event, control: unknown) => {
    if (assertTrustedSender(event) !== "operator") {
      throw new Error("E_DESKTOP_WIDGET_AUTHORITY: operator window required");
    }
    if (!widgetWindow || widgetWindow.isDestroyed()) {
      throw new Error("E_DESKTOP_WIDGET_WINDOW: widget window is unavailable");
    }
    const action = validateWidgetControl(control);
    if (action === "hide") {
      widgetWindow.hide();
    } else if (action === "show") {
      widgetWindow.setAlwaysOnTop(true, "floating");
      widgetWindow.showInactive();
    } else {
      const position = primaryWidgetPosition();
      widgetWindow.setPosition(position.x, position.y, false);
      widgetWindow.setAlwaysOnTop(true, "floating");
      widgetWindow.showInactive();
      scheduleWidgetPositionWrite();
    }
    return getWidgetStatus();
  });
  ipcMain.handle(CHANNELS.avatarStatus, (event) => {
    assertTrustedSender(event);
    return requestControl("avatar.status");
  });
  ipcMain.handle(CHANNELS.avatarCue, (event, cue: unknown) => {
    assertTrustedSender(event);
    return requestControl("avatar.cue", validateAvatarCue(cue));
  });
  ipcMain.handle(CHANNELS.avatarReset, (event) => {
    assertTrustedSender(event);
    return requestControl("avatar.reset", { action: "reset" });
  });
  ipcMain.handle(CHANNELS.safetyStatus, (event) => {
    assertTrustedSender(event);
    return requestControl("safety.status");
  });
  ipcMain.handle(CHANNELS.safetyControl, (event, control: unknown) => {
    const mode = assertTrustedSender(event);
    const validated = validateSafetyControl(control);
    if (validated.action === "set_feature" && mode !== "operator") {
      throw new Error("E_DESKTOP_CAPTURE_AUTHORITY: operator window required");
    }
    return requestControl("safety.control", {
      ...validated,
      actorId: "owner.desktop",
      trustLevel: "owner",
      correlationId: crypto.randomUUID(),
    });
  });
  ipcMain.handle(CHANNELS.runtimeHealth, (event) => {
    assertTrustedSender(event);
    return requestControl("runtime.health");
  });
  ipcMain.handle(CHANNELS.resourcesStatus, async (event) => {
    if (assertTrustedSender(event) !== "operator") {
      throw new Error("E_DESKTOP_RESOURCE_AUTHORITY: operator window required");
    }
    const status = await requestControl("resources.status");
    return augmentResourceStatus(status, resourceTransitionTracker);
  });
  ipcMain.handle(
    CHANNELS.resourcesControl,
    async (event, modelId: unknown, action: unknown) => {
      if (assertTrustedSender(event) !== "operator") {
        throw new Error("E_DESKTOP_RESOURCE_AUTHORITY: operator window required");
      }
      try {
        const result = await requestResourceModelControl(modelId, action);
        const resources = result.resources;
        return resources && typeof resources === "object"
          ? {
              ...result,
              resources: augmentResourceStatus(
                resources,
                resourceTransitionTracker,
              ),
            }
          : result;
      } catch (error) {
        console.error(
          `[hina-desktop:resources:ERROR] ${
            error instanceof Error ? error.message.slice(0, 256) : "resource model control failed"
          }`,
        );
        throw error;
      }
    },
  );
  ipcMain.handle(CHANNELS.captureSources, async (event) => {
    if (assertTrustedSender(event) !== "operator") {
      throw new Error("E_DESKTOP_CAPTURE_AUTHORITY: operator window required");
    }
    try {
      return await listDesktopCaptureSources();
    } catch (error) {
      console.error(
        `[hina-desktop:capture:ERROR] ${
          error instanceof Error ? error.message.slice(0, 256) : "E_DESKTOP_CAPTURE_SOURCES"
        }`,
      );
      throw error;
    }
  });
  ipcMain.handle(CHANNELS.captureSubmit, async (event, input: unknown) => {
    if (assertTrustedSender(event) !== "operator") {
      throw new Error("E_DESKTOP_CAPTURE_AUTHORITY: operator window required");
    }
    try {
      return await submitDesktopCapture(input, (progress) => {
        event.sender.send(CHANNELS.captureProgress, progress);
      });
    } catch (error) {
      console.error(
        `[hina-desktop:capture:ERROR] ${
          error instanceof Error ? error.message.slice(0, 256) : "E_DESKTOP_CAPTURE_IMAGE"
        }`,
      );
      throw error;
    }
  });
  ipcMain.handle(CHANNELS.chatStatus, (event) => {
    assertTrustedSender(event);
    return requestChatStatus();
  });
  ipcMain.handle(CHANNELS.chatStart, (event, payload: unknown) => {
    assertTrustedSender(event);
    return requestChatStart(payload);
  });
  ipcMain.handle(CHANNELS.chatTurn, (event, turnId: unknown) => {
    assertTrustedSender(event);
    return requestChatTurn(turnId);
  });
  ipcMain.handle(CHANNELS.chatCancel, (event, turnId: unknown) => {
    assertTrustedSender(event);
    return requestChatCancel(turnId);
  });
  ipcMain.handle(
    CHANNELS.speechTranscribe,
    (event, audio: unknown, sessionId: unknown) => {
      assertTrustedSender(event);
      return requestSpeechTranscription(audio, sessionId);
    },
  );
  ipcMain.handle(CHANNELS.speechStatus, (event) => {
    assertTrustedSender(event);
    return requestControl("speech.status");
  });
  ipcMain.handle(CHANNELS.ttsStatus, (event) => {
    assertTrustedSender(event);
    return requestControl("tts.status");
  });
  ipcMain.handle(CHANNELS.ttsSynthesize, (event, payload: unknown) => {
    assertTrustedSender(event);
    return requestSpeechSynthesis(payload);
  });
  ipcMain.handle(CHANNELS.visionStatus, async (event) => {
    if (assertTrustedSender(event) !== "operator") {
      throw new Error("E_DESKTOP_VISION_AUTHORITY: operator window required");
    }
    const stored = await loadVisionProviderState();
    let runtimeStatus = await requestVisionStatus();
    const runtimeVision = runtimeStatus.vision;
    const runtimeVisionRecord = (
      runtimeVision
      && typeof runtimeVision === "object"
      && !Array.isArray(runtimeVision)
    )
      ? runtimeVision as Record<string, unknown>
      : null;
    if (
      stored.persisted.provider !== "disabled"
      && stored.persisted.model !== null
      && (
        runtimeVisionRecord === null
        || runtimeVisionRecord.provider !== stored.persisted.provider
        || runtimeVisionRecord.model !== stored.persisted.model
        || runtimeVisionRecord.available !== true
        || (
          stored.persisted.provider === "ollama_cloud"
          && stored.apiKey !== null
          && runtimeVisionRecord.apiKeyConfigured !== true
        )
      )
    ) {
      await syncPersistedVisionProvider();
      runtimeStatus = await requestVisionStatus();
    }
    return {
      runtime: runtimeStatus.vision,
      persistence: {
        provider: stored.persisted.provider,
        model: stored.persisted.model,
        apiKeyConfigured: stored.apiKey !== null,
        encryptedWithOsStorage: (
          stored.persisted.encryptedApiKey !== null
          && safeStorage.isEncryptionAvailable()
        ),
        rendererCanReadStoredKey: false,
      },
    };
  });
  ipcMain.handle(CHANNELS.visionDiscover, async (event, input: unknown) => {
    if (assertTrustedSender(event) !== "operator") {
      throw new Error("E_DESKTOP_VISION_AUTHORITY: operator window required");
    }
    if (!input || typeof input !== "object" || Array.isArray(input)) {
      throw new Error("E_DESKTOP_VISION_CONFIG: discovery input is invalid");
    }
    const record = input as Record<string, unknown>;
    if (
      Object.keys(record).some((key) => !["provider", "apiKey"].includes(key))
      || !("provider" in record)
    ) {
      throw new Error("E_DESKTOP_VISION_CONFIG: discovery fields are invalid");
    }
    const provider = validateVisionProvider(record.provider);
    const stored = await loadVisionProviderState();
    const supplied = typeof record.apiKey === "string" && record.apiKey.length > 0
      ? validateVisionApiKey(record.apiKey)
      : null;
    const apiKey = provider === "ollama_cloud"
      ? supplied ?? stored.apiKey
      : null;
    return requestVisionModelDiscovery(provider, apiKey);
  });
  ipcMain.handle(CHANNELS.visionConfigure, async (event, input: unknown) => {
    if (assertTrustedSender(event) !== "operator") {
      throw new Error("E_DESKTOP_VISION_AUTHORITY: operator window required");
    }
    if (!input || typeof input !== "object" || Array.isArray(input)) {
      throw new Error("E_DESKTOP_VISION_CONFIG: configuration input is invalid");
    }
    const record = input as Record<string, unknown>;
    if (
      Object.keys(record).some((key) => !["provider", "model", "apiKey"].includes(key))
      || !("provider" in record)
      || !("model" in record)
    ) {
      throw new Error("E_DESKTOP_VISION_CONFIG: configuration fields are invalid");
    }
    const provider = validateVisionProvider(record.provider);
    const model = validateVisionModel(record.model);
    const stored = await loadVisionProviderState();
    const supplied = typeof record.apiKey === "string" && record.apiKey.length > 0
      ? validateVisionApiKey(record.apiKey)
      : null;
    const apiKey = provider === "ollama_cloud"
      ? supplied ?? stored.apiKey
      : null;
    if (
      provider === "ollama_cloud"
      && !safeStorage.isEncryptionAvailable()
    ) {
      throw new Error("E_DESKTOP_VISION_ENCRYPTION: OS secret storage is unavailable");
    }
    const runtime = await requestVisionConfigure(provider, model, apiKey);
    await saveVisionProviderState(
      provider,
      model,
      provider === "ollama_cloud" ? supplied : null,
      stored.persisted.encryptedApiKey,
    );
    return {
      runtime,
      persistence: {
        provider,
        model,
        apiKeyConfigured: apiKey !== null,
        encryptedWithOsStorage: apiKey !== null,
        rendererCanReadStoredKey: false,
      },
    };
  });
  ipcMain.handle(CHANNELS.visionClearKey, async (event) => {
    if (assertTrustedSender(event) !== "operator") {
      throw new Error("E_DESKTOP_VISION_AUTHORITY: operator window required");
    }
    const stored = await loadVisionProviderState();
    const runtimePreserved = stored.persisted.provider === "ollama_local";
    let runtimeDisabled = false;
    if (!runtimePreserved) {
      try {
        await requestVisionDisable();
        runtimeDisabled = true;
      } catch (error) {
        if (
          !(error instanceof Error)
          || !error.message.includes("E_DESKTOP_CONTROL_OFFLINE")
        ) {
          throw error;
        }
      }
    }
    await clearPersistedVisionApiKey();
    return {
      apiKeyConfigured: false,
      persisted: false,
      runtimeDisabled,
      runtimePreserved,
    };
  });
  ipcMain.handle(CHANNELS.vtubeStatus, (event) => {
    if (assertTrustedSender(event) !== "operator") {
      throw new Error("E_VTS_AUTHORITY: operator window required");
    }
    return getVTubeStudioClient().status();
  });
  ipcMain.handle(CHANNELS.vtubeConnect, (event) => {
    if (assertTrustedSender(event) !== "operator") {
      throw new Error("E_VTS_AUTHORITY: operator window required");
    }
    return getVTubeStudioClient().connect(true);
  });
  ipcMain.handle(CHANNELS.vtubeDisconnect, (event) => {
    if (assertTrustedSender(event) !== "operator") {
      throw new Error("E_VTS_AUTHORITY: operator window required");
    }
    return getVTubeStudioClient().disconnect();
  });
  ipcMain.handle(CHANNELS.vtubeRefresh, (event) => {
    if (assertTrustedSender(event) !== "operator") {
      throw new Error("E_VTS_AUTHORITY: operator window required");
    }
    return getVTubeStudioClient().refresh();
  });
  ipcMain.handle(CHANNELS.vtubeHotkey, (event, hotkeyId: unknown) => {
    if (assertTrustedSender(event) !== "operator") {
      throw new Error("E_VTS_AUTHORITY: operator window required");
    }
    return getVTubeStudioClient().triggerHotkey(hotkeyId);
  });
  ipcMain.handle(CHANNELS.vtubeMove, (event, preset: unknown) => {
    if (assertTrustedSender(event) !== "operator") {
      throw new Error("E_VTS_AUTHORITY: operator window required");
    }
    return getVTubeStudioClient().moveModel(preset);
  });
  ipcMain.handle(CHANNELS.spoutStatus, (event): SpoutBridgeStatus => {
    assertTrustedSender(event);
    return getSpoutBridge().status();
  });
}

function registerMediaPermissions(): void {
  const isKnownWindow = (webContents: Electron.WebContents): boolean => (
    (mainWindow !== null && webContents === mainWindow.webContents)
    || (widgetWindow !== null && webContents === widgetWindow.webContents)
  );
  session.defaultSession.setPermissionCheckHandler(
    (webContents, permission, _origin, details) => (
      permission === "media"
      && details.mediaType === "audio"
      && webContents !== null
      && isKnownWindow(webContents)
    ),
  );
  session.defaultSession.setPermissionRequestHandler(
    (webContents, permission, callback, details) => {
      const mediaTypes = "mediaTypes" in details ? details.mediaTypes : undefined;
      callback(
        permission === "media"
        && mediaTypes?.includes("audio") === true
        && mediaTypes.includes("video") === false
        && isKnownWindow(webContents),
      );
    },
  );
}

async function createWindows(): Promise<void> {
  const smoke = process.env.HINA_DESKTOP_SMOKE === "1";
  const smokeSpout =
    smoke && process.env.HINA_DESKTOP_SMOKE_SPOUT === "1";
  const rendererPath = join(__dirname, "..", "dist", "index.html");
  const preloadPath = join(__dirname, "preload.js");
  const widgetWidth = 440;
  const widgetHeight = 620;
  const widgetPosition = await loadWidgetPosition();
  mainWindow = new BrowserWindow({
    width: 1280,
    height: 800,
    minWidth: 900,
    minHeight: 620,
    show: true,
    opacity: smoke ? 0 : 1,
    skipTaskbar: smoke,
    focusable: !smoke,
    backgroundColor: "#0d0c11",
    autoHideMenuBar: true,
    title: "Hina Avatar Stage",
    webPreferences: {
      preload: preloadPath,
      nodeIntegration: false,
      contextIsolation: true,
      sandbox: true,
      webSecurity: true,
      webviewTag: false,
      allowRunningInsecureContent: false,
      backgroundThrottling: false,
    },
  });
  widgetWindow = new BrowserWindow({
    x: widgetPosition.x,
    y: widgetPosition.y,
    width: widgetWidth,
    height: widgetHeight,
    frame: false,
    transparent: true,
    hasShadow: false,
    resizable: false,
    movable: true,
    minimizable: false,
    maximizable: false,
    fullscreenable: false,
    alwaysOnTop: true,
    skipTaskbar: true,
    show: true,
    opacity: smoke ? 0 : 1,
    backgroundColor: "#00000000",
    autoHideMenuBar: true,
    title: "Hina Desktop Widget",
    webPreferences: {
      preload: preloadPath,
      nodeIntegration: false,
      contextIsolation: true,
      sandbox: true,
      webSecurity: true,
      webviewTag: false,
      allowRunningInsecureContent: false,
      backgroundThrottling: false,
    },
  });
  widgetWindow.setAlwaysOnTop(true, "floating");
  widgetWindow.setVisibleOnAllWorkspaces(true, { visibleOnFullScreen: true });

  hardenWindow(mainWindow);
  hardenWindow(widgetWindow);
  attachRendererConsoleLogging(mainWindow, "operator");
  attachRendererConsoleLogging(widgetWindow, "widget");
  mainWindow.on("closed", () => {
    mainWindow = null;
    if (widgetWindow && !widgetWindow.isDestroyed()) {
      widgetWindow.close();
    }
  });
  widgetWindow.on("closed", () => {
    widgetWindow = null;
    stopWidgetHoverWatcher();
    widgetHoverInside = false;
    if (widgetPositionTimer) {
      clearTimeout(widgetPositionTimer);
      widgetPositionTimer = null;
    }
  });
  widgetWindow.on("close", () => {
    if (widgetPositionTimer) {
      clearTimeout(widgetPositionTimer);
      widgetPositionTimer = null;
    }
    void persistWidgetPosition();
  });
  widgetWindow.on("move", scheduleWidgetPositionWrite);
  widgetWindow.webContents.on("did-finish-load", () => {
    // Renderer state resets on load; force the next poll to re-send hover.
    widgetHoverInside = false;
  });

  if (smoke) {
    const widgetLoaded = new Promise<void>((resolve, reject) => {
      widgetWindow?.webContents.once("did-fail-load", (_event, code, description) => {
        reject(new Error(
          `E_DESKTOP_WIDGET_LOAD: ${code} ${description.slice(0, 120)}`,
        ));
      });
      widgetWindow?.webContents.once("did-finish-load", () => resolve());
    });
    mainWindow.webContents.once("did-fail-load", (_event, code, description) => {
      console.error(JSON.stringify({
        status: "error",
        errorCode: "E_DESKTOP_RENDERER_LOAD",
        code,
        description: description.slice(0, 160),
      }));
      app.exit(1);
    });
    mainWindow.webContents.once("did-finish-load", async () => {
      try {
        await widgetLoaded;
        const snapshot: unknown = await mainWindow?.webContents.executeJavaScript(
          `(() => {
            const vrmReady = new Promise((resolve, reject) => {
              const deadline = Date.now() + 25000;
              const check = () => {
                if (document.documentElement.dataset.vrmReady === "true") {
                  resolve(true);
                  return;
                }
                if (document.documentElement.dataset.vrmError) {
                  reject(new Error(document.documentElement.dataset.vrmError));
                  return;
                }
                if (Date.now() >= deadline) {
                  reject(new Error("E_DESKTOP_VRM_SMOKE_TIMEOUT"));
                  return;
                }
                setTimeout(check, 50);
              };
              check();
            });
            const performance = new Promise((resolve, reject) => {
              const deadline = Date.now() + 25000;
              const check = () => {
                const sampleCount = Number(
                  document.documentElement.dataset.vrmSampleCount
                );
                if (Number.isFinite(sampleCount) && sampleCount >= 30) {
                  resolve({
                    fps: Number(document.documentElement.dataset.vrmFps),
                    frameTimeP95Ms: Number(
                      document.documentElement.dataset.vrmFrameP95
                    ),
                    frameTimeP99Ms: Number(
                      document.documentElement.dataset.vrmFrameP99
                    ),
                    droppedFramePercent: Number(
                      document.documentElement.dataset.vrmDroppedPercent
                    ),
                    sampleCount
                  });
                  return;
                }
                if (document.documentElement.dataset.vrmError) {
                  reject(new Error(document.documentElement.dataset.vrmError));
                  return;
                }
                if (Date.now() >= deadline) {
                  reject(new Error("E_DESKTOP_PERFORMANCE_SMOKE_TIMEOUT"));
                  return;
                }
                setTimeout(check, 50);
              };
              check();
            });
            return Promise.all([
              window.hinaDesktop.getRuntimeHealth(),
              window.hinaDesktop.getAvatarStatus(),
              window.hinaDesktop.getWidgetStatus(),
              vrmReady,
              performance,
              window.hinaDesktop.getVisionProviderStatus()
            ]).then(async ([
              health,
              avatar,
              widgetStatus,
              vrmLoaded,
              performance,
              visionProvider
            ]) => {
              const presentation = document.documentElement.dataset.avatarPresentation;
              const loadedTextureCount = Number(
                document.documentElement.dataset.avatarTextureCount
              );
              const styledMaterialCount = Number(
                document.documentElement.dataset.avatarStyledMaterialCount
              );
              const canvas = document.querySelector("canvas.vrm-canvas");
              const context = canvas?.getContext("webgl2")
                || canvas?.getContext("webgl");
              const loseContext = context?.getExtension("WEBGL_lose_context");
              if (!loseContext) {
                throw new Error("E_DESKTOP_WEBGL_LOSS_EXTENSION");
              }
              loseContext.loseContext();
              await new Promise((resolve, reject) => {
                const deadline = Date.now() + 5000;
                const check = () => {
                  if (document.documentElement.dataset.vrmError) {
                    resolve(true);
                    return;
                  }
                  if (Date.now() >= deadline) {
                    reject(new Error("E_DESKTOP_WEBGL_FALLBACK_TIMEOUT"));
                    return;
                  }
                  setTimeout(check, 25);
                };
                check();
              });
              const retry = document.getElementById("retryVrmButton");
              if (!(retry instanceof HTMLButtonElement)) {
                throw new Error("E_DESKTOP_VRM_RETRY_CONTROL");
              }
              retry.click();
              await new Promise((resolve, reject) => {
                const deadline = Date.now() + 25000;
                const check = () => {
                  const recoveredSamples = Number(
                    document.documentElement.dataset.vrmSampleCount
                  );
                  if (
                    document.documentElement.dataset.vrmReady === "true"
                    && Number.isFinite(recoveredSamples)
                    && recoveredSamples >= 30
                  ) {
                    resolve(true);
                    return;
                  }
                  if (document.documentElement.dataset.vrmError) {
                    reject(new Error(document.documentElement.dataset.vrmError));
                    return;
                  }
                  if (Date.now() >= deadline) {
                    reject(new Error("E_DESKTOP_VRM_RECOVERY_TIMEOUT"));
                    return;
                  }
                  setTimeout(check, 50);
                };
                check();
              });
              const resourceTab = Array.from(
                document.querySelectorAll(".desktop-nav button")
              ).find((button) => button.textContent?.includes("Tài nguyên AI"));
              if (!(resourceTab instanceof HTMLButtonElement)) {
                throw new Error("E_DESKTOP_RESOURCE_PAGE_CONTROL");
              }
              resourceTab.click();
              await new Promise((resolve, reject) => {
                const deadline = Date.now() + 10000;
                const check = () => {
                  const sampleCount = Number(
                    document.documentElement.dataset.resourceSampleCount
                  );
                  if (
                    document.documentElement.dataset.resourceMonitorState
                    && Number.isFinite(sampleCount)
                    && sampleCount >= 1
                  ) {
                    resolve(true);
                    return;
                  }
                  if (Date.now() >= deadline) {
                    reject(new Error("E_DESKTOP_RESOURCE_PAGE_TIMEOUT"));
                    return;
                  }
                  setTimeout(check, 50);
                };
                check();
              });
              const resourceStatus = await window.hinaDesktop.getResourceStatus();
              return {
                runtime: health.status,
                avatarState: avatar.state,
                widgetStatus,
                vrmLoaded,
                presentation,
                loadedTextureCount,
                styledMaterialCount,
                performance,
                visionProvider,
                resourceStatus,
                resourcePage: {
                  state: document.documentElement.dataset.resourceMonitorState,
                  sampleCount: Number(
                    document.documentElement.dataset.resourceSampleCount
                  ),
                  modelCount: Number(
                    document.documentElement.dataset.resourceModelCount
                  )
                },
                recovery: {
                  webglContextLost: true,
                  svgFallbackObserved: true,
                  vrmReloaded: true
                }
              };
            });
          })()`,
          true,
        );
        if (
          !snapshot
          || typeof snapshot !== "object"
          || !("runtime" in snapshot)
          || typeof snapshot.runtime !== "string"
          || !("avatarState" in snapshot)
          || typeof snapshot.avatarState !== "string"
          || !("widgetStatus" in snapshot)
          || !snapshot.widgetStatus
          || typeof snapshot.widgetStatus !== "object"
          || !("available" in snapshot.widgetStatus)
          || snapshot.widgetStatus.available !== true
          || !("visible" in snapshot.widgetStatus)
          || snapshot.widgetStatus.visible !== true
          || !("alwaysOnTop" in snapshot.widgetStatus)
          || snapshot.widgetStatus.alwaysOnTop !== true
          || !("vrmLoaded" in snapshot)
          || snapshot.vrmLoaded !== true
          || !("presentation" in snapshot)
          || snapshot.presentation !== "hina-kawaii-v0.1"
          || !("loadedTextureCount" in snapshot)
          || typeof snapshot.loadedTextureCount !== "number"
          || !Number.isFinite(snapshot.loadedTextureCount)
          || snapshot.loadedTextureCount < 8
          || !("styledMaterialCount" in snapshot)
          || typeof snapshot.styledMaterialCount !== "number"
          || !Number.isFinite(snapshot.styledMaterialCount)
          || snapshot.styledMaterialCount < 13
          || !("performance" in snapshot)
          || !snapshot.performance
          || typeof snapshot.performance !== "object"
          || !("fps" in snapshot.performance)
          || typeof snapshot.performance.fps !== "number"
          || !Number.isFinite(snapshot.performance.fps)
          || snapshot.performance.fps <= 0
          || snapshot.performance.fps > 240
          || !("frameTimeP95Ms" in snapshot.performance)
          || typeof snapshot.performance.frameTimeP95Ms !== "number"
          || !Number.isFinite(snapshot.performance.frameTimeP95Ms)
          || snapshot.performance.frameTimeP95Ms <= 0
          || snapshot.performance.frameTimeP95Ms > 1_000
          || !("frameTimeP99Ms" in snapshot.performance)
          || typeof snapshot.performance.frameTimeP99Ms !== "number"
          || !Number.isFinite(snapshot.performance.frameTimeP99Ms)
          || snapshot.performance.frameTimeP99Ms > 1_000
          || snapshot.performance.frameTimeP99Ms
            < snapshot.performance.frameTimeP95Ms
          || !("droppedFramePercent" in snapshot.performance)
          || typeof snapshot.performance.droppedFramePercent !== "number"
          || !Number.isFinite(snapshot.performance.droppedFramePercent)
          || snapshot.performance.droppedFramePercent < 0
          || snapshot.performance.droppedFramePercent > 5
          || !("sampleCount" in snapshot.performance)
          || typeof snapshot.performance.sampleCount !== "number"
          || !Number.isFinite(snapshot.performance.sampleCount)
          || snapshot.performance.sampleCount < 30
          || snapshot.performance.sampleCount > 600
          || !("visionProvider" in snapshot)
          || !snapshot.visionProvider
          || typeof snapshot.visionProvider !== "object"
          || !("persistence" in snapshot.visionProvider)
          || !snapshot.visionProvider.persistence
          || typeof snapshot.visionProvider.persistence !== "object"
          || !("provider" in snapshot.visionProvider.persistence)
          || typeof snapshot.visionProvider.persistence.provider !== "string"
          || !("rendererCanReadStoredKey" in snapshot.visionProvider.persistence)
          || snapshot.visionProvider.persistence.rendererCanReadStoredKey !== false
          || !("runtime" in snapshot.visionProvider)
          || !snapshot.visionProvider.runtime
          || typeof snapshot.visionProvider.runtime !== "object"
          || !("resourceStatus" in snapshot)
          || !snapshot.resourceStatus
          || typeof snapshot.resourceStatus !== "object"
          || !("schemaVersion" in snapshot.resourceStatus)
          || snapshot.resourceStatus.schemaVersion !== "1.0"
          || !("models" in snapshot.resourceStatus)
          || !Array.isArray(snapshot.resourceStatus.models)
          || snapshot.resourceStatus.models.length < 4
          || !("physical" in snapshot.resourceStatus)
          || !snapshot.resourceStatus.physical
          || typeof snapshot.resourceStatus.physical !== "object"
          || !("processes" in snapshot.resourceStatus)
          || !snapshot.resourceStatus.processes
          || typeof snapshot.resourceStatus.processes !== "object"
          || !("coreRuntime" in snapshot.resourceStatus.processes)
          || !snapshot.resourceStatus.processes.coreRuntime
          || typeof snapshot.resourceStatus.processes.coreRuntime !== "object"
          || !("rssMiB" in snapshot.resourceStatus.processes.coreRuntime)
          || typeof snapshot.resourceStatus.processes.coreRuntime.rssMiB !== "number"
          || snapshot.resourceStatus.processes.coreRuntime.rssMiB <= 0
          || !("resourcePage" in snapshot)
          || !snapshot.resourcePage
          || typeof snapshot.resourcePage !== "object"
          || !("state" in snapshot.resourcePage)
          || typeof snapshot.resourcePage.state !== "string"
          || !("sampleCount" in snapshot.resourcePage)
          || typeof snapshot.resourcePage.sampleCount !== "number"
          || snapshot.resourcePage.sampleCount < 1
          || !("modelCount" in snapshot.resourcePage)
          || typeof snapshot.resourcePage.modelCount !== "number"
          || snapshot.resourcePage.modelCount < 4
          || !("recovery" in snapshot)
          || !snapshot.recovery
          || typeof snapshot.recovery !== "object"
          || !("webglContextLost" in snapshot.recovery)
          || snapshot.recovery.webglContextLost !== true
          || !("svgFallbackObserved" in snapshot.recovery)
          || snapshot.recovery.svgFallbackObserved !== true
          || !("vrmReloaded" in snapshot.recovery)
          || snapshot.recovery.vrmReloaded !== true
        ) {
          throw new Error(
            `E_DESKTOP_SMOKE_IPC: renderer returned an invalid snapshot ${
              JSON.stringify(snapshot).slice(0, 700)
            }`,
          );
        }
        if (!widgetWindow || widgetWindow.isDestroyed()) {
          throw new Error("E_DESKTOP_WIDGET_WINDOW: widget window is unavailable");
        }
        const widgetSnapshot: unknown =
          await widgetWindow.webContents.executeJavaScript(
            `(() => new Promise((resolve, reject) => {
              const deadline = Date.now() + 25000;
              const check = async () => {
                if (document.documentElement.dataset.widgetError) {
                  reject(new Error(document.documentElement.dataset.widgetError));
                  return;
                }
                if (document.documentElement.dataset.widgetReady === "true") {
                  const root = document.querySelector(".desktop-widget");
                  const controls = document.querySelector(".widget-voice-controls");
                  const voice = document.getElementById("widgetVoiceButton");
                  const mic = document.getElementById("widgetMicButton");
                  const autoListen = document.getElementById("widgetAutoListenButton");
                  const avatarSurface = document.querySelector(".widget-avatar-surface");
                  if (
                    !(root instanceof HTMLElement)
                    || !(controls instanceof HTMLElement)
                    || !(voice instanceof HTMLButtonElement)
                    || !(mic instanceof HTMLButtonElement)
                    || !(autoListen instanceof HTMLButtonElement)
                    || !(avatarSurface instanceof HTMLElement)
                  ) {
                    reject(new Error("E_DESKTOP_WIDGET_DOM"));
                    return;
                  }
                  const hiddenStyle = getComputedStyle(controls);
                  const hidden = {
                    opacity: hiddenStyle.opacity,
                    visibility: hiddenStyle.visibility,
                    pointerEvents: hiddenStyle.pointerEvents
                  };
                  root.focus({ preventScroll: true });
                  await new Promise((done) => setTimeout(done, 180));
                  const focusedStyle = getComputedStyle(controls);
                  const focused = {
                    opacity: focusedStyle.opacity,
                    visibility: focusedStyle.visibility,
                    pointerEvents: focusedStyle.pointerEvents
                  };
                  root.blur();
                  await new Promise((done) => setTimeout(done, 180));
                  let widgetControlDenied = false;
                  try {
                    await window.hinaDesktop.applyWidgetControl({
                      action: "reset_position"
                    });
                  } catch {
                    widgetControlDenied = true;
                  }
                  resolve({
                    mode: await window.hinaDesktop.getWindowMode(),
                    widgetRenderer:
                      document.documentElement.dataset.widgetRenderer ?? null,
                    spoutSender:
                      document.documentElement.dataset.spoutSender ?? null,
                    spoutTransparent:
                      document.documentElement.dataset.spoutTransparent ?? null,
                    presentation:
                      document.documentElement.dataset.avatarPresentation,
                    loadedTextureCount: Number(
                      document.documentElement.dataset.avatarTextureCount
                    ),
                    bodyBackground: getComputedStyle(document.body).backgroundColor,
                    rootBackground: getComputedStyle(root).backgroundColor,
                    dragRegion: getComputedStyle(avatarSurface)
                      .getPropertyValue("-webkit-app-region"),
                    voiceDragRegion: getComputedStyle(voice)
                      .getPropertyValue("-webkit-app-region"),
                    controlCount:
                      document.querySelectorAll(".widget-control").length,
                    micDragRegion: getComputedStyle(mic)
                      .getPropertyValue("-webkit-app-region"),
                    autoListenDragRegion: getComputedStyle(autoListen)
                      .getPropertyValue("-webkit-app-region"),
                    widgetControlDenied,
                    hidden,
                    focused
                  });
                  return;
                }
                if (Date.now() >= deadline) {
                  reject(new Error("E_DESKTOP_WIDGET_SMOKE_TIMEOUT"));
                  return;
                }
                setTimeout(check, 50);
              };
              check();
            }))()`,
            true,
          );
        widgetWindow.webContents.sendInputEvent({
          type: "mouseMove",
          x: 220,
          y: 310,
          movementX: 0,
          movementY: 0,
        });
        await new Promise((resolve) => setTimeout(resolve, 180));
        const widgetHoverSnapshot: unknown =
          await widgetWindow.webContents.executeJavaScript(
            `(() => {
              const root = document.querySelector(".desktop-widget");
              const controls = document.querySelector(".widget-voice-controls");
              if (!(root instanceof HTMLElement) || !(controls instanceof HTMLElement)) {
                throw new Error("E_DESKTOP_WIDGET_HOVER_DOM");
              }
              const style = getComputedStyle(controls);
              return {
                hovered: root.matches(":hover"),
                opacity: style.opacity,
                visibility: style.visibility,
                pointerEvents: style.pointerEvents
              };
            })()`,
            true,
          );
        widgetWindow.webContents.sendInputEvent({
          type: "mouseLeave",
          x: -1,
          y: -1,
          movementX: 0,
          movementY: 0,
        });
        await new Promise((resolve) => setTimeout(resolve, 180));
        widgetWindow.webContents.send(CHANNELS.widgetHover, false);
        await new Promise((resolve) => setTimeout(resolve, 160));
        const widgetIpcHiddenSnapshot: unknown =
          await widgetWindow.webContents.executeJavaScript(
            `(() => {
              const root = document.querySelector(".desktop-widget");
              const controls = document.querySelector(".widget-voice-controls");
              if (!(root instanceof HTMLElement) || !(controls instanceof HTMLElement)) {
                throw new Error("E_DESKTOP_WIDGET_HOVER_DOM");
              }
              const style = getComputedStyle(controls);
              return {
                dataHovered: root.dataset.hovered ?? "missing",
                visibility: style.visibility
              };
            })()`,
            true,
          );
        widgetWindow.webContents.send(CHANNELS.widgetHover, true);
        await new Promise((resolve) => setTimeout(resolve, 160));
        const widgetIpcHoverSnapshot: unknown =
          await widgetWindow.webContents.executeJavaScript(
            `(() => {
              const root = document.querySelector(".desktop-widget");
              const controls = document.querySelector(".widget-voice-controls");
              if (!(root instanceof HTMLElement) || !(controls instanceof HTMLElement)) {
                throw new Error("E_DESKTOP_WIDGET_HOVER_DOM");
              }
              const style = getComputedStyle(controls);
              return {
                dataHovered: root.dataset.hovered ?? "missing",
                opacity: style.opacity,
                visibility: style.visibility,
                pointerEvents: style.pointerEvents
              };
            })()`,
            true,
          );
        widgetWindow.webContents.send(CHANNELS.widgetHover, false);
        const widgetSize = widgetWindow.getContentSize();
        const widgetWidthActual = widgetSize[0] ?? 0;
        const widgetHeightActual = widgetSize[1] ?? 0;
        const widgetDiagnostic = (
          widgetSnapshot && typeof widgetSnapshot === "object"
            ? widgetSnapshot
            : {}
        ) as Record<string, unknown>;
        const widgetAvatarValid = smokeSpout
          ? widgetDiagnostic.widgetRenderer === "spout2"
            && widgetDiagnostic.spoutSender === "VTubeStudioSpout"
          : widgetDiagnostic.presentation === "hina-kawaii-v0.1"
            && typeof widgetDiagnostic.loadedTextureCount === "number"
            && Number.isFinite(widgetDiagnostic.loadedTextureCount)
            && widgetDiagnostic.loadedTextureCount >= 8;
        if (
          !widgetSnapshot
          || typeof widgetSnapshot !== "object"
          || !("mode" in widgetSnapshot)
          || widgetSnapshot.mode !== "widget"
          || !widgetAvatarValid
          || !("bodyBackground" in widgetSnapshot)
          || widgetSnapshot.bodyBackground !== "rgba(0, 0, 0, 0)"
          || !("rootBackground" in widgetSnapshot)
          || widgetSnapshot.rootBackground !== "rgba(0, 0, 0, 0)"
          || !("dragRegion" in widgetSnapshot)
          || widgetSnapshot.dragRegion !== "drag"
          || !("voiceDragRegion" in widgetSnapshot)
          || widgetSnapshot.voiceDragRegion !== "no-drag"
          || !("controlCount" in widgetSnapshot)
          || widgetSnapshot.controlCount !== 3
          || (widgetSnapshot as Record<string, unknown>).micDragRegion !== "no-drag"
          || (widgetSnapshot as Record<string, unknown>).autoListenDragRegion !== "no-drag"
          || !("widgetControlDenied" in widgetSnapshot)
          || widgetSnapshot.widgetControlDenied !== true
          || !("hidden" in widgetSnapshot)
          || !widgetSnapshot.hidden
          || typeof widgetSnapshot.hidden !== "object"
          || !("opacity" in widgetSnapshot.hidden)
          || widgetSnapshot.hidden.opacity !== "0"
          || !("visibility" in widgetSnapshot.hidden)
          || widgetSnapshot.hidden.visibility !== "hidden"
          || !("pointerEvents" in widgetSnapshot.hidden)
          || widgetSnapshot.hidden.pointerEvents !== "none"
          || !("focused" in widgetSnapshot)
          || !widgetSnapshot.focused
          || typeof widgetSnapshot.focused !== "object"
          || !("opacity" in widgetSnapshot.focused)
          || widgetSnapshot.focused.opacity !== "1"
          || !("visibility" in widgetSnapshot.focused)
          || widgetSnapshot.focused.visibility !== "visible"
          || !("pointerEvents" in widgetSnapshot.focused)
          || widgetSnapshot.focused.pointerEvents !== "auto"
          || !widgetHoverSnapshot
          || typeof widgetHoverSnapshot !== "object"
          || !("hovered" in widgetHoverSnapshot)
          || widgetHoverSnapshot.hovered !== true
          || !("opacity" in widgetHoverSnapshot)
          || widgetHoverSnapshot.opacity !== "1"
          || !("visibility" in widgetHoverSnapshot)
          || widgetHoverSnapshot.visibility !== "visible"
          || !("pointerEvents" in widgetHoverSnapshot)
          || widgetHoverSnapshot.pointerEvents !== "auto"
          || !widgetIpcHiddenSnapshot
          || typeof widgetIpcHiddenSnapshot !== "object"
          || !("dataHovered" in widgetIpcHiddenSnapshot)
          || widgetIpcHiddenSnapshot.dataHovered !== "false"
          || !("visibility" in widgetIpcHiddenSnapshot)
          || widgetIpcHiddenSnapshot.visibility !== "hidden"
          || !widgetIpcHoverSnapshot
          || typeof widgetIpcHoverSnapshot !== "object"
          || !("dataHovered" in widgetIpcHoverSnapshot)
          || widgetIpcHoverSnapshot.dataHovered !== "true"
          || !("opacity" in widgetIpcHoverSnapshot)
          || widgetIpcHoverSnapshot.opacity !== "1"
          || !("visibility" in widgetIpcHoverSnapshot)
          || widgetIpcHoverSnapshot.visibility !== "visible"
          || !("pointerEvents" in widgetIpcHoverSnapshot)
          || widgetIpcHoverSnapshot.pointerEvents !== "auto"
          || !widgetWindow.isAlwaysOnTop()
          || !widgetWindow.isMovable()
          || widgetWindow.isResizable()
          || widgetWidthActual !== 440
          || widgetHeightActual < 620
          || widgetHeightActual > 624
        ) {
          throw new Error(
            `E_DESKTOP_WIDGET_SMOKE: widget returned an invalid snapshot ${
              JSON.stringify({
                native: {
                  alwaysOnTop: widgetWindow.isAlwaysOnTop(),
                  movable: widgetWindow.isMovable(),
                  resizable: widgetWindow.isResizable(),
                  size: widgetSize,
                },
                focused: widgetDiagnostic.focused ?? null,
                hidden: widgetDiagnostic.hidden ?? null,
                drag: [
                  widgetDiagnostic.dragRegion ?? null,
                  widgetDiagnostic.voiceDragRegion ?? null,
                ],
                controls: widgetDiagnostic.controlCount ?? null,
                hover: widgetHoverSnapshot,
                ipcHover: {
                  hidden: widgetIpcHiddenSnapshot,
                  hovered: widgetIpcHoverSnapshot,
                },
                snapshot: widgetSnapshot,
              }).slice(0, 700)
            }`,
          );
        }
        const operatorContents = mainWindow?.webContents;
        if (!operatorContents) {
          throw new Error("E_DESKTOP_OPERATOR_WINDOW: operator window is unavailable");
        }
        const widgetControlSmoke: unknown =
          await operatorContents.executeJavaScript(
            `(async () => {
              const hidden = await window.hinaDesktop.applyWidgetControl({
                action: "hide"
              });
              const shown = await window.hinaDesktop.applyWidgetControl({
                action: "show"
              });
              const reset = await window.hinaDesktop.applyWidgetControl({
                action: "reset_position"
              });
              return { hidden, shown, reset };
            })()`,
            true,
          );
        if (
          !widgetControlSmoke
          || typeof widgetControlSmoke !== "object"
          || !("hidden" in widgetControlSmoke)
          || !widgetControlSmoke.hidden
          || typeof widgetControlSmoke.hidden !== "object"
          || !("visible" in widgetControlSmoke.hidden)
          || widgetControlSmoke.hidden.visible !== false
          || !("shown" in widgetControlSmoke)
          || !widgetControlSmoke.shown
          || typeof widgetControlSmoke.shown !== "object"
          || !("visible" in widgetControlSmoke.shown)
          || widgetControlSmoke.shown.visible !== true
          || !("reset" in widgetControlSmoke)
          || !widgetControlSmoke.reset
          || typeof widgetControlSmoke.reset !== "object"
          || !("visible" in widgetControlSmoke.reset)
          || widgetControlSmoke.reset.visible !== true
          || !widgetWindow.isVisible()
        ) {
          throw new Error(
            `E_DESKTOP_WIDGET_CONTROL_SMOKE: ${
              JSON.stringify(widgetControlSmoke).slice(0, 400)
            }`,
          );
        }
        const capturePath = process.env.HINA_DESKTOP_CAPTURE_PATH?.trim();
        if (capturePath) {
          await mkdir(dirname(capturePath), { recursive: true });
          const image = await widgetWindow.webContents.capturePage();
          await writeFile(capturePath, image.toPNG());
        }
        console.log(JSON.stringify({
          status: "ready",
          application: "hina-avatar-desktop",
          runtime: snapshot.runtime,
          avatarState: snapshot.avatarState,
          vrmLoaded: snapshot.vrmLoaded,
          presentation: snapshot.presentation,
          loadedTextureCount: snapshot.loadedTextureCount,
          styledMaterialCount: snapshot.styledMaterialCount,
          performance: snapshot.performance,
          visionProvider: {
            provider: snapshot.visionProvider.persistence.provider,
            apiKeyReadableByRenderer:
              snapshot.visionProvider.persistence.rendererCanReadStoredKey,
          },
          recovery: snapshot.recovery,
          widget: {
            mode: widgetSnapshot.mode,
            transparent: true,
            alwaysOnTop: true,
            movable: true,
            size: widgetSize,
            dragRegion: widgetSnapshot.dragRegion,
            voiceControlHiddenUntilHoverOrFocus: true,
            visibleControlCount: widgetSnapshot.controlCount,
            operatorControls: {
              hideShowReset: true,
              widgetControlDeniedInWidget: widgetSnapshot.widgetControlDenied,
            },
          },
          renderer: "loaded-local-file-with-typed-ipc",
        }));
        app.quit();
      } catch (error) {
        console.error(JSON.stringify({
          status: "error",
          errorCode: "E_DESKTOP_SMOKE",
          message: error instanceof Error ? error.message.slice(0, 200) : "unknown error",
        }));
        app.exit(1);
      }
    });
    smokeTimer = setTimeout(() => {
      console.error(JSON.stringify({
        status: "error",
        errorCode: "E_DESKTOP_SMOKE_TIMEOUT",
      }));
      app.exit(1);
    }, 30_000);
  }

  await Promise.all([
    mainWindow.loadFile(rendererPath),
    widgetWindow.loadFile(rendererPath),
  ]);
  startWidgetHoverWatcher();
}

app.on("before-quit", (event) => {
  stopWidgetHoverWatcher();
  captureGrantStore.clear();
  if (visionRestoreTimer) {
    clearTimeout(visionRestoreTimer);
    visionRestoreTimer = null;
  }
  if (vtubeStudioClient) {
    void vtubeStudioClient.disconnect();
  }
  if (smokeTimer) {
    clearTimeout(smokeTimer);
    smokeTimer = null;
  }
  if (spoutBridge && !shutdownPending) {
    event.preventDefault();
    shutdownPending = true;
    void spoutBridge.stop().finally(() => app.quit());
  }
});
app.whenReady().then(async () => {
  registerMediaPermissions();
  registerIpcHandlers();
  try {
    await getSpoutBridge().start();
  } catch (error) {
    console.warn(
      `[hina-desktop] ${error instanceof Error ? error.message : "E_SPOUT_BRIDGE_START"}`,
    );
  }
  await createWindows();
  scheduleVisionProviderRestore();
});
app.on("activate", () => {
  if (BrowserWindow.getAllWindows().length === 0) {
    void createWindows();
  }
});
app.on("window-all-closed", () => {
  if (process.platform !== "darwin") {
    app.quit();
  }
});
