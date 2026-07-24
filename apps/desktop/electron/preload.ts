import { contextBridge, ipcRenderer } from "electron";

const CHANNELS = Object.freeze({
  avatarStatus: "hina:avatar:status",
  avatarCue: "hina:avatar:cue",
  avatarReset: "hina:avatar:reset",
  safetyStatus: "hina:safety:status",
  safetyControl: "hina:safety:control",
  runtimeHealth: "hina:runtime:health",
});

const hinaDesktop = Object.freeze({
  getAvatarStatus: () => ipcRenderer.invoke(CHANNELS.avatarStatus),
  applyAvatarCue: (cue: unknown) => ipcRenderer.invoke(CHANNELS.avatarCue, cue),
  resetAvatar: () => ipcRenderer.invoke(CHANNELS.avatarReset),
  getSafetyStatus: () => ipcRenderer.invoke(CHANNELS.safetyStatus),
  applySafetyControl: (control: unknown) =>
    ipcRenderer.invoke(CHANNELS.safetyControl, control),
  getRuntimeHealth: () => ipcRenderer.invoke(CHANNELS.runtimeHealth),
});

contextBridge.exposeInMainWorld("hinaDesktop", hinaDesktop);
