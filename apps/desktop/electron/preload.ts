import { contextBridge, ipcRenderer } from "electron";

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
  visionReview: "hina:vision:review",
  visionQualityReset: "hina:vision:quality:reset",
  visionClearKey: "hina:vision:clear-key",
  resourcesStatus: "hina:resources:status",
  resourcesControl: "hina:resources:control",
  minecraftStatus: "hina:minecraft:status",
  minecraftConnect: "hina:minecraft:connect",
  minecraftDisconnect: "hina:minecraft:disconnect",
  minecraftGoal: "hina:minecraft:goal",
  minecraftEmergencyStop: "hina:minecraft:emergency-stop",
  captureSources: "hina:capture:sources",
  captureSubmit: "hina:capture:submit",
  captureProgress: "hina:capture:progress",
});

type CaptureProgress = {
  phase: "capturing" | "encoding" | "analyzing";
  requestedMaxSide: 640 | 960 | 1280;
  sourceName: string;
  width?: number;
  height?: number;
  bytes?: number;
};

function parseCaptureProgress(value: unknown): CaptureProgress | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  const raw = value as Record<string, unknown>;
  if (
    (raw.phase !== "capturing" && raw.phase !== "encoding" && raw.phase !== "analyzing")
    || (raw.requestedMaxSide !== 640 && raw.requestedMaxSide !== 960 && raw.requestedMaxSide !== 1280)
    || typeof raw.sourceName !== "string"
    || raw.sourceName.length > 160
  ) {
    return null;
  }
  const dimensions = [raw.width, raw.height, raw.bytes];
  if (dimensions.some((entry) => (
    entry !== undefined
    && (typeof entry !== "number" || !Number.isInteger(entry) || entry < 0)
  ))) {
    return null;
  }
  return {
    phase: raw.phase as CaptureProgress["phase"],
    requestedMaxSide: raw.requestedMaxSide as CaptureProgress["requestedMaxSide"],
    sourceName: raw.sourceName,
    ...(typeof raw.width === "number" ? { width: raw.width } : {}),
    ...(typeof raw.height === "number" ? { height: raw.height } : {}),
    ...(typeof raw.bytes === "number" ? { bytes: raw.bytes } : {}),
  };
}

const hinaDesktop = Object.freeze({
  getWindowMode: () => ipcRenderer.invoke(CHANNELS.windowMode),
  getWidgetStatus: () => ipcRenderer.invoke(CHANNELS.widgetStatus),
  applyWidgetControl: (control: unknown) =>
    ipcRenderer.invoke(CHANNELS.widgetControl, control),
  onWidgetHover: (listener: (hovered: boolean) => void) => {
    const wrapped = (
      _event: Electron.IpcRendererEvent,
      hovered: unknown,
    ): void => {
      listener(hovered === true);
    };
    ipcRenderer.on(CHANNELS.widgetHover, wrapped);
    return () => {
      ipcRenderer.removeListener(CHANNELS.widgetHover, wrapped);
    };
  },
  getAvatarStatus: () => ipcRenderer.invoke(CHANNELS.avatarStatus),
  applyAvatarCue: (cue: unknown) => ipcRenderer.invoke(CHANNELS.avatarCue, cue),
  resetAvatar: () => ipcRenderer.invoke(CHANNELS.avatarReset),
  getSafetyStatus: () => ipcRenderer.invoke(CHANNELS.safetyStatus),
  applySafetyControl: (control: unknown) =>
    ipcRenderer.invoke(CHANNELS.safetyControl, control),
  getRuntimeHealth: () => ipcRenderer.invoke(CHANNELS.runtimeHealth),
  getChatStatus: () => ipcRenderer.invoke(CHANNELS.chatStatus),
  startChatTurn: (payload: unknown) => ipcRenderer.invoke(CHANNELS.chatStart, payload),
  getChatTurn: (turnId: string) => ipcRenderer.invoke(CHANNELS.chatTurn, turnId),
  cancelChatTurn: (turnId: string) => ipcRenderer.invoke(CHANNELS.chatCancel, turnId),
  transcribeSpeech: (audio: Uint8Array, sessionId: string) =>
    ipcRenderer.invoke(CHANNELS.speechTranscribe, audio, sessionId),
  getSpeechStatus: () => ipcRenderer.invoke(CHANNELS.speechStatus),
  getTtsStatus: () => ipcRenderer.invoke(CHANNELS.ttsStatus),
  synthesizeSpeech: (payload: unknown) => ipcRenderer.invoke(CHANNELS.ttsSynthesize, payload),
  getVTubeStudioStatus: () => ipcRenderer.invoke(CHANNELS.vtubeStatus),
  connectVTubeStudio: () => ipcRenderer.invoke(CHANNELS.vtubeConnect),
  disconnectVTubeStudio: () => ipcRenderer.invoke(CHANNELS.vtubeDisconnect),
  refreshVTubeStudio: () => ipcRenderer.invoke(CHANNELS.vtubeRefresh),
  triggerVTubeStudioHotkey: (hotkeyId: string) =>
    ipcRenderer.invoke(CHANNELS.vtubeHotkey, hotkeyId),
  moveVTubeStudioModel: (preset: "chat" | "screen" | "react") =>
    ipcRenderer.invoke(CHANNELS.vtubeMove, preset),
  getSpoutStatus: () => ipcRenderer.invoke(CHANNELS.spoutStatus),
  getVisionProviderStatus: () => ipcRenderer.invoke(CHANNELS.visionStatus),
  discoverVisionModels: (input: unknown) =>
    ipcRenderer.invoke(CHANNELS.visionDiscover, input),
  configureVisionProvider: (input: unknown) =>
    ipcRenderer.invoke(CHANNELS.visionConfigure, input),
  reviewVisionObservation: (input: unknown) =>
    ipcRenderer.invoke(CHANNELS.visionReview, input),
  resetVisionQualitySession: () =>
    ipcRenderer.invoke(CHANNELS.visionQualityReset),
  clearVisionApiKey: () => ipcRenderer.invoke(CHANNELS.visionClearKey),
  getResourceStatus: () => ipcRenderer.invoke(CHANNELS.resourcesStatus),
  controlResourceModel: (modelId: string, action: "load" | "unload") =>
    ipcRenderer.invoke(CHANNELS.resourcesControl, modelId, action),
  getMinecraftStatus: () => ipcRenderer.invoke(CHANNELS.minecraftStatus),
  connectMinecraft: (input: unknown) =>
    ipcRenderer.invoke(CHANNELS.minecraftConnect, input),
  disconnectMinecraft: () => ipcRenderer.invoke(CHANNELS.minecraftDisconnect),
  runMinecraftGoal: (input: unknown) =>
    ipcRenderer.invoke(CHANNELS.minecraftGoal, input),
  emergencyStopMinecraft: () =>
    ipcRenderer.invoke(CHANNELS.minecraftEmergencyStop),
  listScreenCaptureSources: () => ipcRenderer.invoke(CHANNELS.captureSources),
  captureScreenSource: (input: unknown) =>
    ipcRenderer.invoke(CHANNELS.captureSubmit, input),
  onScreenCaptureProgress: (listener: (progress: CaptureProgress) => void) => {
    const wrapped = (
      _event: Electron.IpcRendererEvent,
      progress: unknown,
    ): void => {
      const parsed = parseCaptureProgress(progress);
      if (parsed !== null) listener(parsed);
    };
    ipcRenderer.on(CHANNELS.captureProgress, wrapped);
    return () => {
      ipcRenderer.removeListener(CHANNELS.captureProgress, wrapped);
    };
  },
});

contextBridge.exposeInMainWorld("hinaDesktop", hinaDesktop);
