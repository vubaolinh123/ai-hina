import {
  app,
  BrowserWindow,
  ipcMain,
  screen,
  session,
  type IpcMainInvokeEvent,
} from "electron";
import { mkdir, readFile, stat, writeFile } from "node:fs/promises";
import { dirname, join } from "node:path";
import {
  requestControl,
  requestChatCancel,
  requestChatStart,
  requestChatStatus,
  requestChatTurn,
  requestSpeechSynthesis,
  requestSpeechTranscription,
  validateAvatarCue,
  validateSafetyControl,
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

const CHANNELS = Object.freeze({
  windowMode: "hina:window:mode",
  widgetStatus: "hina:widget:status",
  widgetControl: "hina:widget:control",
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
});

const WIDGET_SIZE: Size = Object.freeze({ width: 440, height: 620 });
const WIDGET_STATE_FILENAME = "hina-widget-state.v1.json";

let mainWindow: BrowserWindow | null = null;
let widgetWindow: BrowserWindow | null = null;
let smokeTimer: NodeJS.Timeout | null = null;
let widgetPositionTimer: NodeJS.Timeout | null = null;

type DesktopWindowMode = "operator" | "widget";
type WidgetControlAction = "show" | "hide" | "reset_position";

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
    assertTrustedSender(event);
    return requestControl("safety.control", {
      ...validateSafetyControl(control),
      actorId: "owner.desktop",
      trustLevel: "owner",
      correlationId: crypto.randomUUID(),
    });
  });
  ipcMain.handle(CHANNELS.runtimeHealth, (event) => {
    assertTrustedSender(event);
    return requestControl("runtime.health");
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
              performance
            ]).then(async ([health, avatar, widgetStatus, vrmLoaded, performance]) => {
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
              return {
                runtime: health.status,
                avatarState: avatar.state,
                widgetStatus,
                vrmLoaded,
                presentation,
                loadedTextureCount,
                styledMaterialCount,
                performance,
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
                  const avatarSurface = document.querySelector(".widget-avatar-surface");
                  if (
                    !(root instanceof HTMLElement)
                    || !(controls instanceof HTMLElement)
                    || !(voice instanceof HTMLButtonElement)
                    || !(mic instanceof HTMLButtonElement)
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
        const widgetSize = widgetWindow.getContentSize();
        const widgetWidthActual = widgetSize[0] ?? 0;
        const widgetHeightActual = widgetSize[1] ?? 0;
        const widgetDiagnostic = (
          widgetSnapshot && typeof widgetSnapshot === "object"
            ? widgetSnapshot
            : {}
        ) as Record<string, unknown>;
        if (
          !widgetSnapshot
          || typeof widgetSnapshot !== "object"
          || !("mode" in widgetSnapshot)
          || widgetSnapshot.mode !== "widget"
          || !("presentation" in widgetSnapshot)
          || widgetSnapshot.presentation !== "hina-kawaii-v0.1"
          || !("loadedTextureCount" in widgetSnapshot)
          || typeof widgetSnapshot.loadedTextureCount !== "number"
          || !Number.isFinite(widgetSnapshot.loadedTextureCount)
          || widgetSnapshot.loadedTextureCount < 8
          || !("bodyBackground" in widgetSnapshot)
          || widgetSnapshot.bodyBackground !== "rgba(0, 0, 0, 0)"
          || !("rootBackground" in widgetSnapshot)
          || widgetSnapshot.rootBackground !== "rgba(0, 0, 0, 0)"
          || !("dragRegion" in widgetSnapshot)
          || widgetSnapshot.dragRegion !== "drag"
          || !("voiceDragRegion" in widgetSnapshot)
          || widgetSnapshot.voiceDragRegion !== "no-drag"
          || !("controlCount" in widgetSnapshot)
          || widgetSnapshot.controlCount !== 2
          || (widgetSnapshot as Record<string, unknown>).micDragRegion !== "no-drag"
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
}

app.on("before-quit", () => {
  if (smokeTimer) {
    clearTimeout(smokeTimer);
    smokeTimer = null;
  }
});
app.whenReady().then(async () => {
  registerMediaPermissions();
  registerIpcHandlers();
  await createWindows();
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
