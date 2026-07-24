import {
  app,
  BrowserWindow,
  ipcMain,
  type IpcMainInvokeEvent,
} from "electron";
import { join } from "node:path";
import {
  requestControl,
  validateAvatarCue,
  validateSafetyControl,
} from "./control-client";

const CHANNELS = Object.freeze({
  avatarStatus: "hina:avatar:status",
  avatarCue: "hina:avatar:cue",
  avatarReset: "hina:avatar:reset",
  safetyStatus: "hina:safety:status",
  safetyControl: "hina:safety:control",
  runtimeHealth: "hina:runtime:health",
});

let mainWindow: BrowserWindow | null = null;
let smokeTimer: NodeJS.Timeout | null = null;

function assertTrustedSender(event: IpcMainInvokeEvent): void {
  if (
    !mainWindow
    || event.sender !== mainWindow.webContents
    || event.senderFrame !== event.sender.mainFrame
  ) {
    throw new Error("E_DESKTOP_IPC_SENDER: IPC is limited to the desktop main frame");
  }
}

function registerIpcHandlers(): void {
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

async function createWindow(): Promise<void> {
  const smoke = process.env.HINA_DESKTOP_SMOKE === "1";
  const rendererPath = join(__dirname, "..", "dist", "index.html");
  const preloadPath = join(__dirname, "preload.js");
  mainWindow = new BrowserWindow({
    width: 1280,
    height: 800,
    minWidth: 900,
    minHeight: 620,
    show: !smoke,
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
    },
  });
  mainWindow.webContents.setWindowOpenHandler(() => ({ action: "deny" }));
  mainWindow.webContents.on("will-navigate", (event, url) => {
    if (url !== mainWindow?.webContents.getURL()) {
      event.preventDefault();
    }
  });
  mainWindow.webContents.on("will-attach-webview", (event) => {
    event.preventDefault();
  });
  mainWindow.on("closed", () => {
    mainWindow = null;
  });

  if (smoke) {
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
        const snapshot: unknown = await mainWindow?.webContents.executeJavaScript(
          `Promise.all([
            window.hinaDesktop.getRuntimeHealth(),
            window.hinaDesktop.getAvatarStatus()
          ]).then(([health, avatar]) => ({
            runtime: health.status,
            avatarState: avatar.state
          }))`,
          true,
        );
        if (
          !snapshot
          || typeof snapshot !== "object"
          || !("runtime" in snapshot)
          || typeof snapshot.runtime !== "string"
          || !("avatarState" in snapshot)
          || typeof snapshot.avatarState !== "string"
        ) {
          throw new Error("E_DESKTOP_SMOKE_IPC: renderer returned an invalid snapshot");
        }
        console.log(JSON.stringify({
          status: "ready",
          application: "hina-avatar-desktop",
          runtime: snapshot.runtime,
          avatarState: snapshot.avatarState,
          renderer: "loaded-local-file-with-typed-ipc",
        }));
        app.exit(0);
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
    }, 20_000);
  }

  await mainWindow.loadFile(rendererPath);
}

app.on("before-quit", () => {
  if (smokeTimer) {
    clearTimeout(smokeTimer);
    smokeTimer = null;
  }
});
app.whenReady().then(async () => {
  registerIpcHandlers();
  await createWindow();
});
app.on("activate", () => {
  if (BrowserWindow.getAllWindows().length === 0) {
    void createWindow();
  }
});
app.on("window-all-closed", () => {
  if (process.platform !== "darwin") {
    app.quit();
  }
});
