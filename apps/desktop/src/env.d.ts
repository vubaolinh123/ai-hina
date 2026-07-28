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
    featureFlags: {
      perception: boolean;
      [feature: string]: boolean;
    };
  };
};

type RuntimeHealth = {
  status: string;
  uptimeSeconds: number;
};

type ResourceTelemetry = {
  gpuName: string;
  totalVramMiB: number;
  usedVramMiB: number;
  freeVramMiB: number;
  totalRamMiB: number;
  usedRamMiB: number;
  freeRamMiB: number;
  gpuUtilizationPercent: number | null;
  temperatureCelsius: number | null;
  powerDrawWatts: number | null;
};

type ResourceLease = {
  owner: string;
  state: string;
  reservedVramMiB: number;
  reservedRamMiB: number;
  priority: number;
  preemptible: boolean;
  remainingTtlSeconds: number;
};

type ResourceModelState =
  | "loaded"
  | "loading"
  | "unloaded"
  | "unavailable"
  | "unconfigured"
  | "cloud-ready";

type ResourceModel = {
  id: string;
  role: string;
  name: string | null;
  provider: string | null;
  location: "local" | "cloud";
  state: ResourceModelState;
  configured: boolean;
  available: boolean;
  loaded: boolean;
  active: boolean;
  configuredVramMiB: number | null;
  measuredVramMiB: number | null;
  errorCode: string | null;
};

type ResourceModelTransition = {
  sequence: number;
  modelId: string;
  role: string;
  name: string | null;
  fromState: ResourceModelState | null;
  toState: ResourceModelState;
  action: "loaded" | "unloaded" | "state-changed" | "observed";
  occurredAtUnixMilliseconds: number;
};

type ResourceProcess = {
  label: string;
  rssMiB: number | null;
  heapUsedMiB?: number;
  externalMiB?: number;
};

type ResourceStatus = {
  schemaVersion: "1.0";
  sampledAtUnixMilliseconds: number;
  limits: {
    allOnVramCeilingMiB: number;
    minimumFreeVramMiB: number;
  };
  physical: {
    available: boolean;
    errorCode?: string;
    telemetry: ResourceTelemetry | null;
    activeLeases: number;
    reservedVramMiB: number;
    reservedRamMiB: number;
    availableVramMiB: number | null;
    availableRamMiB: number | null;
    headroomMiB: number;
    leases: ResourceLease[];
  };
  processes: {
    coreRuntime: ResourceProcess;
    desktopMain: ResourceProcess;
  };
  models: ResourceModel[];
  modelTransitions: ResourceModelTransition[];
  transitionHistory: {
    persistence: false;
    limit: number;
    count: number;
  };
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

type SpoutBridgeStatus = {
  available: true;
  enabled: boolean;
  state: "disabled" | "starting" | "ready" | "degraded" | "error";
  sender: "VTubeStudioSpout";
  endpoint: string | null;
  frameUrl: string | null;
  frameReady: boolean;
  frameSequence: number;
  frameAgeMilliseconds: number | null;
  width: number;
  height: number;
  transparent: boolean;
  lastErrorCode: string | null;
};

type VisionProviderChoice = "ollama_local" | "ollama_cloud";

type VisionModelOption = {
  name: string;
  sizeBytes: number | null;
  parameterSize: string | null;
  quantization: string | null;
  capabilities: string[];
  lightweight: boolean;
  localGpuUsed: boolean;
};

type VisionProviderRuntimeStatus = {
  provider: VisionProviderChoice | "none";
  model: string | null;
  state: "closed" | "ready" | "unconfigured" | "error";
  available: boolean;
  apiKeyConfigured: boolean;
  apiKeyReadableByRenderer: false;
  apiKeyStorage: "electron-safe-storage";
  automatic: false;
  decisionSupportEligible: false;
  localGpuUsed: boolean;
  cloudImageUpload: boolean;
  lastErrorCode: string | null;
};

type VisionProviderDashboardStatus = {
  runtime: VisionProviderRuntimeStatus;
  persistence: {
    provider: VisionProviderChoice | "disabled";
    model: string | null;
    apiKeyConfigured: boolean;
    encryptedWithOsStorage: boolean;
    rendererCanReadStoredKey: false;
  };
};

type VisionModelDiscovery = {
  provider: VisionProviderChoice;
  count: number;
  models: VisionModelOption[];
  apiKeyConfigured: boolean;
  onlyVisionModels: true;
  localSelectionLimitBytes: number | null;
};

type ScreenCaptureSource = {
  sourceToken: string;
  name: string;
  kind: "screen" | "window";
  previewDataUrl: string;
  previewWidth: number;
  previewHeight: number;
};

type ScreenCaptureSourceListing = {
  grantSessionId: string;
  expiresAtUnixMilliseconds: number;
  sourceCount: number;
  sources: ScreenCaptureSource[];
  persistence: false;
};

type DesktopPerceptionCaptureResult = {
  status: "observed" | "duplicate";
  correlationId: string;
  observation?: {
    observationId: string;
    ttlSeconds: number;
    expiresAt: string;
    evidence: {
      width: number;
      height: number;
      bytes: number;
    };
    ocr?: {
      state: string;
      requested: boolean;
      text?: string;
      errorCode?: string;
    };
    vision?: {
      state: string;
      requested: boolean;
      provider?: string;
      model?: string | null;
      summary?: string;
      errorCode?: string;
      providerErrorCode?: string;
      modelErrorCode?: string;
    };
  };
  dedup?: {
    matchedObservationId: string;
    hammingDistance: number;
    threshold: number;
  };
  desktopCapture: {
    sourceName: string;
    sourceKind: "screen" | "window";
    fullFrame: true;
    requestedMaxSide: 640 | 960 | 1280;
    width: number;
    height: number;
    bytes: number;
    automatic: false;
    persistedByDesktop: false;
  };
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
    | { action: "set_feature"; feature: "perception"; enabled: boolean }
    | { action: "emergency_stop" }
    | { action: "emergency_reset" }
  ): Promise<unknown>;
  getRuntimeHealth(): Promise<RuntimeHealth>;
  getResourceStatus(): Promise<ResourceStatus>;
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
  getSpoutStatus(): Promise<SpoutBridgeStatus>;
  getVisionProviderStatus(): Promise<VisionProviderDashboardStatus>;
  discoverVisionModels(input: {
    provider: VisionProviderChoice;
    apiKey?: string;
  }): Promise<VisionModelDiscovery>;
  configureVisionProvider(input: {
    provider: VisionProviderChoice;
    model: string;
    apiKey?: string;
  }): Promise<{
    runtime: VisionProviderRuntimeStatus;
    persistence: VisionProviderDashboardStatus["persistence"];
  }>;
  clearVisionApiKey(): Promise<{
    apiKeyConfigured: false;
    persisted: false;
    runtimeDisabled: boolean;
    runtimePreserved: boolean;
  }>;
  listScreenCaptureSources(): Promise<ScreenCaptureSourceListing>;
  captureScreenSource(input: {
    grantSessionId: string;
    sourceToken: string;
    maxSide: 640 | 960 | 1280;
    label: string | null;
    analyzeOcr: boolean;
    analyzeVision: boolean;
    visionQuestion: string | null;
  }): Promise<DesktopPerceptionCaptureResult>;
};

interface Window {
  hinaDesktop: HinaDesktopApi;
}
