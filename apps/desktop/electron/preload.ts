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
});

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
});

contextBridge.exposeInMainWorld("hinaDesktop", hinaDesktop);
