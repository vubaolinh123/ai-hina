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

type MinecraftVector = {
  x: number;
  y: number;
  z: number;
};

type MinecraftStatus = {
  schemaVersion: 1;
  phase: "disconnected" | "connecting" | "online" | "error" | "stopping" | "stopped";
  emergencyStopped: boolean;
  sequence: number;
  target: {
    host: string;
    port: number;
    username: string;
    version: string | null;
  } | null;
  connectedAt: string | null;
  capturedAt: string;
  worldFreshness: {
    physicsTickSequence: number;
    ageMs: number | null;
    maximumAgeMs: number;
    state: "fresh" | "stale" | "unavailable";
  } | null;
  world: {
    protocolVersion: string | null;
    dimension: string | null;
    timeOfDay: number | null;
    isDay: boolean | null;
    player: {
      username: string;
      health: number;
      food: number;
      foodSaturation: number;
      oxygenLevel: number;
      gameMode: string;
      position: MinecraftVector;
      velocity: MinecraftVector;
      yaw: number;
      pitch: number;
      onGround: boolean;
    } | null;
    inventory: Array<{
      slot: number;
      name: string;
      displayName: string;
      count: number;
      metadata: number;
    }>;
    nearbyEntities: Array<{
      id: number;
      type: string;
      name: string;
      username?: string;
      position: MinecraftVector;
      distance: number;
      health?: number;
    }>;
  } | null;
  lastError: {
    code: string;
    message: string;
  } | null;
};

type MinecraftGoalResponse = {
  status: string;
  plan: {
    state: "ready" | "unsupported";
    goalId: "harvest.nearby-log.v1" | null;
    label: string;
    planVersion: "minecraft.goal.v1";
  };
  execution?: {
    status: "succeeded" | "failed";
    error?: { code: string; message: string } | null;
    target?: {
      name: string;
      position: MinecraftVector;
      distanceBlocks: number;
    } | null;
    postcondition?: {
      passed: boolean;
      targetStillPresent: boolean | null;
    };
  };
  minecraft: MinecraftStatus;
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
  providerPeakVramMiB: number | null;
  sampledPeakVramMiB: number | null;
  measurementSource: string;
  measurementNote: string;
  errorCode: string | null;
  controlSupported: boolean;
  operatorResident: boolean;
  controlNote: string;
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
    admissionCeilingMiB?: number;
    liveFreeReserveMiB?: number;
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
  state?: AvatarState;
  outcome: "running" | "completed" | "interrupted" | "failed";
  text?: string;
  assistant?: string;
  errorCode?: string;
  errorMessage?: string;
  correlationId?: string;
  context?: Record<string, unknown> | null;
};

type ChatRuntimeStatus = {
  persona: Record<string, unknown>;
  memory: Record<string, unknown>;
  activeTurns: number;
  trackedTurns: number;
  context: Record<string, unknown>;
  outboundPartialStreaming: false;
  toolExecution: false;
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
type VisionQualityRating = "correct" | "partial" | "incorrect";
type VisionSceneTag =
  | "gameplay"
  | "menu_hud"
  | "chat_text"
  | "desktop_ui"
  | "motion_effects"
  | "dark_occluded";

type VisionCalibrationBin = {
  lowerConfidence: number;
  upperConfidence: number;
  includesUpper: boolean;
  sampleCount: number;
  meanConfidencePercent: number | null;
  observedScorePercent: number | null;
};

type VisionCalibrationStatus = {
  calibrated: false;
  diagnosticOnly: true;
  sampleCount: number;
  minimumSamples: number;
  sufficientEvidence: boolean;
  meanConfidencePercent: number | null;
  meanObservedScorePercent: number | null;
  meanAbsoluteErrorPercent: number | null;
  brierScore: number | null;
  ratingTruthMapping: {
    correct: 1;
    partial: 0.5;
    incorrect: 0;
  };
  reliabilityBins: VisionCalibrationBin[];
};

type VisionQualityReviewStatus = {
  schemaVersion: "1.1";
  storage: "memory-only";
  persistsAfterRestart: false;
  storesPixels: false;
  storesSummaries: false;
  capacity: number;
  profile: {
    provider: string | null;
    model: string | null;
  };
  registeredSamples: number;
  ratedSamples: number;
  unratedSamples: number;
  ratings: {
    correct: number;
    partial: number;
    incorrect: number;
  };
  states: {
    ready: number;
    abstained: number;
  };
  abstentionRatePercent: number | null;
  weightedScorePercent: number | null;
  targetPercent: number;
  minimumRatedSamples: number;
  sceneDiversity: {
    fixedAllowlist: VisionSceneTag[];
    counts: Record<VisionSceneTag, number>;
    coveredTags: number;
    minimumCoveredTags: number;
    minimumSamplesPerCoveredTag: number;
    targetMet: boolean;
    aggregateOnly: true;
  };
  candidateTargetMet: boolean;
  promotionApproved: false;
  calibration: VisionCalibrationStatus;
  allProfilesRegisteredSamples: number;
};

type VisionQualityReviewResponse = {
  status: "reviewed";
  observationId: string;
  rating: VisionQualityRating;
  sceneTags: VisionSceneTag[];
  replaced: boolean;
  qualityReview?: VisionQualityReviewStatus;
};

type VisionQualityResetResponse = {
  status: "reset";
  removedSamples: number;
  qualityReview: VisionQualityReviewStatus;
};

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
  qualityReview: VisionQualityReviewStatus;
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

type ScreenCaptureProgress = {
  phase: "capturing" | "encoding" | "analyzing";
  requestedMaxSide: 640 | 960 | 1280;
  sourceName: string;
  width?: number;
  height?: number;
  bytes?: number;
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
    vision?: {
      state: "not-requested" | "unavailable" | "ready" | "abstained" | "error";
      requested: boolean;
      provider?: string;
      model?: string | null;
      summary?: string | null;
      confidence?: number | null;
      confidenceSource?: string | null;
      confidenceCalibrated?: boolean;
      minimumConfidence?: number;
      abstainReason?: string | null;
      errorCode?: string;
      providerErrorCode?: string;
      modelErrorCode?: string;
      processingMilliseconds?: number;
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
    timings?: {
      sourceLookupMilliseconds: number;
      encodingMilliseconds: number;
      runtimeMilliseconds: number;
      totalMilliseconds: number;
    };
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
    | { action: "set_feature"; feature: "perception" | "gameAction"; enabled: boolean }
    | { action: "emergency_stop" }
    | { action: "emergency_reset" }
  ): Promise<unknown>;
  getRuntimeHealth(): Promise<RuntimeHealth>;
  getResourceStatus(): Promise<ResourceStatus>;
  controlResourceModel(
    modelId: string,
    action: "load" | "unload",
  ): Promise<{
    status: string;
    modelId: string;
    action: string;
    noOp: boolean;
    message: string;
    resources: ResourceStatus;
  }>;
  getMinecraftStatus(): Promise<MinecraftStatus>;
  connectMinecraft(input: {
    host: string;
    port: number;
    username: string;
    version: string | null;
  }): Promise<{
    status: string;
    minecraft: MinecraftStatus;
  }>;
  disconnectMinecraft(): Promise<{
    status: string;
    minecraft: MinecraftStatus;
  }>;
  runMinecraftGoal(input: string): Promise<MinecraftGoalResponse>;
  emergencyStopMinecraft(): Promise<{
    status: string;
    minecraft: MinecraftStatus;
  }>;
  getChatStatus(): Promise<ChatRuntimeStatus>;
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
  reviewVisionObservation(input: {
    observationId: string;
    rating: VisionQualityRating;
    sceneTags: VisionSceneTag[];
  }): Promise<VisionQualityReviewResponse>;
  resetVisionQualitySession(): Promise<VisionQualityResetResponse>;
  clearVisionApiKey(): Promise<{
    apiKeyConfigured: false;
    persisted: false;
    runtimeDisabled: boolean;
    runtimePreserved: boolean;
  }>;
  listScreenCaptureSources(): Promise<ScreenCaptureSourceListing>;
  captureScreenSource(input: {
    sessionId: string;
    grantSessionId: string;
    sourceToken: string;
    maxSide: 640 | 960 | 1280;
    label: string | null;
    analyzeVision: boolean;
    visionQuestion: string | null;
  }): Promise<DesktopPerceptionCaptureResult>;
  onScreenCaptureProgress(
    listener: (progress: ScreenCaptureProgress) => void,
  ): () => void;
};

interface Window {
  hinaDesktop: HinaDesktopApi;
}
