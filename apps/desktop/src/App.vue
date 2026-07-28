<script setup lang="ts">
import {
  computed,
  defineAsyncComponent,
  onBeforeUnmount,
  onMounted,
  ref,
  watch,
} from "vue";
import { encodePcmWav, mergeAudioChunks, resampleAudio } from "./audio-utils";
import {
  MicrophoneRecorder,
  type MicrophoneCapture,
} from "./microphone-recorder";
import type { FrameMetricsReport } from "./frame-metrics.mjs";

const VrmStage = defineAsyncComponent(() => import("./VrmStage.vue"));
const DesktopWidget = defineAsyncComponent(() => import("./DesktopWidget.vue"));
type DashboardPage =
  | "overview"
  | "chat"
  | "speech"
  | "perception"
  | "resources"
  | "avatar"
  | "live2d"
  | "runtime";

const stateLabels: Record<AvatarState, string> = {
  idle: "Nghỉ",
  listening: "Đang nghe",
  thinking: "Đang suy nghĩ",
  speaking: "Đang nói",
  interrupted: "Bị ngắt",
  error: "Có lỗi",
};

const avatar = ref<AvatarStatus | null>(null);
const windowMode = ref<DesktopWindowMode | null>(null);
const safety = ref<SafetyStatus | null>(null);
const widgetStatus = ref<WidgetStatus | null>(null);
const vtubeStatus = ref<VTubeStudioStatus | null>(null);
const spoutStatus = ref<SpoutBridgeStatus | null>(null);
const vtubeBusy = ref(false);
const vtubeMessage = ref("");
const runtime = ref<RuntimeHealth | null>(null);
const previewState = ref<AvatarState>("idle");
const errorMessage = ref("");
const busy = ref(false);
const activePage = ref<DashboardPage>("avatar");
const chatInput = ref("");
const chatMessages = ref<Array<{ role: "user" | "assistant" | "system"; text: string }>>([]);
const chatBusy = ref(false);
const chatTurnState = ref<AvatarState>("idle");
const chatError = ref("");
const chatVoiceEnabled = ref(true);
const chatSessionId = crypto.randomUUID();
const speechSessionId = crypto.randomUUID();
const speechRecording = ref(false);
const speechBusy = ref(false);
const speechStatus = ref("Sẵn sàng. Bấm Thu mic, nói một câu rồi bấm Dừng & nhận dạng.");
const speechTranscript = ref("");
const speechCorrelationId = ref("");
const speechRuntime = ref<SpeechRuntimeStatus | null>(null);
const ttsRuntime = ref<TtsRuntimeStatus | null>(null);
const speechLiveEnabled = ref(true);
const speechTtsText = ref("Xin chào, mình là Hina. Đây là phần kiểm tra giọng nói tiếng Việt.");
const speechTtsAudioUrl = ref("");
const visionProviderStatus = ref<VisionProviderDashboardStatus | null>(null);
const visionProvider = ref<VisionProviderChoice>("ollama_cloud");
const visionApiKey = ref("");
const visionModels = ref<VisionModelOption[]>([]);
const visionModel = ref("");
const visionBusy = ref(false);
const visionMessage = ref("");
const screenCaptureListing = ref<ScreenCaptureSourceListing | null>(null);
const screenCaptureSourceToken = ref("");
const screenCaptureMaxSide = ref<640 | 960 | 1280>(960);
const screenCaptureLabel = ref("");
const screenCaptureAnalyzeOcr = ref(false);
const screenCaptureAnalyzeVision = ref(false);
const screenCaptureVisionQuestion = ref("");
const screenCaptureBusy = ref(false);
const screenCaptureMessage = ref("");
const screenCaptureResult = ref<DesktopPerceptionCaptureResult | null>(null);
let screenCaptureVisionPreferenceTouched = false;
let removeScreenCaptureProgressListener: (() => void) | null = null;
const resourceStatus = ref<ResourceStatus | null>(null);
const resourceError = ref("");
const resourcePending = ref(false);
const resourceControlBusyId = ref<string | null>(null);
const resourceControlMessage = ref("");
const resourceSamples = ref<Array<{
  sampledAt: number;
  usedVramMiB: number;
  usedRamMiB: number;
  gpuUtilizationPercent: number | null;
}>>([]);
let speechTtsAudio: HTMLAudioElement | null = null;
let speechRecorder: MicrophoneRecorder | null = null;
let speechLivePending = false;
let speechLiveLastSubmittedAt = 0;
let speechLiveEpoch = 0;
let chatPollTimer: number | null = null;
let activeChatTurnId: string | null = null;
const vrmReady = ref(false);
const vrmError = ref("");
const vrmFps = ref(0);
const vrmDisplayName = ref("");
const vrmPresentationId = ref("");
const vrmTextureCount = ref(0);
const vrmStyledMaterialCount = ref(0);
const vrmPerformance = ref<FrameMetricsReport | null>(null);
const vrmStageKey = ref(0);
let avatarTimer: number | null = null;
let safetyTimer: number | null = null;
let widgetTimer: number | null = null;
let spoutTimer: number | null = null;
let resourceTimer: number | null = null;
let avatarRefreshPending = false;
let safetyRefreshPending = false;
let lastResourceLoggedError = "";
let controlRetryAt = 0;
let controlRetryDelay = 1_000;

const selectedScreenCaptureSource = computed(
  () => screenCaptureListing.value?.sources.find(
    (source) => source.sourceToken === screenCaptureSourceToken.value,
  ) ?? null,
);
const perceptionFeatureEnabled = computed(
  () => safety.value?.state.featureFlags?.perception === true,
);
const selectableVisionModels = computed<VisionModelOption[]>(() => {
  const models = [...visionModels.value];
  const persisted = visionProviderStatus.value?.persistence;
  if (
    persisted
    && persisted.provider === visionProvider.value
    && persisted.model
    && !models.some((model) => model.name === persisted.model)
  ) {
    models.unshift({
      name: persisted.model,
      sizeBytes: null,
      parameterSize: null,
      quantization: null,
      capabilities: ["vision"],
      lightweight: true,
      localGpuUsed: persisted.provider === "ollama_local",
    });
  }
  return models;
});
const visionConfigurationActionLabel = computed(() => {
  if (visionProvider.value === "ollama_local") {
    return "Áp dụng và lưu model local";
  }
  if (visionProviderStatus.value?.persistence.apiKeyConfigured) {
    return visionApiKey.value.trim()
      ? "Ghi đè API key và giữ model này"
      : "Dùng API key và model đã lưu";
  }
  return "Lưu API key và model";
});

function controlRequestAllowed(): boolean {
  return Date.now() >= controlRetryAt;
}

function noteControlFailure(error: unknown): void {
  const message = error instanceof Error ? error.message : "E_DESKTOP_CONTROL_OFFLINE";
  errorMessage.value = message;
  console.error("[hina-operator] E_DESKTOP_CONTROL", message);
  if (message.includes("E_DESKTOP_CONTROL_OFFLINE")) {
    controlRetryAt = Date.now() + controlRetryDelay;
    controlRetryDelay = Math.min(controlRetryDelay * 2, 30_000);
  }
}

function resetControlBackoff(): void {
  controlRetryAt = 0;
  controlRetryDelay = 1_000;
}

function appendChatMessage(role: "user" | "assistant" | "system", text: string): void {
  chatMessages.value.push({ role, text });
}

async function playAssistantVoice(text: string): Promise<void> {
  if (!chatVoiceEnabled.value || safety.value?.state.muted || !text.trim()) return;
  const bytes = await window.hinaDesktop.synthesizeSpeech({
    text,
    utteranceId: crypto.randomUUID(),
    sessionId: chatSessionId,
    source: "owner.console",
  });
  const wavBuffer = Uint8Array.from(bytes).buffer;
  const url = URL.createObjectURL(new Blob([wavBuffer], { type: "audio/wav" }));
  const audio = new Audio(url);
  audio.addEventListener("ended", () => URL.revokeObjectURL(url), { once: true });
  await audio.play();
}

async function pollDesktopChat(turnId: string): Promise<void> {
  try {
    const turn = await window.hinaDesktop.getChatTurn(turnId);
    if (turn.state) {
      chatTurnState.value = turn.state;
    } else if (turn.outcome === "running") {
      chatTurnState.value = "thinking";
    }
    if (turn.outcome === "running") {
      chatPollTimer = window.setTimeout(() => void pollDesktopChat(turnId), 180);
      return;
    }
    activeChatTurnId = null;
    chatBusy.value = false;
    const completedState = turn.outcome === "completed" ? "idle" : turn.outcome === "interrupted" ? "interrupted" : "error";
    chatTurnState.value = completedState;
    if (turn.outcome === "completed" && turn.assistant) {
      appendChatMessage("assistant", turn.assistant);
      try {
        await playAssistantVoice(turn.assistant);
      } catch (error) {
        chatError.value = error instanceof Error ? error.message : "E_DESKTOP_TTS";
        console.error("[hina-chat] E_DESKTOP_TTS", chatError.value);
      }
    } else if (turn.outcome === "interrupted") {
      appendChatMessage("system", "Cuộc trò chuyện đã được dừng.");
    } else {
      const failure = `${turn.errorCode ?? "E_CHAT_FAILED"}: ${turn.errorMessage ?? "AI không thể trả lời."}`;
      chatError.value = failure;
      appendChatMessage("system", failure);
      console.error(
        `[hina-chat] ${turn.errorCode ?? "E_CHAT_FAILED"}`,
        turn.errorMessage ?? "AI không thể trả lời.",
        `correlationId=${turn.correlationId ?? "unknown"}`,
      );
    }
  } catch (error) {
    activeChatTurnId = null;
    chatBusy.value = false;
    chatTurnState.value = "error";
    chatError.value = error instanceof Error ? error.message : "E_DESKTOP_CHAT";
    console.error("[hina-chat] E_DESKTOP_CHAT_POLL", chatError.value);
  }
}

async function sendDesktopChat(): Promise<void> {
  const text = chatInput.value.trim();
  if (!text || chatBusy.value) return;
  chatBusy.value = true;
  chatTurnState.value = "thinking";
  chatError.value = "";
  appendChatMessage("user", text);
  chatInput.value = "";
  try {
    const turn = await window.hinaDesktop.startChatTurn({
      sessionId: chatSessionId,
      source: "owner.console",
      text,
    });
    activeChatTurnId = turn.turnId;
    await pollDesktopChat(turn.turnId);
  } catch (error) {
    chatBusy.value = false;
    chatTurnState.value = "error";
    chatError.value = error instanceof Error ? error.message : "E_DESKTOP_CHAT";
    appendChatMessage("system", chatError.value);
    console.error("[hina-chat] E_DESKTOP_CHAT_START", chatError.value);
  }
}

async function cancelDesktopChat(): Promise<void> {
  if (!activeChatTurnId) return;
  try {
    await window.hinaDesktop.cancelChatTurn(activeChatTurnId);
  } catch (error) {
    chatError.value = error instanceof Error ? error.message : "E_DESKTOP_CHAT_CANCEL";
  }
  activeChatTurnId = null;
  chatBusy.value = false;
  chatTurnState.value = "interrupted";
}

function cleanupSpeechRecorder(): void {
  const current = speechRecorder;
  speechRecorder = null;
  speechRecording.value = false;
  if (!current) return;
  void current.stop();
}

function captureToWav(capture: Readonly<MicrophoneCapture>): Uint8Array {
  return encodePcmWav(
    resampleAudio(
      mergeAudioChunks(capture.chunks, capture.sampleCount),
      capture.sampleRate,
      16_000,
    ),
    16_000,
  );
}

async function refreshSpeechRuntime(): Promise<void> {
  try {
    const [speech, tts] = await Promise.all([
      window.hinaDesktop.getSpeechStatus(),
      window.hinaDesktop.getTtsStatus(),
    ]);
    speechRuntime.value = speech;
    ttsRuntime.value = tts;
  } catch (error) {
    console.error(
      "[hina-speech-test] E_DESKTOP_STT_STATUS",
      error instanceof Error ? error.message : "unknown error",
    );
  }
}

function formatVisionModelSize(bytes: number | null): string {
  if (bytes === null) return "Cloud / không tải vào máy";
  return `${(bytes / 1024 ** 3).toFixed(1)} GB`;
}

async function refreshVisionProviderStatus(): Promise<void> {
  try {
    visionProviderStatus.value = await window.hinaDesktop.getVisionProviderStatus();
    const persisted = visionProviderStatus.value.persistence;
    if (persisted.provider !== "disabled") {
      visionProvider.value = persisted.provider;
      visionModel.value = persisted.model ?? "";
    }
    if (!screenCaptureVisionPreferenceTouched) {
      screenCaptureAnalyzeVision.value =
        visionProviderStatus.value.runtime.available;
    }
    if (
      !visionMessage.value
      && persisted.provider === "ollama_cloud"
      && persisted.model
      && persisted.apiKeyConfigured
    ) {
      visionMessage.value =
        `Đã khôi phục API key mã hóa và model ${persisted.model}. `
        + "Bạn có thể dùng ngay, để trống ô key để giữ nguyên hoặc dán key mới để ghi đè.";
    }
  } catch (error) {
    visionMessage.value = error instanceof Error
      ? error.message
      : "E_DESKTOP_VISION_STATUS";
    console.error("[hina-vision] E_DESKTOP_VISION_STATUS", visionMessage.value);
  }
}

async function discoverVisionModels(): Promise<void> {
  if (visionBusy.value) return;
  visionBusy.value = true;
  visionMessage.value = "Đang đọc danh sách model và kiểm tra capability vision…";
  try {
    const suppliedApiKey = visionApiKey.value.trim();
    const result = await window.hinaDesktop.discoverVisionModels({
      provider: visionProvider.value,
      ...(suppliedApiKey ? { apiKey: suppliedApiKey } : {}),
    });
    visionModels.value = result.models;
    if (!result.models.some((item) => item.name === visionModel.value)) {
      visionModel.value = result.models[0]?.name ?? "";
    }
    visionMessage.value = result.count
      ? `Đã tìm thấy ${result.count} model đọc ảnh. Chỉ model khai báo capability vision mới được hiển thị.`
      : "Không tìm thấy model đọc ảnh nào. Với Ollama local, hãy pull một model vision nhẹ trước.";
  } catch (error) {
    visionMessage.value = error instanceof Error
      ? error.message
      : "E_DESKTOP_VISION_DISCOVERY";
    console.error("[hina-vision] E_DESKTOP_VISION_DISCOVERY", visionMessage.value);
  } finally {
    visionBusy.value = false;
  }
}

async function applyVisionProvider(): Promise<void> {
  if (visionBusy.value || !visionModel.value) return;
  visionBusy.value = true;
  const suppliedApiKey = visionApiKey.value.trim();
  visionMessage.value = suppliedApiKey
    && visionProviderStatus.value?.persistence.apiKeyConfigured
    ? "Đang xác minh và ghi đè API key đã lưu…"
    : "Đang xác minh model và lưu cấu hình bảo mật…";
  try {
    await window.hinaDesktop.configureVisionProvider({
      provider: visionProvider.value,
      model: visionModel.value,
      ...(suppliedApiKey ? { apiKey: suppliedApiKey } : {}),
    });
    visionApiKey.value = "";
    visionMessage.value = visionProvider.value === "ollama_cloud"
      ? `Đã lưu API key bằng mã hóa Windows và giữ model ${visionModel.value}. `
        + "Lần sau mở Hina bạn không cần nhập hoặc chọn lại; dán key khác rồi bấm ghi đè nếu muốn thay."
      : "Đã lưu model Ollama local. Model chỉ được chạy qua GPU scheduler và tự unload sau mỗi lượt.";
    await refreshVisionProviderStatus();
  } catch (error) {
    visionMessage.value = error instanceof Error
      ? error.message
      : "E_DESKTOP_VISION_CONFIG";
    console.error("[hina-vision] E_DESKTOP_VISION_CONFIG", visionMessage.value);
  } finally {
    visionBusy.value = false;
  }
}

async function clearVisionProviderKey(): Promise<void> {
  if (visionBusy.value) return;
  visionBusy.value = true;
  try {
    const result = await window.hinaDesktop.clearVisionApiKey();
    visionApiKey.value = "";
    visionModels.value = [];
    visionMessage.value = result.runtimePreserved
      ? "Đã xóa key Cloud đã mã hóa. Model Ollama local hiện tại vẫn được giữ nguyên."
      : result.runtimeDisabled
        ? "Đã xóa key mã hóa và tắt provider Cloud trong runtime."
        : "Đã xóa key mã hóa. Runtime đang offline nên sẽ giữ trạng thái tắt ở lần khởi động sau.";
    await refreshVisionProviderStatus();
  } catch (error) {
    visionMessage.value = error instanceof Error
      ? error.message
      : "E_DESKTOP_VISION_CLEAR";
  } finally {
    visionBusy.value = false;
  }
}

async function listScreenCaptureSources(): Promise<void> {
  if (screenCaptureBusy.value) return;
  screenCaptureBusy.value = true;
  screenCaptureMessage.value =
    "Đang đọc ảnh xem trước của các màn hình và cửa sổ hiện có…";
  screenCaptureResult.value = null;
  try {
    const listing = await window.hinaDesktop.listScreenCaptureSources();
    screenCaptureListing.value = listing;
    screenCaptureSourceToken.value = listing.sources[0]?.sourceToken ?? "";
    screenCaptureMessage.value =
      `Đã tìm thấy ${listing.sourceCount} nguồn. Grant chỉ dùng một lần và hết hạn sau 60 giây.`;
  } catch (error) {
    screenCaptureListing.value = null;
    screenCaptureSourceToken.value = "";
    screenCaptureMessage.value = error instanceof Error
      ? error.message
      : "E_DESKTOP_CAPTURE_SOURCES";
    console.error(
      "[hina-screen-capture] E_DESKTOP_CAPTURE_SOURCES",
      screenCaptureMessage.value,
    );
  } finally {
    screenCaptureBusy.value = false;
  }
}

async function togglePerceptionFeature(): Promise<void> {
  if (screenCaptureBusy.value || !safety.value) return;
  screenCaptureBusy.value = true;
  try {
    await window.hinaDesktop.applySafetyControl({
      action: "set_feature",
      feature: "perception",
      enabled: !perceptionFeatureEnabled.value,
    });
    await refreshSafety();
    screenCaptureMessage.value = perceptionFeatureEnabled.value
      ? "Đã bật quyền Quan sát màn hình. Hina vẫn chỉ chụp khi bạn bấm nút gửi."
      : "Đã tắt quyền Quan sát màn hình. Mọi lượt chụp mới sẽ bị chặn.";
  } catch (error) {
    screenCaptureMessage.value = error instanceof Error
      ? error.message
      : "E_DESKTOP_CAPTURE_SAFETY";
    console.error(
      "[hina-screen-capture] E_DESKTOP_CAPTURE_SAFETY",
      screenCaptureMessage.value,
    );
  } finally {
    screenCaptureBusy.value = false;
  }
}

async function captureSelectedScreenSource(): Promise<void> {
  const listing = screenCaptureListing.value;
  const source = selectedScreenCaptureSource.value;
  if (screenCaptureBusy.value || !listing || !source) return;
  screenCaptureBusy.value = true;
  screenCaptureResult.value = null;
  screenCaptureMessage.value =
    `Đang chụp toàn bộ “${source.name}”, hạ cạnh dài xuống tối đa ${screenCaptureMaxSide.value} px…`;
  try {
    const result = await window.hinaDesktop.captureScreenSource({
      sessionId: chatSessionId,
      grantSessionId: listing.grantSessionId,
      sourceToken: source.sourceToken,
      maxSide: screenCaptureMaxSide.value,
      label: screenCaptureLabel.value.trim() || null,
      analyzeOcr: screenCaptureAnalyzeOcr.value,
      analyzeVision: screenCaptureAnalyzeVision.value,
      visionQuestion: screenCaptureAnalyzeVision.value
        ? screenCaptureVisionQuestion.value.trim() || null
        : null,
    });
    screenCaptureResult.value = result;
    screenCaptureMessage.value = describeScreenCaptureResult(result);
    if (result.observation?.vision?.state === "error") {
      const code = visionAnalysisErrorCode(result.observation.vision);
      console.error(
        "[hina-screen-capture] E_PERCEPTION_VISION",
        code,
        `correlationId=${result.correlationId}`,
      );
      await refreshVisionProviderStatus();
    }
  } catch (error) {
    screenCaptureMessage.value = error instanceof Error
      ? error.message
      : "E_DESKTOP_CAPTURE_IMAGE";
    console.error(
      "[hina-screen-capture] E_DESKTOP_CAPTURE_IMAGE",
      screenCaptureMessage.value,
    );
  } finally {
    // A grant is deliberately single-use even when the source disappears or
    // the downstream provider rejects the request.
    screenCaptureListing.value = null;
    screenCaptureSourceToken.value = "";
    screenCaptureBusy.value = false;
  }
}

function handleScreenCaptureProgress(progress: ScreenCaptureProgress): void {
  if (!screenCaptureBusy.value) return;
  if (progress.phase === "capturing") {
    screenCaptureMessage.value =
      `Đang lấy đúng một khung hình từ “${progress.sourceName}”…`;
    return;
  }
  if (progress.phase === "encoding") {
    screenCaptureMessage.value =
      `Đã lấy khung hình. Đang hạ cạnh dài xuống tối đa ${progress.requestedMaxSide} px và nén PNG…`;
    return;
  }
  const dimensions = progress.width && progress.height
    ? `${progress.width}×${progress.height}`
    : "khung hình";
  const size = typeof progress.bytes === "number"
    ? ` · ${Math.ceil(progress.bytes / 1024)} KB`
    : "";
  screenCaptureMessage.value = screenCaptureAnalyzeVision.value
    ? `Ảnh ${dimensions}${size} đã gửi. Hina đang phân tích bằng model vision; chụp và nén đã xong.`
    : `Ảnh ${dimensions}${size} đã gửi tới Hina để xử lý.`;
}

function markScreenCaptureVisionPreference(): void {
  screenCaptureVisionPreferenceTouched = true;
}

async function askHinaAboutLastCapture(): Promise<void> {
  const observation = screenCaptureResult.value?.observation;
  const hasSemanticContext = (
    observation?.vision?.state === "ready"
    || observation?.ocr?.state === "ready"
  );
  if (!hasSemanticContext || chatBusy.value) return;
  activePage.value = "chat";
  chatInput.value = screenCaptureVisionQuestion.value.trim()
    || "Dựa trên ảnh vừa chụp, hãy mô tả ngắn gọn điều đáng chú ý.";
  await sendDesktopChat();
}

function visionAnalysisErrorCode(
  vision: NonNullable<
    NonNullable<DesktopPerceptionCaptureResult["observation"]>["vision"]
  >,
): string {
  return (
    vision.providerErrorCode
    || vision.modelErrorCode
    || vision.errorCode
    || "E_PERCEPTION_VISION"
  );
}

function describeScreenCaptureResult(
  result: DesktopPerceptionCaptureResult,
): string {
  const prefix = result.status === "duplicate"
    ? "Ảnh trùng với quan sát còn hạn."
    : (
      `Đã gửi ảnh ${result.desktopCapture.width}×${result.desktopCapture.height} `
      + `(${Math.ceil(result.desktopCapture.bytes / 1024)} KB).`
    );
  const timings = result.desktopCapture.timings;
  const timingSuffix = timings
    ? ` Chụp/nén ${formatMilliseconds(timings.sourceLookupMilliseconds + timings.encodingMilliseconds)} · runtime ${formatMilliseconds(timings.runtimeMilliseconds)} · tổng ${formatMilliseconds(timings.totalMilliseconds)}.`
    : "";
  const vision = result.observation?.vision;
  if (vision?.state === "ready" && vision.summary) {
    return `${prefix} Model vision đã phân tích thành công.${timingSuffix}`;
  }
  if (vision?.requested && vision.state !== "ready") {
    return `${prefix} Phân tích vision thất bại: ${visionAnalysisErrorCode(vision)}.${timingSuffix}`;
  }
  const ocr = result.observation?.ocr;
  if (ocr?.state === "ready") {
    return `${prefix} OCR đã đọc ảnh; model vision chưa được yêu cầu.${timingSuffix}`;
  }
  if (ocr?.requested && ocr.state !== "ready") {
    return `${prefix} OCR thất bại: ${ocr.errorCode || "E_PERCEPTION_OCR"}.${timingSuffix}`;
  }
  return (
    `${prefix} Ảnh mới chỉ được nhận làm evidence, chưa được phân tích nội dung. `
    + `Hãy bật “Phân tích bằng model vision” hoặc OCR trước khi chụp.${timingSuffix}`
  );
}

async function updateLiveTranscript(
  capture: Readonly<MicrophoneCapture>,
  epoch: number,
): Promise<void> {
  const elapsedSeconds = capture.sampleCount / capture.sampleRate;
  const now = Date.now();
  if (
    !speechLiveEnabled.value
    || elapsedSeconds < 1
    || speechLivePending
    || now - speechLiveLastSubmittedAt < 1_000
  ) return;
  const wav = captureToWav(capture);
  if (wav.byteLength > 1_048_576) return;
  speechLivePending = true;
  speechLiveLastSubmittedAt = now;
  try {
    const result = await window.hinaDesktop.transcribeSpeech(wav, speechSessionId);
    if (speechRecording.value && epoch === speechLiveEpoch) {
      speechTranscript.value = result.transcript.trim();
      speechCorrelationId.value = result.correlationId;
      speechStatus.value = result.speechDetected
        ? `Realtime: ${result.processingMilliseconds} ms · tiếp tục nói hoặc bấm Dừng.`
        : "Realtime đang nghe; chưa phát hiện giọng nói rõ.";
    }
  } catch (error) {
    if (speechRecording.value && epoch === speechLiveEpoch) {
      const message = error instanceof Error ? error.message : "E_DESKTOP_STT_LIVE";
      speechStatus.value = message;
      console.error("[hina-speech-test] E_DESKTOP_STT_LIVE", message);
    }
  } finally {
    speechLivePending = false;
  }
}

async function stopSpeechTest(): Promise<void> {
  const current = speechRecorder;
  if (!current) return;
  speechRecorder = null;
  speechRecording.value = false;
  speechLiveEpoch += 1;
  const capture = await current.stop();
  if (capture.sampleCount < capture.sampleRate * 0.25) {
    speechStatus.value = "Audio quá ngắn. Hãy nói ít nhất khoảng 0,25 giây.";
    return;
  }
  const wav = captureToWav(capture);
  if (wav.byteLength > 1_048_576) {
    speechStatus.value = "Audio vượt giới hạn 1 MiB. Hãy thử một câu ngắn hơn.";
    return;
  }
  speechBusy.value = true;
  speechStatus.value = "Đang tạo transcript cuối bằng STT local…";
  speechCorrelationId.value = "";
  try {
    const result = await window.hinaDesktop.transcribeSpeech(wav, speechSessionId);
    speechTranscript.value = result.transcript.trim();
    speechCorrelationId.value = result.correlationId;
    speechStatus.value = result.speechDetected
      ? `STT hoàn tất trong ${result.processingMilliseconds} ms.`
      : "STT không phát hiện tiếng nói trong đoạn thu.";
  } catch (error) {
    const message = error instanceof Error ? error.message : "E_DESKTOP_STT";
    speechStatus.value = message;
    console.error("[hina-speech-test] E_DESKTOP_STT", message);
  } finally {
    speechBusy.value = false;
  }
}

async function startSpeechTest(): Promise<void> {
  if (speechBusy.value || speechRecording.value) return;
  if (!navigator.mediaDevices?.getUserMedia) {
    speechStatus.value = "Thiết bị hiện tại không cung cấp quyền microphone.";
    return;
  }
  try {
    speechLiveEpoch += 1;
    const epoch = speechLiveEpoch;
    speechLiveLastSubmittedAt = 0;
    speechTranscript.value = "";
    speechCorrelationId.value = "";
    speechRecorder = await MicrophoneRecorder.start({
      maximumSeconds: 30,
      chunkNotificationMilliseconds: 250,
      onChunk: (capture) => void updateLiveTranscript(capture, epoch),
      onMaximumDuration: () => void stopSpeechTest(),
    });
    speechRecording.value = true;
    speechStatus.value = speechLiveEnabled.value
      ? "Đang thu mic và cập nhật transcript realtime…"
      : "Đang thu mic… nói một câu, sau đó bấm Dừng & nhận dạng.";
  } catch (error) {
    cleanupSpeechRecorder();
    const message = error instanceof Error ? error.message : "E_DESKTOP_MIC_PERMISSION";
    speechStatus.value = message;
    console.error("[hina-speech-test] E_DESKTOP_MIC_PERMISSION", message);
  }
}

async function testTtsVoice(): Promise<void> {
  const text = speechTtsText.value.trim();
  if (!text || speechBusy.value || speechRecording.value) return;
  speechBusy.value = true;
  speechStatus.value = "Đang tạo WAV 24 kHz bằng giọng Hina/OmniVoice thật trên GPU…";
  try {
    const bytes = await window.hinaDesktop.synthesizeSpeech({
      text,
      utteranceId: crypto.randomUUID(),
      sessionId: speechSessionId,
      source: "owner.console",
    });
    if (speechTtsAudioUrl.value) URL.revokeObjectURL(speechTtsAudioUrl.value);
    speechTtsAudio?.pause();
    speechTtsAudioUrl.value = URL.createObjectURL(
      new Blob([Uint8Array.from(bytes)], { type: "audio/wav" }),
    );
    speechTtsAudio = new Audio(speechTtsAudioUrl.value);
    await speechTtsAudio.play();
    speechStatus.value = "TTS hoàn tất và đang phát. Bạn cũng có thể dùng thanh audio để nghe lại.";
  } catch (error) {
    const message = error instanceof Error ? error.message : "E_DESKTOP_TTS";
    speechStatus.value = message;
    console.error("[hina-speech-test] E_DESKTOP_TTS", message);
  } finally {
    speechBusy.value = false;
  }
}

function cleanupSpeechTest(): void {
  cleanupSpeechRecorder();
  speechTtsAudio?.pause();
  speechTtsAudio = null;
  if (speechTtsAudioUrl.value) {
    URL.revokeObjectURL(speechTtsAudioUrl.value);
    speechTtsAudioUrl.value = "";
  }
}

const stageState = computed(() => avatar.value?.state ?? "error");
const stageExpression = computed(() => avatar.value?.expression ?? "concerned");
const stageViseme = computed(() => avatar.value?.viseme ?? "sil");
const stageIntensity = computed(() => (
  avatar.value?.state === "speaking"
    ? Math.min(1, Math.max(0, avatar.value.intensity))
    : 0
));
const stageMouthRx = computed(() => {
  const targetWidth = {
    sil: 31,
    A: 28,
    I: 35,
    U: 18,
    E: 33,
    O: 22,
  }[stageViseme.value];
  return 31 + (targetWidth - 31) * stageIntensity.value;
});
const stageMouthRy = computed(() => {
  const targetHeight = {
    sil: 0,
    A: 25,
    I: 14,
    U: 19,
    E: 16,
    O: 23,
  }[stageViseme.value];
  return 7 + targetHeight * stageIntensity.value;
});
const connected = computed(() => runtime.value?.status === "ready");
const resourceTelemetry = computed(
  () => resourceStatus.value?.physical.telemetry ?? null,
);
const resourceLoadedCount = computed(
  () => resourceStatus.value?.models.filter(
    (model) => model.state === "loaded" || model.state === "loading",
  ).length ?? 0,
);
const resourceCloudCount = computed(
  () => resourceStatus.value?.models.filter(
    (model) => model.state === "cloud-ready",
  ).length ?? 0,
);
const resourceLargestLease = computed(() => {
  const leases = resourceStatus.value?.physical.leases ?? [];
  return leases.reduce<ResourceLease | null>(
    (largest, lease) => (
      largest === null || lease.reservedVramMiB > largest.reservedVramMiB
        ? lease
        : largest
    ),
    null,
  );
});
const resourceAnalysis = computed(() => {
  const status = resourceStatus.value;
  const telemetry = resourceTelemetry.value;
  if (!status) {
    return {
      level: "waiting",
      title: "Đang lấy số liệu thật",
      message: "Trang chỉ bắt đầu đo khi bạn mở mục này.",
    };
  }
  if (!status.physical.available || !telemetry) {
    return {
      level: "unavailable",
      title: "Chưa đọc được GPU",
      message: `NVIDIA telemetry tạm thời không sẵn sàng (${status.physical.errorCode ?? "E_RESOURCE_TELEMETRY"}). RAM và trạng thái model vẫn được giữ nếu runtime cung cấp.`,
    };
  }
  const overCeiling =
    telemetry.usedVramMiB > status.limits.allOnVramCeilingMiB;
  const belowHeadroom =
    telemetry.freeVramMiB < status.limits.minimumFreeVramMiB;
  if (overCeiling || belowHeadroom) {
    return {
      level: "danger",
      title: "Đã chạm vùng không an toàn",
      message: `GPU đang dùng ${formatMiB(telemetry.usedVramMiB)} và chỉ còn ${formatMiB(telemetry.freeVramMiB)}. Hina phải nhường hoặc unload model trước tác vụ GPU tiếp theo.`,
    };
  }
  if (
    telemetry.usedVramMiB > status.limits.allOnVramCeilingMiB - 1_024
    || telemetry.freeVramMiB < status.limits.minimumFreeVramMiB + 1_024
  ) {
    return {
      level: "warning",
      title: "Đang gần giới hạn",
      message: `Phần VRAM còn trống là ${formatMiB(telemetry.freeVramMiB)}. Hãy tránh chạy thêm game hoặc model GPU nặng cùng lúc.`,
    };
  }
  return {
    level: "healthy",
    title: "Tài nguyên đang cân bằng",
    message: `Còn ${formatMiB(telemetry.freeVramMiB)} VRAM. NVIDIA đã trừ phần Windows và app khác; scheduler so từng model với phần trống thật này.`,
  };
});
const resourceVramPercent = computed(() => {
  const telemetry = resourceTelemetry.value;
  return telemetry
    ? Math.min(100, (telemetry.usedVramMiB / telemetry.totalVramMiB) * 100)
    : 0;
});
const resourceRamPercent = computed(() => {
  const telemetry = resourceTelemetry.value;
  return telemetry
    ? Math.min(100, (telemetry.usedRamMiB / telemetry.totalRamMiB) * 100)
    : 0;
});

function formatMiB(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "Không rõ";
  if (value >= 1_024) {
    return `${(value / 1_024).toLocaleString("vi-VN", {
      minimumFractionDigits: 1,
      maximumFractionDigits: 1,
    })} GB`;
  }
  return `${Math.round(value).toLocaleString("vi-VN")} MB`;
}

function formatMilliseconds(value: number): string {
  if (!Number.isFinite(value) || value < 0) return "không rõ";
  if (value < 1_000) return `${Math.round(value)} ms`;
  return `${(value / 1_000).toLocaleString("vi-VN", { maximumFractionDigits: 1 })} giây`;
}

function formatMetric(value: number | null | undefined, suffix: string): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "Không hỗ trợ";
  return `${value.toLocaleString("vi-VN", { maximumFractionDigits: 1 })}${suffix}`;
}

function resourceStateLabel(state: ResourceModelState): string {
  return {
    loaded: "Đã load",
    loading: "Đang dùng / đang load",
    unloaded: "Đã unload",
    unavailable: "Không sẵn sàng",
    unconfigured: "Chưa cấu hình",
    "cloud-ready": "Cloud sẵn sàng",
  }[state];
}

function resourceTransitionLabel(
  transition: ResourceModelTransition,
): string {
  if (transition.action === "loaded") return "vừa được load";
  if (transition.action === "unloaded") return "vừa được unload";
  if (transition.action === "observed") {
    return `được ghi nhận ở trạng thái “${resourceStateLabel(transition.toState)}”`;
  }
  return `đổi sang “${resourceStateLabel(transition.toState)}”`;
}

function formatResourceTime(value: number): string {
  return new Date(value).toLocaleTimeString("vi-VN", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

function resourceSparklinePoints(
  metric: "usedVramMiB" | "usedRamMiB" | "gpuUtilizationPercent",
): string {
  const samples = resourceSamples.value;
  if (samples.length === 0) return "";
  const telemetry = resourceTelemetry.value;
  const maximum = metric === "gpuUtilizationPercent"
    ? 100
    : metric === "usedVramMiB"
      ? telemetry?.totalVramMiB ?? Math.max(...samples.map((sample) => sample.usedVramMiB), 1)
      : telemetry?.totalRamMiB ?? Math.max(...samples.map((sample) => sample.usedRamMiB), 1);
  return samples.map((sample, index) => {
    const raw = sample[metric];
    const value = raw === null ? 0 : raw;
    const x = samples.length === 1 ? 300 : (index / (samples.length - 1)) * 300;
    const y = 72 - Math.min(1, Math.max(0, value / maximum)) * 64;
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  }).join(" ");
}
const snapshot = computed(() => avatar.value
  ? JSON.stringify({
      state: avatar.value.state,
      expression: avatar.value.expression,
      viseme: avatar.value.viseme,
      intensity: avatar.value.intensity,
      source: avatar.value.source,
      mode: avatar.value.mode,
      sequence: avatar.value.sequence,
      updatedAt: avatar.value.updatedAt,
      correlationId: avatar.value.correlationId,
      turnId: avatar.value.turnId,
      utteranceId: avatar.value.utteranceId,
      asset: avatar.value.asset,
      lipSync: avatar.value.lipSync,
      desktopRenderer: {
        vrmLoaded: vrmReady.value,
        displayName: vrmDisplayName.value || null,
        presentationId: vrmPresentationId.value || null,
        loadedTextureCount: vrmTextureCount.value,
        styledMaterialCount: vrmStyledMaterialCount.value,
        fps: vrmFps.value || null,
        performance: vrmPerformance.value,
        developmentSample: true,
        phonemeAccurate: false,
      },
    }, null, 2)
  : "Chưa nhận được snapshot từ control plane.");

async function refreshAvatar(): Promise<void> {
  if (avatarRefreshPending || !controlRequestAllowed()) return;
  avatarRefreshPending = true;
  try {
    avatar.value = await window.hinaDesktop.getAvatarStatus();
    errorMessage.value = "";
  } catch (error) {
    noteControlFailure(error);
  } finally {
    avatarRefreshPending = false;
  }
}

async function refreshSafety(): Promise<void> {
  if (safetyRefreshPending || !controlRequestAllowed()) return;
  safetyRefreshPending = true;
  try {
    const [nextSafety, nextRuntime] = await Promise.all([
      window.hinaDesktop.getSafetyStatus(),
      window.hinaDesktop.getRuntimeHealth(),
    ]);
    safety.value = nextSafety;
    runtime.value = nextRuntime;
  } catch (error) {
    runtime.value = null;
    noteControlFailure(error);
  } finally {
    safetyRefreshPending = false;
  }
}

async function refreshResources(): Promise<void> {
  if (
    resourcePending.value
    || activePage.value !== "resources"
    || windowMode.value !== "operator"
  ) return;
  resourcePending.value = true;
  try {
    const next = await window.hinaDesktop.getResourceStatus();
    resourceStatus.value = next;
    resourceError.value = "";
    lastResourceLoggedError = "";
    const telemetry = next.physical.telemetry;
    if (
      telemetry
      && resourceSamples.value.at(-1)?.sampledAt !== next.sampledAtUnixMilliseconds
    ) {
      resourceSamples.value.push({
        sampledAt: next.sampledAtUnixMilliseconds,
        usedVramMiB: telemetry.usedVramMiB,
        usedRamMiB: telemetry.usedRamMiB,
        gpuUtilizationPercent: telemetry.gpuUtilizationPercent,
      });
      if (resourceSamples.value.length > 60) {
        resourceSamples.value.splice(0, resourceSamples.value.length - 60);
      }
    }
    document.documentElement.dataset.resourceMonitorState =
      resourceAnalysis.value.level;
    document.documentElement.dataset.resourceModelCount =
      String(next.models.length);
    document.documentElement.dataset.resourceSampleCount =
      String(resourceSamples.value.length);
  } catch (error) {
    const message = error instanceof Error
      ? error.message
      : "E_DESKTOP_RESOURCE_STATUS";
    resourceError.value = message;
    document.documentElement.dataset.resourceMonitorState = "error";
    if (lastResourceLoggedError !== message) {
      console.error("[hina-resource-monitor] E_DESKTOP_RESOURCE_STATUS", message);
      lastResourceLoggedError = message;
    }
  } finally {
    resourcePending.value = false;
  }
}

async function controlResourceModel(
  model: ResourceModel,
  action: "load" | "unload",
): Promise<void> {
  if (
    resourceControlBusyId.value !== null
    || !model.controlSupported
    || model.location === "cloud"
  ) {
    return;
  }
  resourceControlBusyId.value = model.id;
  resourceControlMessage.value = "";
  try {
    const result = await window.hinaDesktop.controlResourceModel(model.id, action);
    if (result.resources) {
      resourceStatus.value = result.resources;
    }
    resourceControlMessage.value = result.message;
    resourceError.value = "";
  } catch (error) {
    resourceControlMessage.value = "";
    resourceError.value = error instanceof Error
      ? error.message
      : "E_DESKTOP_RESOURCE_CONTROL";
    console.error(
      "[hina-resource-monitor] E_DESKTOP_RESOURCE_CONTROL",
      resourceError.value,
      `modelId=${model.id}`,
      `action=${action}`,
    );
  } finally {
    resourceControlBusyId.value = null;
    await refreshResources();
  }
}

function startResourcePolling(): void {
  if (resourceTimer !== null || windowMode.value !== "operator") return;
  void refreshResources();
  resourceTimer = window.setInterval(() => void refreshResources(), 1_500);
}

function stopResourcePolling(): void {
  if (resourceTimer !== null) {
    window.clearInterval(resourceTimer);
    resourceTimer = null;
  }
}

async function refreshWidget(): Promise<void> {
  if (!controlRequestAllowed()) return;
  try {
    widgetStatus.value = await window.hinaDesktop.getWidgetStatus();
  } catch (error) {
    noteControlFailure(error);
  }
}

async function refreshVTubeStudioStatus(
  refreshRemote = false,
): Promise<void> {
  try {
    vtubeStatus.value = refreshRemote && vtubeStatus.value?.authenticated
      ? await window.hinaDesktop.refreshVTubeStudio()
      : await window.hinaDesktop.getVTubeStudioStatus();
  } catch (error) {
    vtubeMessage.value = error instanceof Error
      ? error.message
      : "E_VTS_STATUS";
    vtubeStatus.value = await window.hinaDesktop.getVTubeStudioStatus();
  }
}

async function refreshSpoutStatus(): Promise<void> {
  try {
    spoutStatus.value = await window.hinaDesktop.getSpoutStatus();
  } catch (error) {
    console.error(
      "[hina-operator] E_SPOUT_STATUS",
      error instanceof Error ? error.message : "E_SPOUT_STATUS",
    );
    spoutStatus.value = null;
  }
}

async function connectVTubeStudio(): Promise<void> {
  if (vtubeBusy.value) return;
  vtubeBusy.value = true;
  vtubeMessage.value =
    "Đang kết nối. Nếu VTube Studio hỏi quyền plugin, hãy bấm Allow.";
  try {
    vtubeStatus.value = await window.hinaDesktop.connectVTubeStudio();
    vtubeMessage.value = vtubeStatus.value.authenticated
      ? vtubeStatus.value.model.loaded
        ? "Đã kết nối. Hina đang điều khiển model Live2D đã chọn trong VTube Studio."
        : "Đã kết nối Plugin API, nhưng VTube Studio chưa tải model Live2D. Hãy chọn model trong cửa sổ chính rồi bấm “Đọc lại model”."
      : "VTube Studio chưa cấp quyền plugin; hãy bấm kết nối lại và chọn Allow.";
  } catch (error) {
    vtubeMessage.value = error instanceof Error
      ? error.message
      : "E_VTS_CONNECT";
    await refreshVTubeStudioStatus();
  } finally {
    vtubeBusy.value = false;
  }
}

async function disconnectVTubeStudio(): Promise<void> {
  if (vtubeBusy.value) return;
  vtubeBusy.value = true;
  try {
    vtubeStatus.value = await window.hinaDesktop.disconnectVTubeStudio();
    vtubeMessage.value =
      "Đã ngắt VTube Studio. Widget VRM local vẫn hoạt động bình thường.";
  } catch (error) {
    vtubeMessage.value = error instanceof Error
      ? error.message
      : "E_VTS_DISCONNECT";
  } finally {
    vtubeBusy.value = false;
  }
}

async function triggerVTubeStudioHotkey(hotkeyId: string): Promise<void> {
  if (vtubeBusy.value) return;
  vtubeBusy.value = true;
  try {
    vtubeStatus.value =
      await window.hinaDesktop.triggerVTubeStudioHotkey(hotkeyId);
    vtubeMessage.value = "Đã gửi hotkey tới model Live2D hiện tại.";
  } catch (error) {
    vtubeMessage.value = error instanceof Error
      ? error.message
      : "E_VTS_HOTKEY";
    await refreshVTubeStudioStatus();
  } finally {
    vtubeBusy.value = false;
  }
}

async function moveVTubeStudioModel(
  preset: "chat" | "screen" | "react",
): Promise<void> {
  if (vtubeBusy.value) return;
  vtubeBusy.value = true;
  try {
    vtubeStatus.value =
      await window.hinaDesktop.moveVTubeStudioModel(preset);
    vtubeMessage.value =
      `Đã chuyển model sang bố cục ${preset}; không thay đổi file model.`;
  } catch (error) {
    vtubeMessage.value = error instanceof Error
      ? error.message
      : "E_VTS_MOVE";
    await refreshVTubeStudioStatus();
  } finally {
    vtubeBusy.value = false;
  }
}

async function retryConnection(): Promise<void> {
  busy.value = true;
  try {
    resetControlBackoff();
    await Promise.all([refreshAvatar(), refreshSafety(), refreshWidget()]);
  } finally {
    busy.value = false;
  }
}

async function applyWidgetControl(
  action: "show" | "hide" | "reset_position",
): Promise<void> {
  busy.value = true;
  try {
    widgetStatus.value = await window.hinaDesktop.applyWidgetControl({ action });
    errorMessage.value = "";
  } catch (error) {
    errorMessage.value = error instanceof Error
      ? error.message
      : "E_DESKTOP_WIDGET_CONTROL";
  } finally {
    busy.value = false;
  }
}

async function preview(): Promise<void> {
  busy.value = true;
  try {
    avatar.value = await window.hinaDesktop.applyAvatarCue({
      source: "owner.console",
      state: previewState.value,
      mode: "manual-preview",
    });
    errorMessage.value = "";
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : "E_DESKTOP_AVATAR_CUE";
  } finally {
    busy.value = false;
  }
}

async function resetAvatar(): Promise<void> {
  busy.value = true;
  try {
    avatar.value = await window.hinaDesktop.resetAvatar();
    errorMessage.value = "";
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : "E_DESKTOP_AVATAR_RESET";
  } finally {
    busy.value = false;
  }
}

async function toggleMute(): Promise<void> {
  if (!safety.value) return;
  busy.value = true;
  try {
    await window.hinaDesktop.applySafetyControl({
      action: "set_mute",
      enabled: !safety.value.state.muted,
    });
    await refreshSafety();
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : "E_DESKTOP_SAFETY";
  } finally {
    busy.value = false;
  }
}

async function toggleEmergency(): Promise<void> {
  if (!safety.value) return;
  busy.value = true;
  try {
    await window.hinaDesktop.applySafetyControl({
      action: safety.value.state.emergencyStopped
        ? "emergency_reset"
        : "emergency_stop",
    });
    await refreshSafety();
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : "E_DESKTOP_SAFETY";
  } finally {
    busy.value = false;
  }
}

function handleVrmReady(details: {
  displayName: string;
  presentationId: string;
  source: "bundled-vrm-1.0";
  loadedTextureCount: number;
  styledMaterialCount: number;
}): void {
  vrmReady.value = true;
  vrmError.value = "";
  vrmDisplayName.value = details.displayName;
  vrmPresentationId.value = details.presentationId;
  vrmTextureCount.value = details.loadedTextureCount;
  vrmStyledMaterialCount.value = details.styledMaterialCount;
  document.documentElement.dataset.vrmReady = "true";
  document.documentElement.dataset.avatarPresentation = details.presentationId;
  document.documentElement.dataset.avatarTextureCount =
    String(details.loadedTextureCount);
  document.documentElement.dataset.avatarStyledMaterialCount =
    String(details.styledMaterialCount);
  delete document.documentElement.dataset.vrmError;
}

function clearVrmPerformance(): void {
  vrmPerformance.value = null;
  vrmFps.value = 0;
  for (const name of [
    "vrmFps",
    "vrmFrameP95",
    "vrmFrameP99",
    "vrmDroppedPercent",
    "vrmSampleCount",
  ]) {
    delete document.documentElement.dataset[name];
  }
}

function handleVrmFailure(message: string): void {
  vrmReady.value = false;
  vrmError.value = message.slice(0, 200);
  vrmPresentationId.value = "";
  vrmTextureCount.value = 0;
  vrmStyledMaterialCount.value = 0;
  clearVrmPerformance();
  document.documentElement.dataset.vrmError = vrmError.value;
  delete document.documentElement.dataset.vrmReady;
  delete document.documentElement.dataset.avatarPresentation;
  delete document.documentElement.dataset.avatarTextureCount;
  delete document.documentElement.dataset.avatarStyledMaterialCount;
}

function handleVrmPerformance(report: FrameMetricsReport): void {
  vrmPerformance.value = report;
  vrmFps.value = report.fps;
  document.documentElement.dataset.vrmFps = String(report.fps);
  document.documentElement.dataset.vrmFrameP95 = String(report.frameTimeP95Ms);
  document.documentElement.dataset.vrmFrameP99 = String(report.frameTimeP99Ms);
  document.documentElement.dataset.vrmDroppedPercent =
    String(report.droppedFramePercent);
  document.documentElement.dataset.vrmSampleCount = String(report.sampleCount);
}

function retryVrm(): void {
  vrmReady.value = false;
  vrmError.value = "";
  clearVrmPerformance();
  delete document.documentElement.dataset.vrmError;
  delete document.documentElement.dataset.vrmReady;
  delete document.documentElement.dataset.avatarPresentation;
  delete document.documentElement.dataset.avatarTextureCount;
  delete document.documentElement.dataset.avatarStyledMaterialCount;
  vrmStageKey.value += 1;
}

function stopPolling(): void {
  stopResourcePolling();
  if (avatarTimer !== null) {
    window.clearInterval(avatarTimer);
    avatarTimer = null;
  }
  if (safetyTimer !== null) {
    window.clearInterval(safetyTimer);
    safetyTimer = null;
  }
  if (widgetTimer !== null) {
    window.clearInterval(widgetTimer);
    widgetTimer = null;
  }
  if (spoutTimer !== null) {
    window.clearInterval(spoutTimer);
    spoutTimer = null;
  }
  if (chatPollTimer !== null) {
    window.clearTimeout(chatPollTimer);
    chatPollTimer = null;
  }
}

function cleanupDesktop(): void {
  stopPolling();
  cleanupSpeechTest();
  if (removeScreenCaptureProgressListener !== null) {
    removeScreenCaptureProgressListener();
    removeScreenCaptureProgressListener = null;
  }
}

watch(activePage, (page) => {
  if (page === "resources") {
    startResourcePolling();
  } else {
    stopResourcePolling();
  }
});

onMounted(async () => {
  windowMode.value = await window.hinaDesktop.getWindowMode();
  document.documentElement.dataset.windowMode = windowMode.value;
  if (windowMode.value !== "operator") return;
  removeScreenCaptureProgressListener = window.hinaDesktop.onScreenCaptureProgress(
    handleScreenCaptureProgress,
  );
  await Promise.all([
    refreshAvatar(),
    refreshSafety(),
    refreshWidget(),
    refreshSpeechRuntime(),
    refreshVisionProviderStatus(),
    refreshVTubeStudioStatus(),
    refreshSpoutStatus(),
  ]);
  avatarTimer = window.setInterval(refreshAvatar, 250);
  safetyTimer = window.setInterval(refreshSafety, 1_000);
  widgetTimer = window.setInterval(refreshWidget, 1_000);
  spoutTimer = window.setInterval(refreshSpoutStatus, 1_000);
  window.addEventListener("beforeunload", cleanupDesktop, { once: true });
});

onBeforeUnmount(() => {
  window.removeEventListener("beforeunload", cleanupDesktop);
  cleanupDesktop();
});
</script>

<template>
  <DesktopWidget v-if="windowMode === 'widget'" />
  <main v-else-if="windowMode === 'operator'" class="desktop-shell">
    <header class="desktop-header">
      <div class="brand">
        <div class="brand-mark">H</div>
        <div>
          <p class="eyebrow">M08 / LOCAL OPERATOR DESKTOP</p>
          <h1>Hina Avatar Stage</h1>
        </div>
      </div>
      <div class="runtime-pill" :data-online="connected">
        <span></span>
        {{ connected ? "Control plane đã kết nối" : "Control plane offline" }}
      </div>
    </header>

    <nav class="desktop-nav" aria-label="Điều hướng dashboard">
      <button type="button" :class="{ active: activePage === 'overview' }" @click="activePage = 'overview'">
        Tổng quan
        <small>Nhìn nhanh trạng thái Hina</small>
      </button>
      <button type="button" :class="{ active: activePage === 'chat' }" @click="activePage = 'chat'">
        Chat với Hina
        <small>Gửi text và nghe câu trả lời</small>
      </button>
      <button type="button" :class="{ active: activePage === 'speech' }" @click="activePage = 'speech'">
        Mic / STT / TTS
        <small>Kiểm tra thu âm và giọng thật</small>
      </button>
      <button type="button" :class="{ active: activePage === 'perception' }" @click="activePage = 'perception'">
        Quan sát
        <small>Chụp màn hình và chọn model</small>
      </button>
      <button type="button" :class="{ active: activePage === 'resources' }" @click="activePage = 'resources'">
        Tài nguyên AI
        <small>RAM, VRAM và model realtime</small>
      </button>
      <button type="button" :class="{ active: activePage === 'avatar' }" @click="activePage = 'avatar'">
        Avatar Stage
        <small>Xem biểu cảm và lip-sync</small>
      </button>
      <button type="button" :class="{ active: activePage === 'live2d' }" @click="activePage = 'live2d'">
        Live2D / VTube Studio
        <small>Hiyori hoặc model của bạn</small>
      </button>
      <button type="button" :class="{ active: activePage === 'runtime' }" @click="activePage = 'runtime'">
        Runtime & Safety
        <small>Widget, mute và dừng khẩn cấp</small>
      </button>
    </nav>

    <section v-if="errorMessage" class="error-banner" role="alert">
      <strong>Không đọc được dữ liệu thật.</strong>
      <span>{{ errorMessage }}</span>
      <small>
        <code>pnpm start:desktop</code> sẽ tự khởi control plane. Nếu runtime vừa
        khởi động lại, desktop sẽ chờ theo backoff thay vì gửi lỗi liên tục.
      </small>
      <button type="button" :disabled="busy" @click="retryConnection">
        Thử kết nối lại ngay
      </button>
    </section>

    <section v-if="activePage === 'overview'" class="dashboard-page overview-page">
      <div class="page-heading">
        <p class="eyebrow">DASHBOARD / TỔNG QUAN</p>
        <h2>Chào bạn, đây là bảng điều khiển Hina</h2>
        <p class="purpose">Các thẻ dưới đây cho biết Hina đang kết nối hay không, avatar đang làm gì và bạn có thể đi tới chức năng nào tiếp theo.</p>
      </div>
      <div class="overview-grid">
        <article class="overview-card">
          <span>Kết nối control plane</span>
          <strong :data-good="connected">{{ connected ? "Đang hoạt động" : "Chưa sẵn sàng" }}</strong>
          <p>{{ connected ? "Desktop đang đọc dữ liệu thật từ runtime local." : "Hãy chạy start:desktop; hệ thống sẽ tự khởi control plane." }}</p>
        </article>
        <article class="overview-card">
          <span>Trạng thái Hina</span>
          <strong>{{ stateLabels[stageState] }}</strong>
          <p>Biểu cảm {{ avatar?.expression ?? "chưa có" }} · viseme {{ stageViseme }}.</p>
        </article>
        <article class="overview-card">
          <span>Voice phản hồi</span>
          <strong>{{ safety?.state.muted ? "Đang tắt" : "Đang bật" }}</strong>
          <p>Vào Chat với Hina để gửi câu hỏi. Khi bật voice, câu trả lời sẽ phát thành WAV thật.</p>
        </article>
        <article class="overview-card">
          <span>Avatar Live2D bên ngoài</span>
          <strong :data-good="vtubeStatus?.authenticated">
            {{ vtubeStatus?.authenticated ? "VTube Studio đã nối" : "Chưa kết nối" }}
          </strong>
          <p>
            {{ vtubeStatus?.model.loaded
              ? `Model: ${vtubeStatus.model.name || vtubeStatus.model.vtsModelName}`
              : "VRM local vẫn là fallback; vào trang Live2D để thiết lập." }}
          </p>
        </article>
      </div>
      <div class="quick-actions">
        <button class="primary" type="button" @click="activePage = 'chat'">Mở chat với Hina</button>
        <button type="button" @click="activePage = 'speech'">Kiểm tra Mic / STT / TTS</button>
        <button type="button" @click="activePage = 'perception'">Thiết lập đọc màn hình</button>
        <button type="button" @click="activePage = 'resources'">Theo dõi RAM / VRAM</button>
        <button type="button" @click="activePage = 'avatar'">Xem avatar</button>
        <button type="button" @click="activePage = 'live2d'">Thiết lập Live2D / Hiyori</button>
        <button type="button" @click="activePage = 'runtime'">Quản lý widget và Safety</button>
      </div>
    </section>

    <section v-else-if="activePage === 'chat'" class="dashboard-page chat-page">
      <div class="page-heading">
        <p class="eyebrow">DASHBOARD / CHAT</p>
        <h2>Nói chuyện với Hina bằng text và voice</h2>
          <p class="purpose">Nhập câu hỏi bằng tiếng Việt. Hina trả về nội dung text trước, sau đó phát cùng nội dung bằng OmniVoice local chạy GPU và dùng mẫu giọng Hina cố định nếu Voice đang bật.</p>
      </div>
      <div class="chat-layout">
        <div class="chat-messages" aria-live="polite">
          <p v-if="chatMessages.length === 0" class="chat-empty">Chưa có tin nhắn. Hãy bắt đầu bằng một câu chào.</p>
          <div v-for="(message, index) in chatMessages" :key="`${index}-${message.role}`" class="chat-message" :data-role="message.role">
            <span>{{ message.role === 'user' ? 'Bạn' : message.role === 'assistant' ? 'Hina' : 'Hệ thống' }}</span>
            <p>{{ message.text }}</p>
          </div>
          <div
            v-if="chatBusy"
            class="chat-thinking"
            role="status"
            aria-live="polite"
            data-testid="chat-thinking"
          >
            <span>Hina đang {{ chatTurnState === "speaking" ? "chuẩn bị nói" : "suy nghĩ" }}…</span>
            <i aria-hidden="true"></i><i aria-hidden="true"></i><i aria-hidden="true"></i>
          </div>
        </div>
        <form class="chat-composer" @submit.prevent="sendDesktopChat">
          <label for="desktopChatInput">Bạn muốn nói gì với Hina?</label>
          <textarea id="desktopChatInput" v-model="chatInput" rows="4" maxlength="16384" :disabled="chatBusy" placeholder="Ví dụ: Hina, hôm nay bạn thấy thế nào?"></textarea>
          <div class="chat-options">
            <label class="voice-toggle">
              <input v-model="chatVoiceEnabled" type="checkbox">
              <span>Phát voice trả lời</span>
            </label>
            <span class="chat-hint">Voice vẫn tuân theo nút mute Safety.</span>
          </div>
          <div class="button-row">
            <button class="primary" type="submit" :disabled="chatBusy || !chatInput.trim()">Gửi cho Hina</button>
            <button type="button" :disabled="!chatBusy" @click="cancelDesktopChat">Dừng lượt trả lời</button>
            <button type="button" :disabled="busy || !safety" @click="toggleMute">{{ safety?.state.muted ? "Bật voice toàn hệ thống" : "Tắt voice toàn hệ thống" }}</button>
          </div>
          <p v-if="chatError" class="inline-error">{{ chatError }}</p>
        </form>
      </div>
    </section>

    <section v-else-if="activePage === 'speech'" class="dashboard-page speech-page">
      <div class="page-heading">
        <p class="eyebrow">DASHBOARD / MIC · STT · TTS</p>
        <h2>Kiểm tra từng phần của hội thoại bằng giọng nói</h2>
        <p class="purpose">
          Trang này dùng dịch vụ thật, không dùng dữ liệu giả. Phần Mic → STT thu âm trực tiếp
              và cập nhật transcript khi bạn còn đang nói. Phần TTS gửi đoạn text cho OmniVoice chạy GPU, chia câu dài thành các đoạn ổn định rồi phát lại WAV 24 kHz bằng giọng Hina.
        </p>
      </div>
      <div class="speech-runtime-strip" role="status">
        <strong>Backend đang chạy</strong>
        <span v-if="speechRuntime">
          {{ speechRuntime.configured.provider }} · {{ speechRuntime.configured.model }} ·
          {{ speechRuntime.provider.effectiveDevice.toUpperCase() }} /
          {{ speechRuntime.configured.computeType }}
        </span>
        <span v-else>Chưa đọc được trạng thái STT.</span>
        <span v-if="ttsRuntime">
          · TTS {{ ttsRuntime.provider.effectiveDevice.toUpperCase() }} /
          {{ ttsRuntime.provider.effectivePrecision }}
        </span>
        <button type="button" @click="refreshSpeechRuntime">Làm mới</button>
      </div>
      <div class="speech-test-grid">
        <article class="speech-test-card">
          <p class="eyebrow">MIC → LOCAL STT REALTIME</p>
          <h3>Hina nghe bạn nói</h3>
          <p>
            Dùng khi cần kiểm tra quyền microphone và độ chính xác nhận dạng tiếng Việt/tiếng Anh.
            Tên model cùng thiết bị GPU/CPU thật luôn hiện phía trên; audio chỉ nằm trong bộ nhớ của lượt hiện tại.
          </p>
          <label class="speech-live-toggle">
            <input v-model="speechLiveEnabled" type="checkbox" :disabled="speechRecording">
            Cập nhật transcript realtime khi đang nói
          </label>
          <div class="button-row">
            <button
              v-if="!speechRecording"
              id="speechStartMic"
              class="primary"
              type="button"
              :disabled="speechBusy"
              @click="startSpeechTest"
            >
              Thu mic
            </button>
            <button
              v-else
              id="speechStopMic"
              class="recording"
              type="button"
              @click="stopSpeechTest"
            >
              Dừng &amp; chốt transcript
            </button>
          </div>
          <div class="speech-result" aria-live="polite">
            <span>Kết quả transcript</span>
            <strong>{{ speechTranscript || "Chưa có transcript." }}</strong>
            <small v-if="speechCorrelationId">
              Correlation ID: <code>{{ speechCorrelationId }}</code>
            </small>
          </div>
        </article>

        <article class="speech-test-card">
          <p class="eyebrow">TEXT → VIENEU VIETNAMESE GPU</p>
          <h3>Nghe thử giọng Hina</h3>
          <p>
            Dùng khi cần kiểm tra giọng và cảm xúc. Câu dài được tách theo dấu câu
            để giữ nhịp tự nhiên; hệ thống không ép tăng tốc làm mất chữ.
          </p>
          <label for="speechTtsText">Nội dung Hina sẽ nói</label>
          <textarea
            id="speechTtsText"
            v-model="speechTtsText"
            rows="5"
            maxlength="4000"
            :disabled="speechBusy || speechRecording"
          ></textarea>
          <button
            id="speechTestTts"
            class="primary"
            type="button"
            :disabled="speechBusy || speechRecording || !speechTtsText.trim()"
            @click="testTtsVoice"
          >
            Tạo &amp; phát giọng Hina
          </button>
          <audio
            v-if="speechTtsAudioUrl"
            class="speech-audio"
            :src="speechTtsAudioUrl"
            controls
          ></audio>
        </article>
      </div>
      <div class="speech-status" :data-recording="speechRecording" role="status">
        <strong>{{ speechRecording ? "● Đang nghe" : speechBusy ? "Đang xử lý" : "Trạng thái" }}</strong>
        <span>{{ speechStatus }}</span>
      </div>
      <aside class="speech-help">
        <strong>Nếu không nghe/không nhận được giọng:</strong>
        kiểm tra Windows đã cấp quyền microphone cho ứng dụng desktop, chọn đúng mic mặc định,
        nói gần mic rồi xem correlation ID hoặc dòng <code>[hina-error]</code> trong cửa sổ
        <code>pnpm start:desktop</code>.
      </aside>
    </section>

    <section v-else-if="activePage === 'perception'" class="dashboard-page perception-page">
      <div class="page-heading">
        <p class="eyebrow">M08 / SCREEN PERCEPTION</p>
        <h2>Cho Hina đọc toàn bộ màn hình hoặc cửa sổ bạn chọn</h2>
        <p class="purpose">
          Mỗi lần bạn bấm gửi, Electron chụp đúng một khung hình đầy đủ của nguồn đã
          chọn rồi giảm cạnh dài xuống 640, 960 hoặc 1280 px. Mặc định 960 px giúp
          giảm dung lượng, thời gian xử lý và lượng token hình ảnh mà vẫn đủ rõ cho
          phần lớn game/UI. Không có ảnh nào được chụp tự động.
        </p>
      </div>

      <section class="screen-capture-panel" aria-labelledby="screenCaptureTitle">
        <div class="screen-capture-heading">
          <div>
            <p class="eyebrow">1 / CHỤP THẬT MỘT LẦN</p>
            <h3 id="screenCaptureTitle">Chọn nguồn và gửi toàn bộ khung hình</h3>
          </div>
          <span
            class="capture-permission-badge"
            :data-enabled="String(perceptionFeatureEnabled)"
          >
            {{ perceptionFeatureEnabled ? "Quyền quan sát đang bật" : "Quyền quan sát đang tắt" }}
          </span>
        </div>

        <div class="capture-safety-row">
          <p>
            Nút quyền chỉ mở/đóng cổng Safety. Dù đang bật, Hina vẫn không thể tự
            chụp; source grant chỉ sống 60 giây, dùng đúng một lần và không được lưu.
          </p>
          <button
            type="button"
            :class="{ danger: perceptionFeatureEnabled }"
            :disabled="screenCaptureBusy || !safety"
            @click="togglePerceptionFeature"
          >
            {{ perceptionFeatureEnabled ? "Tắt quyền quan sát" : "Bật quyền quan sát" }}
          </button>
          <button
            class="primary"
            type="button"
            :disabled="screenCaptureBusy || !perceptionFeatureEnabled"
            @click="listScreenCaptureSources"
          >
            {{ screenCaptureBusy ? "Đang xử lý…" : "Đọc màn hình / cửa sổ hiện có" }}
          </button>
        </div>

        <div v-if="screenCaptureListing" class="capture-source-gallery" role="list">
          <button
            v-for="source in screenCaptureListing.sources"
            :key="source.sourceToken"
            type="button"
            class="capture-source-card"
            :class="{ selected: source.sourceToken === screenCaptureSourceToken }"
            :aria-pressed="source.sourceToken === screenCaptureSourceToken"
            @click="screenCaptureSourceToken = source.sourceToken"
          >
            <img :src="source.previewDataUrl" alt="">
            <span>
              <strong>{{ source.name }}</strong>
              <small>
                {{ source.kind === "screen" ? "Toàn màn hình" : "Toàn cửa sổ" }}
                · preview {{ source.previewWidth }}×{{ source.previewHeight }}
              </small>
            </span>
          </button>
        </div>
        <div v-else class="capture-empty-state">
          Bấm “Đọc màn hình / cửa sổ hiện có” để tạo danh sách xem trước tạm thời.
        </div>

        <div class="capture-config-grid">
          <div class="capture-selected-preview">
            <template v-if="selectedScreenCaptureSource">
              <img :src="selectedScreenCaptureSource.previewDataUrl" alt="Xem trước nguồn đã chọn">
              <strong>{{ selectedScreenCaptureSource.name }}</strong>
              <p>
                Hina nhận toàn bộ nội dung đang nằm trong khung này; không crop và
                không che phần nào.
              </p>
            </template>
            <p v-else>Chưa chọn nguồn để chụp.</p>
          </div>

          <div class="capture-options">
            <label for="screenCaptureResolution">Độ phân giải gửi cho AI</label>
            <select
              id="screenCaptureResolution"
              v-model.number="screenCaptureMaxSide"
              :disabled="screenCaptureBusy"
            >
              <option :value="640">640 px — tiết kiệm token, chữ lớn/game đơn giản</option>
              <option :value="960">960 px — cân bằng, khuyên dùng</option>
              <option :value="1280">1280 px — chi tiết hơn, tốn xử lý hơn</option>
            </select>

            <label for="screenCaptureLabel">Tên gợi nhớ cho lượt này (không bắt buộc)</label>
            <input
              id="screenCaptureLabel"
              v-model="screenCaptureLabel"
              type="text"
              maxlength="120"
              autocomplete="off"
              placeholder="Ví dụ: Minecraft — màn hình chính"
            >

            <label class="capture-checkbox">
              <input v-model="screenCaptureAnalyzeOcr" type="checkbox">
              <span>
                <strong>Đọc chữ bằng OCR GPU</strong>
                <small>Nhanh với menu/HUD; kết quả vẫn cần đối chiếu nếu chữ nhỏ.</small>
              </span>
            </label>
            <label class="capture-checkbox">
              <input
                v-model="screenCaptureAnalyzeVision"
                type="checkbox"
                :disabled="!visionProviderStatus?.runtime.available"
                @change="markScreenCaptureVisionPreference"
              >
              <span>
                <strong>Phân tích bằng model vision đang chọn</strong>
                <small>
                  {{
                    visionProviderStatus?.runtime.available
                      ? "Dùng provider bên dưới cho đúng ảnh này."
                      : "Hãy cấu hình model vision ở phần dưới trước."
                  }}
                </small>
              </span>
            </label>

            <template v-if="screenCaptureAnalyzeVision">
              <label for="screenCaptureQuestion">Hina cần chú ý điều gì? (không bắt buộc)</label>
              <textarea
                id="screenCaptureQuestion"
                v-model="screenCaptureVisionQuestion"
                maxlength="500"
                rows="3"
                placeholder="Ví dụ: Mô tả tình huống game và nguy hiểm gần nhân vật."
              ></textarea>
            </template>

            <button
              id="captureFullFrameButton"
              class="primary capture-submit"
              type="button"
              :disabled="
                screenCaptureBusy
                  || !perceptionFeatureEnabled
                  || !screenCaptureListing
                  || !selectedScreenCaptureSource
              "
              @click="captureSelectedScreenSource"
            >
              Chụp toàn bộ nguồn đã chọn và gửi Hina
            </button>
          </div>
        </div>

        <div class="capture-message" role="status">
          {{ screenCaptureMessage || "Mặc định 960 px; ảnh thường không được lưu sau lượt đọc." }}
        </div>
        <div v-if="screenCaptureResult" class="capture-result">
          <strong>
            {{
              screenCaptureResult.status === "duplicate"
                ? "Đã dùng lại quan sát còn hạn"
                : screenCaptureResult.observation?.vision?.state === "ready"
                  ? "Hina đã nhìn và phân tích ảnh"
                  : screenCaptureResult.observation?.ocr?.state === "ready"
                    ? "Hina đã nhận ảnh và OCR đã đọc chữ"
                    : "Hina đã nhận ảnh nhưng chưa phân tích thành công"
            }}
          </strong>
          <span>
            {{ screenCaptureResult.desktopCapture.width }}×{{ screenCaptureResult.desktopCapture.height }}
            · {{ Math.ceil(screenCaptureResult.desktopCapture.bytes / 1024) }} KB
            · full frame · correlation {{ screenCaptureResult.correlationId }}
          </span>
          <p v-if="screenCaptureResult.observation?.vision?.summary">
            <b>Model vision:</b> {{ screenCaptureResult.observation.vision.summary }}
          </p>
          <p
            v-else-if="
              screenCaptureResult.observation?.vision?.requested
                && screenCaptureResult.observation.vision.state !== 'ready'
            "
            class="capture-analysis-error"
          >
            <b>Model vision chưa trả được kết quả:</b>
            {{ visionAnalysisErrorCode(screenCaptureResult.observation.vision) }}.
            Hãy xem trạng thái provider bên dưới hoặc thử lại; correlation ID ở
            dòng trên dùng để tìm đúng lỗi trong console.
          </p>
          <p v-else class="capture-analysis-not-requested">
            <b>Model vision:</b> chưa được yêu cầu trong lượt này. Bật
            “Phân tích bằng model vision đang chọn” trước khi chụp để Hina mô tả ảnh.
          </p>
          <p v-if="screenCaptureResult.observation?.ocr?.text">
            <b>OCR:</b> {{ screenCaptureResult.observation.ocr.text }}
          </p>
          <p
            v-else-if="
              screenCaptureResult.observation?.ocr?.requested
                && screenCaptureResult.observation.ocr.state !== 'ready'
            "
            class="capture-analysis-error"
          >
            <b>OCR chưa trả được kết quả:</b>
            {{ screenCaptureResult.observation.ocr.errorCode || "E_PERCEPTION_OCR" }}.
          </p>
          <div
            v-if="
              screenCaptureResult.observation?.vision?.state === 'ready'
                || screenCaptureResult.observation?.ocr?.state === 'ready'
            "
            class="button-row"
          >
            <button
              class="primary"
              type="button"
              :disabled="chatBusy"
              @click="askHinaAboutLastCapture"
            >
              Hỏi Hina ngay về ảnh vừa chụp
            </button>
            <small>
              Nên bấm ngay: mô tả ảnh chỉ đi vào đúng phiên Chat này trong tối đa 15 giây,
              rồi tự hết hạn.
            </small>
          </div>
        </div>
      </section>

      <div class="vision-status-grid">
        <article class="vision-status-card">
          <span>Provider đang lưu</span>
          <strong>{{ visionProviderStatus?.persistence.provider ?? "Chưa đọc được" }}</strong>
          <p>{{ visionProviderStatus?.persistence.model || "Chưa chọn model" }}</p>
        </article>
        <article class="vision-status-card">
          <span>API key</span>
          <strong>
            {{ visionProviderStatus?.persistence.apiKeyConfigured ? "Đã lưu mã hóa" : "Chưa lưu" }}
          </strong>
          <p>Renderer không thể đọc ngược key đã lưu.</p>
        </article>
        <article class="vision-status-card">
          <span>Runtime</span>
          <strong>
            {{ visionProviderStatus?.runtime.available ? "Sẵn sàng" : "Chưa cấu hình" }}
          </strong>
          <p>{{ visionProviderStatus?.runtime.lastErrorCode || "Không có lỗi provider." }}</p>
        </article>
      </div>

      <div class="vision-settings-grid">
        <article class="vision-settings-card">
          <p class="eyebrow">2 / CHỌN NGUỒN MODEL</p>
          <h3>Provider đọc ảnh</h3>
          <label for="visionProvider">Nguồn xử lý ảnh</label>
          <select id="visionProvider" v-model="visionProvider" :disabled="visionBusy">
            <option value="ollama_cloud">Ollama Cloud — không dùng VRAM máy</option>
            <option value="ollama_local">Ollama local — riêng tư, dùng GPU máy</option>
          </select>

          <template v-if="visionProvider === 'ollama_cloud'">
            <div
              class="vision-key-state"
              :data-configured="String(visionProviderStatus?.persistence.apiKeyConfigured === true)"
            >
              <strong>
                {{
                  visionProviderStatus?.persistence.apiKeyConfigured
                    ? "API key đã được lưu"
                    : "Chưa có API key được lưu"
                }}
              </strong>
              <span>
                {{
                  visionProviderStatus?.persistence.apiKeyConfigured
                    ? `Windows đã mã hóa key; Hina sẽ tự dùng lại với model ${visionProviderStatus.persistence.model || "đã lưu"}.`
                    : "Nhập key một lần để Hina mã hóa và tự khôi phục ở những lần mở sau."
                }}
              </span>
            </div>
            <label for="visionApiKey">
              {{
                visionProviderStatus?.persistence.apiKeyConfigured
                  ? "API key mới (không bắt buộc)"
                  : "Ollama Cloud API key"
              }}
            </label>
            <input
              id="visionApiKey"
              v-model="visionApiKey"
              type="password"
              autocomplete="off"
              maxlength="4096"
              :disabled="visionBusy"
              :placeholder="visionProviderStatus?.persistence.apiKeyConfigured
                ? 'Để trống để tiếp tục dùng key đã mã hóa'
                : 'Dán API key Ollama Cloud'"
            >
            <p class="vision-help">
              {{
                visionProviderStatus?.persistence.apiKeyConfigured
                  ? "Để trống để tiếp tục dùng key hiện tại. Dán key khác rồi bấm nút ghi đè để thay key mà không cần đọc lại danh sách hoặc chọn lại model."
                  : "Khi bấm lưu, Electron mã hóa key bằng safeStorage của Windows trong thư mục ứng dụng."
              }}
              Key không vào Git, log, bộ nhớ web hay response trả về renderer.
            </p>
          </template>
          <p v-else class="vision-help">
            Hina quét Ollama tại <code>127.0.0.1:11434</code>, dùng
            <code>/api/show</code> để xác nhận capability <code>vision</code> và
            chỉ nhận model tối đa khoảng 4B/5 GB.
          </p>

          <button
            class="primary"
            type="button"
            :disabled="visionBusy"
            @click="discoverVisionModels"
          >
            {{ visionBusy ? "Đang kiểm tra…" : "Đọc danh sách model vision" }}
          </button>
        </article>

        <article class="vision-settings-card">
          <p class="eyebrow">3 / CHỌN MODEL</p>
          <h3>Model Hina sẽ dùng để nhìn</h3>
          <label for="visionModel">Model có capability vision</label>
          <select
            id="visionModel"
            v-model="visionModel"
            :disabled="visionBusy || selectableVisionModels.length === 0"
          >
            <option v-if="selectableVisionModels.length === 0" value="">
              Hãy đọc danh sách model trước
            </option>
            <option
              v-for="model in selectableVisionModels"
              :key="model.name"
              :value="model.name"
            >
              {{ model.name }} · {{ model.parameterSize || "Cloud" }} ·
              {{ formatVisionModelSize(model.sizeBytes) }}
            </option>
          </select>

          <div v-if="visionModel" class="vision-model-detail">
            <template v-for="model in selectableVisionModels" :key="`detail-${model.name}`">
              <div v-if="model.name === visionModel">
                <span>Tham số</span><strong>{{ model.parameterSize || "Cloud" }}</strong>
                <span>Dung lượng</span><strong>{{ formatVisionModelSize(model.sizeBytes) }}</strong>
                <span>VRAM máy</span><strong>{{ model.localGpuUsed ? "Có" : "Không" }}</strong>
                <span>Capability</span><strong>{{ model.capabilities.join(", ") }}</strong>
              </div>
            </template>
          </div>

          <div class="button-row">
            <button
              class="primary"
              type="button"
              :disabled="visionBusy || !visionModel"
              @click="applyVisionProvider"
            >
              {{ visionConfigurationActionLabel }}
            </button>
            <button
              type="button"
              :disabled="visionBusy || !visionProviderStatus?.persistence.apiKeyConfigured"
              @click="clearVisionProviderKey"
            >
              Xóa API key đã lưu
            </button>
            <button type="button" :disabled="visionBusy" @click="refreshVisionProviderStatus">
              Làm mới trạng thái
            </button>
          </div>
        </article>
      </div>

      <div class="vision-message" role="status">
        <strong>Trạng thái cấu hình</strong>
        <span>{{ visionMessage || "Hãy chọn provider, đọc danh sách model rồi bấm Áp dụng." }}</span>
      </div>

      <aside class="vision-privacy-note">
        <strong>Khi nào nên chọn gì?</strong>
        Chọn Cloud nếu cần chất lượng đọc ảnh tốt mà không tăng VRAM; ảnh được gửi
        tới Ollama Cloud ở đúng lượt bạn yêu cầu. Chọn local nếu ảnh không được rời
        máy; đổi lại model vision sẽ dùng GPU và được scheduler unload sau lượt đọc.
        OCR local vẫn là lớp riêng và kết quả ảnh luôn bị coi là dữ liệu không đáng
        tin, không tự điều khiển game.
      </aside>
    </section>

    <section v-else-if="activePage === 'resources'" class="dashboard-page resources-page">
      <div class="resource-heading-row">
        <div class="page-heading">
          <p class="eyebrow">M08 / REALTIME RESOURCE OBSERVABILITY</p>
          <h2>Tài nguyên AI: RAM, VRAM và model đang hoạt động</h2>
          <p class="purpose">
            Trang này đo tài nguyên thật trên máy và cập nhật mỗi 1,5 giây khi
            bạn đang mở nó. Dùng trang này để biết model nào đang nằm trong bộ
            nhớ, model nào đã được giải phóng và Hina còn đủ chỗ chạy tác vụ mới hay không.
          </p>
        </div>
        <button type="button" :disabled="resourcePending" @click="refreshResources">
          {{ resourcePending ? "Đang đo…" : "Đo lại ngay" }}
        </button>
      </div>

      <div
        class="resource-analysis"
        :data-level="resourceAnalysis.level"
        role="status"
      >
        <div class="resource-analysis-icon" aria-hidden="true"></div>
        <div>
          <span>Phân tích tự động</span>
          <strong>{{ resourceAnalysis.title }}</strong>
          <p>{{ resourceAnalysis.message }}</p>
        </div>
        <small v-if="resourceStatus">
          Cập nhật {{ formatResourceTime(resourceStatus.sampledAtUnixMilliseconds) }}
        </small>
      </div>

      <div v-if="resourceError" class="resource-inline-error" role="alert">
        <strong>Không thể cập nhật tài nguyên:</strong>
        <span>{{ resourceError }}</span>
      </div>

      <template v-if="resourceStatus">
        <div class="resource-summary-grid">
          <article class="resource-summary-card resource-vram-card">
            <div class="resource-card-heading">
              <span>VRAM GPU vật lý</span>
              <strong>{{ formatMiB(resourceTelemetry?.usedVramMiB) }}</strong>
            </div>
            <div class="resource-meter" aria-label="Tỷ lệ VRAM đang dùng">
              <span :style="{ width: `${resourceVramPercent}%` }"></span>
            </div>
            <p>
              Tổng {{ formatMiB(resourceTelemetry?.totalVramMiB) }} · còn
              {{ formatMiB(resourceTelemetry?.freeVramMiB) }}.
            </p>
            <small>
              Hina có trần admission
              {{ formatMiB(resourceStatus.limits.allOnVramCeilingMiB) }}. VRAM trống NVIDIA
              đã bao gồm Windows/app khác, nên không bị trừ thêm dự phòng cố định.
            </small>
          </article>

          <article class="resource-summary-card">
            <div class="resource-card-heading">
              <span>RAM toàn hệ thống</span>
              <strong>{{ formatMiB(resourceTelemetry?.usedRamMiB) }}</strong>
            </div>
            <div class="resource-meter ram" aria-label="Tỷ lệ RAM đang dùng">
              <span :style="{ width: `${resourceRamPercent}%` }"></span>
            </div>
            <p>
              Tổng {{ formatMiB(resourceTelemetry?.totalRamMiB) }} · còn
              {{ formatMiB(resourceTelemetry?.freeRamMiB) }}.
            </p>
            <small>Đây là RAM của cả Windows, game và Hina cộng lại.</small>
          </article>

          <article class="resource-summary-card">
            <div class="resource-card-heading">
              <span>GPU đang làm việc</span>
              <strong>
                {{ formatMetric(resourceTelemetry?.gpuUtilizationPercent, "%") }}
              </strong>
            </div>
            <div class="resource-metric-pairs">
              <div>
                <span>Nhiệt độ</span>
                <strong>{{ formatMetric(resourceTelemetry?.temperatureCelsius, "°C") }}</strong>
              </div>
              <div>
                <span>Công suất</span>
                <strong>{{ formatMetric(resourceTelemetry?.powerDrawWatts, " W") }}</strong>
              </div>
            </div>
            <small>“Không hỗ trợ” nghĩa là driver không cung cấp số đó, không phải bằng 0.</small>
          </article>

          <article class="resource-summary-card">
            <div class="resource-card-heading">
              <span>Tiến trình Hina</span>
              <strong>
                {{ formatMiB(resourceStatus.processes.coreRuntime.rssMiB) }}
              </strong>
            </div>
            <div class="resource-metric-pairs">
              <div>
                <span>Core + AI worker</span>
                <strong>{{ formatMiB(resourceStatus.processes.coreRuntime.rssMiB) }}</strong>
              </div>
              <div>
                <span>Desktop</span>
                <strong>{{ formatMiB(resourceStatus.processes.desktopMain.rssMiB) }}</strong>
              </div>
            </div>
            <small>RSS là phần RAM vật lý tiến trình đang giữ tại thời điểm đo.</small>
          </article>
        </div>

        <div class="resource-chart-grid">
          <article class="resource-chart-card">
            <div>
              <span>Xu hướng VRAM</span>
              <strong>{{ formatMiB(resourceTelemetry?.usedVramMiB) }}</strong>
            </div>
            <svg viewBox="0 0 300 80" role="img" aria-label="Biểu đồ VRAM realtime">
              <path d="M0 72H300" />
              <polyline :points="resourceSparklinePoints('usedVramMiB')" />
            </svg>
            <small>{{ resourceSamples.length }}/60 mẫu gần nhất</small>
          </article>
          <article class="resource-chart-card">
            <div>
              <span>Xu hướng RAM</span>
              <strong>{{ formatMiB(resourceTelemetry?.usedRamMiB) }}</strong>
            </div>
            <svg viewBox="0 0 300 80" role="img" aria-label="Biểu đồ RAM realtime">
              <path d="M0 72H300" />
              <polyline :points="resourceSparklinePoints('usedRamMiB')" />
            </svg>
            <small>{{ resourceSamples.length }}/60 mẫu gần nhất</small>
          </article>
          <article class="resource-chart-card">
            <div>
              <span>Mức tải GPU</span>
              <strong>{{ formatMetric(resourceTelemetry?.gpuUtilizationPercent, "%") }}</strong>
            </div>
            <svg viewBox="0 0 300 80" role="img" aria-label="Biểu đồ tải GPU realtime">
              <path d="M0 72H300" />
              <polyline :points="resourceSparklinePoints('gpuUtilizationPercent')" />
            </svg>
            <small>{{ resourceSamples.length }}/60 mẫu gần nhất</small>
          </article>
        </div>

        <article class="resource-panel">
          <div class="resource-panel-heading">
            <div>
              <p class="eyebrow">MODEL RESIDENCY</p>
              <h3>Model đã load, đã unload hoặc đang ở Cloud</h3>
            </div>
            <div class="resource-counts">
              <span>{{ resourceLoadedCount }} local đang load</span>
              <span>{{ resourceCloudCount }} cloud sẵn sàng</span>
            </div>
          </div>
          <p class="resource-help">
            “Đã load” nghĩa là trọng số model đang nằm trong RAM/VRAM. “Đã
            unload” nghĩa là model vẫn được cấu hình nhưng đã nhả bộ nhớ và sẽ
            load lại khi cần. Cloud không lấy VRAM cho trọng số model trên máy này.
          </p>
          <p v-if="resourceControlMessage" class="resource-control-message" role="status">
            {{ resourceControlMessage }}
          </p>
          <div class="resource-table-wrap">
            <table class="resource-table">
              <thead>
                <tr>
                  <th>Chức năng</th>
                  <th>Model / provider</th>
                  <th>Nơi chạy</th>
                  <th>Trạng thái</th>
                  <th>Ngân sách VRAM</th>
                  <th>VRAM model đo được</th>
                  <th>Owner control</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="model in resourceStatus.models" :key="model.id">
                  <td>
                    <strong>{{ model.role }}</strong>
                    <small>{{ model.id }}</small>
                  </td>
                  <td>
                    <strong>{{ model.name || "Chưa chọn model" }}</strong>
                    <small>{{ model.provider || "Chưa có provider" }}</small>
                  </td>
                  <td>{{ model.location === "cloud" ? "Ollama Cloud" : "Máy local" }}</td>
                  <td>
                    <span class="model-state" :data-state="model.state">
                      {{ resourceStateLabel(model.state) }}
                    </span>
                    <small v-if="model.active">Scheduler đang cấp lease</small>
                    <small v-else-if="model.errorCode">{{ model.errorCode }}</small>
                  </td>
                  <td>{{ formatMiB(model.configuredVramMiB) }}</td>
                  <td>{{ formatMiB(model.measuredVramMiB) }}</td>
                  <td class="resource-model-actions">
                    <button
                      type="button"
                      class="compact"
                      :disabled="
                        resourceControlBusyId !== null
                        || !model.controlSupported
                        || model.location === 'cloud'
                        || !model.available
                        || model.state === 'loaded'
                        || model.state === 'loading'
                      "
                      :title="
                        model.controlSupported
                          ? 'Giữ model trên GPU bằng scheduler; nếu thiếu headroom thao tác sẽ bị từ chối an toàn.'
                          : model.controlNote
                      "
                      @click="controlResourceModel(model, 'load')"
                    >
                      {{ resourceControlBusyId === model.id ? "Đang xử lý…" : "Force load" }}
                    </button>
                    <button
                      type="button"
                      class="compact danger"
                      :disabled="
                        resourceControlBusyId !== null
                        || !model.controlSupported
                        || model.location === 'cloud'
                        || (model.state !== 'loaded' && model.state !== 'loading')
                      "
                      :title="
                        model.controlSupported
                          ? 'Trả model về scheduler sau khi tác vụ đang chạy kết thúc.'
                          : model.controlNote
                      "
                      @click="controlResourceModel(model, 'unload')"
                    >
                      Force unload
                    </button>
                    <small>{{ model.controlNote }}</small>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </article>

        <div class="resource-detail-grid">
          <article class="resource-panel">
            <div class="resource-panel-heading">
              <div>
                <p class="eyebrow">SCHEDULER LEASES</p>
                <h3>Quyền dùng tài nguyên đang giữ</h3>
              </div>
              <span>{{ resourceStatus.physical.activeLeases }} lease</span>
            </div>
            <p class="resource-help">
              Lease là “vé giữ chỗ” để tránh nhiều model chiếm GPU cùng lúc.
              Số reservation không được cộng thêm vào VRAM vật lý vì nó chỉ là ngân sách.
            </p>
            <div v-if="resourceStatus.physical.leases.length" class="resource-lease-list">
              <div
                v-for="lease in resourceStatus.physical.leases"
                :key="`${lease.owner}-${lease.priority}`"
              >
                <div>
                  <strong>{{ lease.owner }}</strong>
                  <small>
                    Ưu tiên {{ lease.priority }} ·
                    {{ lease.preemptible ? "có thể nhường" : "không tự nhường" }}
                  </small>
                </div>
                <span>{{ formatMiB(lease.reservedVramMiB) }} VRAM</span>
                <span>{{ formatMiB(lease.reservedRamMiB) }} RAM</span>
                <span>còn {{ Math.ceil(lease.remainingTtlSeconds) }} giây</span>
              </div>
            </div>
            <div v-else class="resource-empty">
              Không có model nào đang giữ lease. Đây là trạng thái bình thường khi Hina đang nghỉ.
            </div>
            <small v-if="resourceLargestLease" class="resource-footnote">
              Lease lớn nhất hiện tại: {{ resourceLargestLease.owner }} ·
              {{ formatMiB(resourceLargestLease.reservedVramMiB) }} VRAM.
            </small>
          </article>

          <article class="resource-panel">
            <div class="resource-panel-heading">
              <div>
                <p class="eyebrow">LOAD / UNLOAD TIMELINE</p>
                <h3>Thay đổi từ lúc mở desktop</h3>
              </div>
              <span>{{ resourceStatus.transitionHistory.count }}/{{ resourceStatus.transitionHistory.limit }}</span>
            </div>
            <p class="resource-help">
              Lịch sử này chỉ nằm trong RAM của desktop, không ghi file và sẽ
              mất khi đóng ứng dụng.
            </p>
            <ol v-if="resourceStatus.modelTransitions.length" class="resource-timeline">
              <li
                v-for="transition in resourceStatus.modelTransitions.slice().reverse().slice(0, 8)"
                :key="transition.sequence"
              >
                <time>{{ formatResourceTime(transition.occurredAtUnixMilliseconds) }}</time>
                <div>
                  <strong>{{ transition.role }}</strong>
                  <span>{{ resourceTransitionLabel(transition) }}</span>
                </div>
              </li>
            </ol>
            <div v-else class="resource-empty">Chưa ghi nhận thay đổi model.</div>
          </article>
        </div>

        <aside class="resource-explainer">
          <strong>Cách đọc trang này trong 20 giây</strong>
          <p>
            Hãy nhìn thẻ “Phân tích tự động” trước. Nếu màu xanh, bạn có thể
            dùng Hina bình thường. Màu vàng nghĩa là sắp chật VRAM. Màu đỏ nghĩa
            là phải chờ scheduler unload model hoặc đóng tác vụ GPU khác.
            “Ngân sách VRAM” là mức Hina dùng để quyết định có cho model chạy hay
            không; “VRAM model đo được” mới là số provider báo đang chiếm.
          </p>
        </aside>
      </template>

      <div v-else class="resource-loading">
        <span></span>
        <strong>Đang chờ snapshot tài nguyên đầu tiên…</strong>
        <p>Control plane cần tối đa vài giây để hỏi driver NVIDIA và các provider.</p>
      </div>
    </section>

    <section v-else-if="activePage === 'live2d'" class="dashboard-page live2d-page">
      <div class="page-heading">
        <p class="eyebrow">M07 / EXTERNAL LIVE2D RENDERER</p>
        <h2>Avatar Live2D qua VTube Studio</h2>
        <p class="purpose">
          Đây là cách project Neuro hiển thị nhân vật: model Live2D chạy trong
          VTube Studio, còn Hina dùng API local để xem model hiện tại, bật hotkey
          biểu cảm và đổi bố cục. Khi VTube Studio tắt, widget VRM trong suốt của
          Hina vẫn là phương án dự phòng và chat/voice không bị dừng.
        </p>
      </div>

      <div class="vtube-status-strip" :data-connected="vtubeStatus?.authenticated">
        <div>
          <span>Trạng thái</span>
          <strong>
            {{ vtubeStatus?.authenticated
              ? "Đã kết nối và xác thực"
              : vtubeStatus?.state === "needs_authorization"
                ? "Đang chờ bạn cấp quyền"
                : "Chưa kết nối" }}
          </strong>
        </div>
        <div>
          <span>Địa chỉ local cố định</span>
          <strong><code>{{ vtubeStatus?.endpoint ?? "ws://127.0.0.1:8001" }}</code></strong>
        </div>
        <div>
          <span>Renderer ưu tiên</span>
          <strong>{{ vtubeStatus?.model.loaded ? "Live2D đã chọn" : "VRM fallback" }}</strong>
        </div>
        <div>
          <span>Token</span>
          <strong>{{ vtubeStatus?.authorizationStored ? "Đã lưu cục bộ" : "Chưa có" }}</strong>
        </div>
      </div>

      <div class="live2d-grid">
        <article class="live2d-card setup-card">
          <p class="eyebrow">THIẾT LẬP MỘT LẦN</p>
          <h3>Để dùng Hiyori giống ảnh của Neuro</h3>
          <ol>
            <li>Mở VTube Studio trên Windows và vào Settings → Plugins.</li>
            <li>Bật “Allow Plugin API access”; API phải nghe ở cổng mặc định 8001.</li>
            <li>Trong VTube Studio, chọn Hiyori hoặc model Live2D bạn có quyền dùng.</li>
            <li>Chuyển sang tab Settings → biểu tượng camera → kéo xuống “Spout2 Config” và bật “Activate Spout2”.</li>
            <li>Trong phần Background chọn màu đen rồi bật “Transparent in capture” để widget không có nền.</li>
            <li>Bấm nút kết nối dưới đây rồi chọn <strong>Allow</strong> trong hộp thoại VTube Studio.</li>
          </ol>
          <div class="button-row">
            <button
              class="primary"
              type="button"
              :disabled="vtubeBusy || vtubeStatus?.authenticated"
              @click="connectVTubeStudio"
            >
              Kết nối &amp; xin quyền
            </button>
            <button
              type="button"
              :disabled="vtubeBusy || !vtubeStatus?.authenticated"
              @click="refreshVTubeStudioStatus(true)"
            >
              Đọc lại model
            </button>
            <button
              type="button"
              :disabled="vtubeBusy || !vtubeStatus?.connected"
              @click="disconnectVTubeStudio"
            >
              Ngắt kết nối
            </button>
          </div>
          <p v-if="vtubeMessage" class="vtube-message" role="status">{{ vtubeMessage }}</p>
          <p v-if="vtubeStatus?.lastErrorCode" class="inline-error">
            {{ vtubeStatus.lastErrorCode }} — hãy chắc rằng VTube Studio đang mở và Plugin API đã bật.
          </p>
        </article>

        <article class="live2d-card spout-card">
          <p class="eyebrow">WIDGET / SPOUT2 FRAME BRIDGE</p>
          <h3>
            {{ spoutStatus?.frameReady
              ? "Widget đang nhận frame Live2D thật"
              : "Widget đang chờ frame Live2D" }}
          </h3>
          <p>
            Cầu nối này chỉ nhận sender <code>VTubeStudioSpout</code> trên loopback,
            giữ frame mới nhất trong RAM rồi đưa vào widget. Nếu bridge lỗi, VRM
            local tự hiện lại; chat, mic và kéo thả không bị khóa.
          </p>
          <div class="status-grid">
            <div>
              <span>Bridge</span>
              <strong :data-good="spoutStatus?.state === 'ready'">
                {{ spoutStatus?.state ?? "chưa đọc" }}
              </strong>
            </div>
            <div>
              <span>Sender</span>
              <strong>{{ spoutStatus?.sender ?? "—" }}</strong>
            </div>
            <div>
              <span>Kích thước frame</span>
              <strong>
                {{ spoutStatus?.width && spoutStatus?.height
                  ? `${spoutStatus.width} × ${spoutStatus.height}`
                  : "—" }}
              </strong>
            </div>
            <div>
              <span>Nền trong suốt</span>
              <strong :data-good="spoutStatus?.transparent">
                {{ spoutStatus?.transparent ? "Đã bật" : "Chưa bật" }}
              </strong>
            </div>
          </div>
          <p v-if="spoutStatus?.lastErrorCode" class="inline-error">
            {{ spoutStatus.lastErrorCode }}
          </p>
          <p v-else-if="spoutStatus?.frameReady && !spoutStatus.transparent" class="vtube-message">
            Frame đã vào widget nhưng nền vẫn opaque. Bật “Transparent in capture”
            trong VTube Studio để giữ nền desktop trong suốt.
          </p>
        </article>

        <article class="live2d-card">
          <p class="eyebrow">MODEL ĐANG CHỌN TRONG VTUBE STUDIO</p>
          <h3>{{ vtubeStatus?.model.name || "Chưa tải model Live2D" }}</h3>
          <div class="status-grid">
            <div><span>Model loaded</span><strong>{{ vtubeStatus?.model.loaded ? "Có" : "Không" }}</strong></div>
            <div><span>Model ID</span><strong>{{ vtubeStatus?.model.id || "—" }}</strong></div>
            <div><span>File VTS</span><strong>{{ vtubeStatus?.model.vtsModelName || "—" }}</strong></div>
            <div><span>Số hotkey</span><strong>{{ vtubeStatus?.hotkeys.length ?? 0 }}</strong></div>
          </div>
          <p>
            Hina không đọc file model từ ổ đĩa và không nhận frame video qua API.
            VTube Studio tự render Live2D; Hina chỉ gửi những lệnh đã cố định bên dưới.
          </p>
        </article>

        <article class="live2d-card hotkey-card">
          <p class="eyebrow">BIỂU CẢM / ANIMATION</p>
          <h3>Hotkey của model hiện tại</h3>
          <p>
            Dùng để thử biểu cảm hoặc animation đã được chính model cấu hình sẵn.
            Dashboard chỉ cho bấm ID vừa đọc từ model; không gửi payload tùy ý.
          </p>
          <div v-if="vtubeStatus?.hotkeys.length" class="hotkey-grid">
            <button
              v-for="hotkey in vtubeStatus.hotkeys"
              :key="hotkey.id"
              type="button"
              :disabled="vtubeBusy || !vtubeStatus.authenticated"
              :title="hotkey.type"
              @click="triggerVTubeStudioHotkey(hotkey.id)"
            >
              {{ hotkey.name }}
              <small>{{ hotkey.type }}</small>
            </button>
          </div>
          <p v-else class="empty-state">
            Chưa có hotkey. Hãy kết nối, tải model trong VTube Studio rồi bấm “Đọc lại model”.
          </p>
        </article>

        <article class="live2d-card movement-card">
          <p class="eyebrow">BỐ CỤC STREAM</p>
          <h3>Đưa nhân vật tới vị trí có sẵn</h3>
          <p>
            Ba preset chỉ thay vị trí/kích thước model đang mở. Chúng không sửa
            model, không điều khiển chuột và có thể hoàn tác trực tiếp trong VTube Studio.
          </p>
          <div class="preset-grid">
            <button
              type="button"
              :disabled="vtubeBusy || !vtubeStatus?.authenticated"
              @click="moveVTubeStudioModel('chat')"
            >
              Chat
              <small>Nhân vật lớn, gần trung tâm</small>
            </button>
            <button
              type="button"
              :disabled="vtubeBusy || !vtubeStatus?.authenticated"
              @click="moveVTubeStudioModel('screen')"
            >
              Chia sẻ màn hình
              <small>Dạt phải, dành chỗ cho nội dung</small>
            </button>
            <button
              type="button"
              :disabled="vtubeBusy || !vtubeStatus?.authenticated"
              @click="moveVTubeStudioModel('react')"
            >
              React
              <small>Nhỏ hơn để xem video/game</small>
            </button>
          </div>
        </article>
      </div>

      <aside class="live2d-license-notice">
        <strong>Vì sao Hiyori không nằm sẵn trong repo Hina?</strong>
        <p>
          Neuro chỉ nói rằng tác giả dùng model Hiyori mặc định; file Hiyori
          không thuộc source MIT của họ. Hiyori là sample của Live2D và chịu
          Free Material License/sample terms riêng. Vì vậy Hina kết nối tới
          model bạn tự chọn trong VTube Studio, không copy hay nhận thay điều
          khoản asset. Trang tham khảo:
          <code>live2d.com/en/learn/sample/momose-hiyori-video/</code>.
        </p>
      </aside>
    </section>

    <section v-else class="stage-grid" :data-page="activePage">
      <article
        v-if="activePage === 'avatar'"
        class="stage"
        :data-state="stageState"
        :data-expression="stageExpression"
        :data-viseme="stageViseme"
        :data-vrm-loaded="vrmReady"
      >
        <div class="stage-topline">
          <span>
            {{ vrmReady
              ? "HINA KAWAII v0.1 · COLORED ANIME PROTOTYPE"
              : vrmError
                ? "VRM LOAD FAILED · CODE-NATIVE FALLBACK"
                : "CODE-NATIVE FALLBACK · VRM ĐANG TẢI" }}
          </span>
          <span>#{{ avatar?.sequence ?? 0 }} · {{ avatar?.mode ?? "offline" }}</span>
        </div>
        <VrmStage
          :key="vrmStageKey"
          :class="{ 'vrm-stage-hidden': !vrmReady }"
          :state="stageState"
          :expression="stageExpression"
          :viseme="stageViseme"
          :intensity="stageIntensity"
          @ready="handleVrmReady"
          @failed="handleVrmFailure"
          @performance="handleVrmPerformance"
        />
        <svg
          v-if="!vrmReady"
          class="avatar"
          viewBox="0 0 520 620"
          role="img"
          aria-label="Hina code-native avatar fallback"
        >
          <defs>
            <linearGradient id="desktopHair" x1="0" x2="1" y1="0" y2="1">
              <stop offset="0" stop-color="#3c3150"/>
              <stop offset="1" stop-color="#17131f"/>
            </linearGradient>
            <radialGradient id="desktopSkin" cx="45%" cy="34%">
              <stop offset="0" stop-color="#ffe8da"/>
              <stop offset="1" stop-color="#e7bdac"/>
            </radialGradient>
          </defs>
          <circle class="aura" cx="260" cy="285" r="215"/>
          <g class="avatar-body">
            <path class="hair" d="M91 514c12-118 7-246 46-352C164 88 210 52 265 52c71 0 126 58 147 151 24 108 6 226 24 311z"/>
            <path class="coat" d="M80 620c11-109 71-174 180-174s170 65 181 174z"/>
            <path class="shirt" d="M191 620l27-160h84l29 160z"/>
            <path class="collar" d="M176 472l72 62-45 35-48-77zM344 472l-72 62 45 35 48-77z"/>
            <path class="neck" d="M220 421h80v77c-18 16-62 16-80 0z"/>
            <ellipse class="face" cx="260" cy="287" rx="137" ry="168"/>
            <path class="hair fringe" d="M124 238c6-117 64-181 144-181 89 0 139 74 140 183-45-32-70-70-90-118-20 52-75 92-194 116z"/>
            <path class="hair side" d="M124 219c-30 80-12 194 45 246l26-49c-34-58-41-128-28-211zM397 211c31 88 17 198-45 254l-28-48c37-64 43-136 27-218z"/>
            <path class="eye left" d="M166 287q40-34 78 0q-39 25-78 0z"/>
            <path class="eye right" d="M276 287q40-34 78 0q-39 25-78 0z"/>
            <circle class="glint" cx="209" cy="279" r="5"/>
            <circle class="glint" cx="319" cy="279" r="5"/>
            <path class="line brow-left" d="M170 249q35-19 70 0"/>
            <path class="line brow-right" d="M280 249q35-19 70 0"/>
            <path class="line nose" d="M257 296l-7 48 19 4"/>
            <ellipse class="blush" cx="176" cy="344" rx="28" ry="10"/>
            <ellipse class="blush" cx="344" cy="344" rx="28" ry="10"/>
            <path class="line mouth-line" d="M222 384q38 25 76 0"/>
            <ellipse
              class="mouth"
              cx="260"
              cy="390"
              :rx="stageMouthRx"
              :ry="stageMouthRy"
            />
            <g class="hairpin">
              <path d="M130 196l66-39M136 218l67-37"/>
              <circle cx="130" cy="196" r="8"/>
              <circle cx="136" cy="218" r="8"/>
            </g>
          </g>
        </svg>
        <div class="stage-caption">
          <strong>{{ stateLabels[stageState] }}</strong>
          <span>
            {{ stageState }} · {{ avatar?.expression ?? "offline" }} ·
            {{ stageViseme }} {{ Math.round(stageIntensity * 100) }}% ·
            {{ vrmReady ? `${vrmFps || "—"} FPS` : "SVG fallback" }}
          </span>
        </div>
      </article>

      <aside class="operator-panel">
        <div>
          <p class="eyebrow">TYPED IPC / LOOPBACK ONLY</p>
          <h2>Điều khiển operator</h2>
          <p class="purpose">
            Desktop chỉ nhận snapshot trình bày qua preload API có tên cố định.
            Renderer không có Node, filesystem, database, model hay fetch trực tiếp.
          </p>
        </div>

        <div class="status-grid">
          <div><span>State</span><strong>{{ stateLabels[stageState] }}</strong></div>
          <div><span>Biểu cảm</span><strong>{{ avatar?.expression ?? "—" }}</strong></div>
          <div><span>Khẩu hình</span><strong>{{ stageViseme }} · {{ Math.round(stageIntensity * 100) }}%</strong></div>
          <div><span>Nguồn cue</span><strong>{{ avatar?.source ?? "—" }}</strong></div>
          <div><span>Safety revision</span><strong>{{ safety?.state.revision ?? "—" }}</strong></div>
          <div><span>Visual Hina</span><strong>{{ vrmPresentationId || "Đang tải…" }}</strong></div>
        </div>

        <section class="control-card widget-settings-card">
          <div class="presentation-heading">
            <div>
              <p class="eyebrow">DESKTOP WIDGET</p>
              <h3>Quản lý widget avatar</h3>
            </div>
            <span class="presentation-status" :data-ready="widgetStatus?.visible">
              {{ widgetStatus?.visible ? "Đang hiện" : "Đang ẩn" }}
            </span>
          </div>
          <p>
            Widget là avatar trong suốt nổi trên desktop. Kéo trực tiếp nhân vật
            để di chuyển; vị trí hợp lệ sẽ được nhớ cho lần mở sau. Các nút này
            chỉ quản lý cửa sổ, không thay đổi state hội thoại hay giọng nói.
          </p>
          <div class="status-grid widget-position-grid">
            <div>
              <span>Vị trí hiện tại</span>
              <strong>
                {{ widgetStatus ? `${widgetStatus.position.x}, ${widgetStatus.position.y}` : "Đang đọc…" }}
              </strong>
            </div>
            <div>
              <span>Luôn nổi</span>
              <strong>{{ widgetStatus?.alwaysOnTop ? "Có" : "Không" }}</strong>
            </div>
          </div>
          <div class="button-row">
            <button
              :disabled="busy || !widgetStatus?.visible"
              @click="applyWidgetControl('hide')"
            >
              Ẩn widget
            </button>
            <button
              :disabled="busy || widgetStatus?.visible"
              @click="applyWidgetControl('show')"
            >
              Hiện widget
            </button>
            <button
              :disabled="busy || !widgetStatus"
              @click="applyWidgetControl('reset_position')"
            >
              Đặt lại vị trí
            </button>
          </div>
        </section>

        <section class="control-card presentation-card">
          <div class="presentation-heading">
            <div>
              <p class="eyebrow">HINA VISUAL PROFILE</p>
              <h3>{{ vrmDisplayName || "Đang chuẩn bị Hina…" }}</h3>
            </div>
            <span class="presentation-status" :data-ready="vrmReady">
              {{ vrmReady ? "Đã có màu" : "Đang tải" }}
            </span>
          </div>
          <p>
            Bản này dùng khuôn VRM có license làm nền, sau đó áp bảng màu sakura,
            nơ tóc/ngực, chớp mắt và dáng đứng tay hạ tự nhiên do dự án tự tạo.
            Texture được nhúng local, không tải từ Internet.
          </p>
          <div class="palette-row" aria-label="Bảng màu Hina">
            <span title="Sakura pink"></span>
            <span title="Lavender"></span>
            <span title="Warm cream"></span>
            <span title="Plum"></span>
          </div>
          <small v-if="vrmReady">
            Đã đọc {{ vrmTextureCount }} texture nhúng · đã phối màu
            {{ vrmStyledMaterialCount }} material.
          </small>
        </section>

        <section class="control-card">
          <h3>Hiệu năng renderer thật</h3>
          <p>
            FPS là số khung hình mỗi giây. p95/p99 cho biết 95%/99% khung hình
            hoàn tất nhanh hơn bao nhiêu mili-giây; drop là tỷ lệ khung ước tính
            bị lỡ. Đây là cửa sổ đo ngắn 2 giây, không phải benchmark OBS dài giờ.
          </p>
          <div class="status-grid performance-grid">
            <div><span>FPS / mục tiêu</span><strong>{{ vrmPerformance ? `${vrmPerformance.fps} / ${vrmPerformance.targetFps}` : "Đang đo…" }}</strong></div>
            <div><span>Frame p95 / p99</span><strong>{{ vrmPerformance ? `${vrmPerformance.frameTimeP95Ms} / ${vrmPerformance.frameTimeP99Ms} ms` : "—" }}</strong></div>
            <div><span>Ước tính drop</span><strong>{{ vrmPerformance ? `${vrmPerformance.droppedFramePercent}%` : "—" }}</strong></div>
            <div><span>Mẫu / cửa sổ</span><strong>{{ vrmPerformance ? `${vrmPerformance.sampleCount} / ${vrmPerformance.windowMs} ms` : "—" }}</strong></div>
          </div>
        </section>

        <section class="control-card">
          <h3>Xem thử visual</h3>
          <p>
            Đây là <code>manual-preview</code>, chỉ đổi state renderer qua backend;
            không tạo hội thoại hay TTS giả.
          </p>
          <label for="previewState">State muốn xem</label>
          <select id="previewState" v-model="previewState" :disabled="busy">
            <option v-for="(label, value) in stateLabels" :key="value" :value="value">
              {{ label }} — {{ value }}
            </option>
          </select>
          <div class="button-row">
            <button class="primary" :disabled="busy || !connected" @click="preview">Xem thử</button>
            <button :disabled="busy || !connected" @click="resetAvatar">Đặt về idle</button>
          </div>
        </section>

        <section class="control-card">
          <h3>Âm thanh & khẩn cấp</h3>
          <p>Mute tắt âm thanh; emergency stop chặn hành động mới tại safety authority.</p>
          <div class="button-row">
            <button :disabled="busy || !safety" @click="toggleMute">
              {{ safety?.state.muted ? "Tắt mute" : "Bật mute" }}
            </button>
            <button
              class="danger"
              :disabled="busy || !safety"
              @click="toggleEmergency"
            >
              {{ safety?.state.emergencyStopped ? "Khôi phục hoạt động" : "Dừng khẩn cấp" }}
            </button>
          </div>
        </section>

        <section class="limitations">
          <strong>Giới hạn trung thực</strong>
          <span>
            VRM: {{ vrmReady ? "đã tải local, có texture và profile Hina" : "chưa tải; đang dùng SVG" }}
          </span>
          <span>
            Nhân vật: Hina prototype v0.1 dùng base VRM phát triển; chưa phải
            model đặt vẽ độc quyền/final do owner duyệt
          </span>
          <span>
            Miệng desktop: theo viseme phổ âm thanh thật khi Dev Console phát TTS;
            đây là heuristic, chưa phải căn phoneme chính xác
          </span>
          <span>
            Control plane: tự thử lại mỗi 250 ms; sau khi service restart,
            avatar mới bắt đầu ở state idle an toàn
          </span>
          <span v-if="vrmError" class="inline-error">Lỗi VRM: {{ vrmError }}</span>
          <button
            v-if="vrmError"
            id="retryVrmButton"
            type="button"
            @click="retryVrm"
          >
            Thử tải lại VRM local
          </button>
        </section>

        <section class="asset-notice">
          <strong>Asset đang dùng để làm gì?</strong>
          <p>
            <code>VRM1_Constraint_Twist_Sample</code> vẫn là base mesh VRM 1.0
            chính thức thuộc pixiv Inc., cho phép avatar use, commercial use,
            modification và redistribution theo metadata nhúng. Profile màu,
            pose và phụ kiện “Hina Kawaii · Pastel Sakura” là code original trong
            repository; đây chưa phải artwork VRM độc quyền do dự án sở hữu.
          </p>
        </section>

        <details>
          <summary>Snapshot renderer-safe</summary>
          <pre>{{ snapshot }}</pre>
        </details>
      </aside>
    </section>
  </main>
</template>
