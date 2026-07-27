/// <reference types="vite/client" />

type AvatarState =
  | "idle"
  | "listening"
  | "thinking"
  | "speaking"
  | "interrupted"
  | "error";

type AvatarStatus = {
  available: true;
  sequence: number;
  state: AvatarState;
  expression: string;
  viseme: "sil" | "A" | "I" | "U" | "E" | "O";
  intensity: number;
  source: string;
  mode: "runtime" | "manual-preview" | "tts-playback";
  updatedAt: string;
  correlationId: string | null;
  turnId: string | null;
  utteranceId: string | null;
  asset: {
    displayName: string;
    type: string;
    vrmLoaded: boolean;
    live2dLoaded: boolean;
  };
  lipSync: {
    mode: string;
    phonemeAccurate: boolean;
  };
};

type SafetyStatus = {
  state: {
    emergencyStopped: boolean;
    muted: boolean;
    revision: number;
  };
};

type RuntimeHealth = {
  status: string;
  uptimeSeconds: number;
};

type ChatTurn = {
  turnId: string;
  sessionId: string;
  outcome: "running" | "completed" | "interrupted" | "failed";
  text?: string;
  assistant?: string;
  errorCode?: string;
  errorMessage?: string;
  correlationId?: string;
};

type SpeechTranscription = {
  status: "transcribed" | "silence";
  transcript: string;
  speechDetected: boolean;
  processingMilliseconds: number;
  correlationId: string;
};

type SpeechRuntimeStatus = {
  available: boolean;
  configured: {
    provider: string;
    model: string;
    language: string;
    device: string;
    computeType: string;
  };
  provider: {
    available: boolean;
    modelLoaded: boolean;
    effectiveDevice: string;
    lastErrorCode: string | null;
  };
};

type TtsRuntimeStatus = {
  available: boolean;
  configured: {
    device: string;
    precision: string;
    model: string;
  };
  provider: {
    effectiveDevice: string;
    effectivePrecision: string;
    modelLoaded: boolean;
    lastErrorCode: string | null;
  };
};

type DesktopWindowMode = "operator" | "widget";

type WidgetStatus = {
  available: true;
  visible: boolean;
  alwaysOnTop: boolean;
  position: {
    x: number;
    y: number;
  };
};

type VTubeStudioStatus = {
  available: true;
  endpoint: "ws://127.0.0.1:8001";
  state:
    | "offline"
    | "connecting"
    | "needs_authorization"
    | "connected"
    | "error";
  connected: boolean;
  authenticated: boolean;
  authorizationStored: boolean;
  model: {
    loaded: boolean;
    id: string | null;
    name: string | null;
    vtsModelName: string | null;
  };
  hotkeys: Array<{
    id: string;
    name: string;
    type: string;
  }>;
  lastErrorCode: string | null;
  renderer: "external-vtube-studio";
  offlineFallback: "hina-vrm-widget";
  hiyoriBundled: false;
};

type HinaDesktopApi = {
  getWindowMode(): Promise<DesktopWindowMode>;
  getWidgetStatus(): Promise<WidgetStatus>;
  applyWidgetControl(control:
    | { action: "show" }
    | { action: "hide" }
    | { action: "reset_position" }
  ): Promise<WidgetStatus>;
  onWidgetHover(listener: (hovered: boolean) => void): () => void;
  getAvatarStatus(): Promise<AvatarStatus>;
  applyAvatarCue(cue: {
    source: "owner.console";
    state: AvatarState;
    mode: "manual-preview";
  }): Promise<AvatarStatus>;
  resetAvatar(): Promise<AvatarStatus>;
  getSafetyStatus(): Promise<SafetyStatus>;
  applySafetyControl(control:
    | { action: "set_mute"; enabled: boolean }
    | { action: "emergency_stop" }
    | { action: "emergency_reset" }
  ): Promise<unknown>;
  getRuntimeHealth(): Promise<RuntimeHealth>;
  getChatStatus(): Promise<Record<string, unknown>>;
  startChatTurn(payload: {
    sessionId: string;
    source: "owner.console";
    text: string;
  }): Promise<ChatTurn>;
  getChatTurn(turnId: string): Promise<ChatTurn>;
  cancelChatTurn(turnId: string): Promise<ChatTurn>;
  transcribeSpeech(
    audio: Uint8Array,
    sessionId: string,
  ): Promise<SpeechTranscription>;
  getSpeechStatus(): Promise<SpeechRuntimeStatus>;
  getTtsStatus(): Promise<TtsRuntimeStatus>;
  synthesizeSpeech(payload: {
    text: string;
    utteranceId: string;
    sessionId: string | null;
    source: "owner.console";
  }): Promise<Uint8Array>;
  getVTubeStudioStatus(): Promise<VTubeStudioStatus>;
  connectVTubeStudio(): Promise<VTubeStudioStatus>;
  disconnectVTubeStudio(): Promise<VTubeStudioStatus>;
  refreshVTubeStudio(): Promise<VTubeStudioStatus>;
  triggerVTubeStudioHotkey(hotkeyId: string): Promise<VTubeStudioStatus>;
  moveVTubeStudioModel(
    preset: "chat" | "screen" | "react",
  ): Promise<VTubeStudioStatus>;
};

interface Window {
  hinaDesktop: HinaDesktopApi;
}
