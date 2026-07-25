import {
  app,
  BrowserWindow,
  ipcMain,
  screen,
  type IpcMainInvokeEvent,
} from "electron";
import { mkdir, writeFile } from "node:fs/promises";
import { dirname, join } from "node:path";
import {
  requestControl,
  validateAvatarCue,
  validateSafetyControl,
} from "./control-client";

const CHANNELS = Object.freeze({
  windowMode: "hina:window:mode",
  avatarStatus: "hina:avatar:status",
  avatarCue: "hina:avatar:cue",
  avatarReset: "hina:avatar:reset",
  safetyStatus: "hina:safety:status",
  safetyControl: "hina:safety:control",
  runtimeHealth: "hina:runtime:health",
});

let mainWindow: BrowserWindow | null = null;
let widgetWindow: BrowserWindow | null = null;
let smokeTimer: NodeJS.Timeout | null = null;

type DesktopWindowMode = "operator" | "widget";

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

function registerIpcHandlers(): void {
  ipcMain.handle(CHANNELS.windowMode, (event) => assertTrustedSender(event));
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
}

async function createWindows(): Promise<void> {
  const smoke = process.env.HINA_DESKTOP_SMOKE === "1";
  const rendererPath = join(__dirname, "..", "dist", "index.html");
  const preloadPath = join(__dirname, "preload.js");
  const widgetWidth = 440;
  const widgetHeight = 620;
  const workArea = screen.getPrimaryDisplay().workArea;
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
    x: workArea.x + workArea.width - widgetWidth - 24,
    y: workArea.y + workArea.height - widgetHeight - 24,
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
  mainWindow.on("closed", () => {
    mainWindow = null;
    if (widgetWindow && !widgetWindow.isDestroyed()) {
      widgetWindow.close();
    }
  });
  widgetWindow.on("closed", () => {
    widgetWindow = null;
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
              vrmReady,
              performance
            ]).then(async ([health, avatar, vrmLoaded, performance]) => {
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
                  const avatarSurface = document.querySelector(".widget-avatar-surface");
                  if (
                    !(root instanceof HTMLElement)
                    || !(controls instanceof HTMLElement)
                    || !(voice instanceof HTMLButtonElement)
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
          || widgetSnapshot.controlCount !== 1
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
