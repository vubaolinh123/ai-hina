<script setup lang="ts">
import {
  computed,
  defineAsyncComponent,
  onBeforeUnmount,
  onMounted,
  ref,
} from "vue";
import { encodePcmWav, mergeAudioChunks, resampleAudio } from "./audio-utils";
import type { FrameMetricsReport } from "./frame-metrics.mjs";

const VrmStage = defineAsyncComponent(() => import("./VrmStage.vue"));
const DesktopWidget = defineAsyncComponent(() => import("./DesktopWidget.vue"));
type DashboardPage = "overview" | "chat" | "speech" | "avatar" | "runtime";

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
const runtime = ref<RuntimeHealth | null>(null);
const previewState = ref<AvatarState>("idle");
const errorMessage = ref("");
const busy = ref(false);
const activePage = ref<DashboardPage>("avatar");
const chatInput = ref("");
const chatMessages = ref<Array<{ role: "user" | "assistant" | "system"; text: string }>>([]);
const chatBusy = ref(false);
const chatError = ref("");
const chatVoiceEnabled = ref(true);
const chatSessionId = crypto.randomUUID();
const speechSessionId = crypto.randomUUID();
const speechRecording = ref(false);
const speechBusy = ref(false);
const speechStatus = ref("Sẵn sàng. Bấm Thu mic, nói một câu rồi bấm Dừng & nhận dạng.");
const speechTranscript = ref("");
const speechCorrelationId = ref("");
const speechTtsText = ref("Xin chào, mình là Hina. Đây là phần kiểm tra giọng nói tiếng Việt.");
const speechTtsAudioUrl = ref("");
let speechTtsAudio: HTMLAudioElement | null = null;
let speechRecorder: {
  stream: MediaStream;
  context: AudioContext;
  source: MediaStreamAudioSourceNode;
  processor: ScriptProcessorNode;
  sink: GainNode;
  chunks: Float32Array[];
  sampleCount: number;
  stopping: boolean;
} | null = null;
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
let avatarRefreshPending = false;
let safetyRefreshPending = false;
let controlRetryAt = 0;
let controlRetryDelay = 1_000;

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
    if (turn.outcome === "running") {
      chatPollTimer = window.setTimeout(() => void pollDesktopChat(turnId), 180);
      return;
    }
    activeChatTurnId = null;
    chatBusy.value = false;
    if (turn.outcome === "completed" && turn.assistant) {
      appendChatMessage("assistant", turn.assistant);
      try {
        await playAssistantVoice(turn.assistant);
      } catch (error) {
        chatError.value = error instanceof Error ? error.message : "E_DESKTOP_TTS";
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
    chatError.value = error instanceof Error ? error.message : "E_DESKTOP_CHAT";
    console.error("[hina-chat] E_DESKTOP_CHAT_POLL", chatError.value);
  }
}

async function sendDesktopChat(): Promise<void> {
  const text = chatInput.value.trim();
  if (!text || chatBusy.value) return;
  chatBusy.value = true;
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
}

function cleanupSpeechRecorder(): void {
  const current = speechRecorder;
  speechRecorder = null;
  speechRecording.value = false;
  if (!current) return;
  current.processor.onaudioprocess = null;
  current.source.disconnect();
  current.processor.disconnect();
  current.sink.disconnect();
  current.stream.getTracks().forEach((track) => track.stop());
  void current.context.close();
}

async function stopSpeechTest(): Promise<void> {
  const current = speechRecorder;
  if (!current || current.stopping) return;
  current.stopping = true;
  speechRecorder = null;
  speechRecording.value = false;
  current.processor.onaudioprocess = null;
  current.source.disconnect();
  current.processor.disconnect();
  current.sink.disconnect();
  current.stream.getTracks().forEach((track) => track.stop());
  const sampleRate = current.context.sampleRate;
  await current.context.close();
  if (current.sampleCount < sampleRate * 0.25) {
    speechStatus.value = "Audio quá ngắn. Hãy nói ít nhất khoảng 0,25 giây.";
    return;
  }
  const wav = encodePcmWav(
    resampleAudio(
      mergeAudioChunks(current.chunks, current.sampleCount),
      sampleRate,
      16_000,
    ),
    16_000,
  );
  if (wav.byteLength > 1_048_576) {
    speechStatus.value = "Audio vượt giới hạn 1 MiB. Hãy thử một câu ngắn hơn.";
    return;
  }
  speechBusy.value = true;
  speechStatus.value = "Đang gửi WAV thật sang Moonshine để nhận dạng tiếng Việt…";
  speechTranscript.value = "";
  speechCorrelationId.value = "";
  try {
    const result = await window.hinaDesktop.transcribeSpeech(wav, speechSessionId);
    speechTranscript.value = result.transcript.trim();
    speechCorrelationId.value = result.correlationId;
    speechStatus.value = result.speechDetected
      ? `STT hoàn tất trong ${result.processingMilliseconds} ms.`
      : "Moonshine không phát hiện tiếng nói trong đoạn thu.";
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
    const stream = await navigator.mediaDevices.getUserMedia({
      audio: {
        channelCount: 1,
        echoCancellation: true,
        noiseSuppression: true,
        autoGainControl: true,
      },
      video: false,
    });
    const context = new window.AudioContext();
    const source = context.createMediaStreamSource(stream);
    const processor = context.createScriptProcessor(4096, 1, 1);
    const sink = context.createGain();
    sink.gain.value = 0;
    speechRecorder = {
      stream,
      context,
      source,
      processor,
      sink,
      chunks: [],
      sampleCount: 0,
      stopping: false,
    };
    processor.onaudioprocess = (event) => {
      if (!speechRecorder || speechRecorder.stopping) return;
      const chunk = new Float32Array(event.inputBuffer.getChannelData(0));
      speechRecorder.chunks.push(chunk);
      speechRecorder.sampleCount += chunk.length;
      if (speechRecorder.sampleCount / context.sampleRate >= 30) {
        void stopSpeechTest();
      }
    };
    source.connect(processor);
    processor.connect(sink);
    sink.connect(context.destination);
    speechRecording.value = true;
    speechStatus.value = "Đang thu mic… nói một câu, sau đó bấm Dừng & nhận dạng.";
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
  speechStatus.value = "Đang tạo WAV bằng giọng Hina/VieNeu thật…";
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

async function refreshWidget(): Promise<void> {
  if (!controlRequestAllowed()) return;
  try {
    widgetStatus.value = await window.hinaDesktop.getWidgetStatus();
  } catch (error) {
    noteControlFailure(error);
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
  if (chatPollTimer !== null) {
    window.clearTimeout(chatPollTimer);
    chatPollTimer = null;
  }
}

function cleanupDesktop(): void {
  stopPolling();
  cleanupSpeechTest();
}

onMounted(async () => {
  windowMode.value = await window.hinaDesktop.getWindowMode();
  document.documentElement.dataset.windowMode = windowMode.value;
  if (windowMode.value !== "operator") return;
  await Promise.all([refreshAvatar(), refreshSafety(), refreshWidget()]);
  avatarTimer = window.setInterval(refreshAvatar, 250);
  safetyTimer = window.setInterval(refreshSafety, 1_000);
  widgetTimer = window.setInterval(refreshWidget, 1_000);
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
          <p class="eyebrow">M07 / LOCAL OPERATOR DESKTOP</p>
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
      <button type="button" :class="{ active: activePage === 'avatar' }" @click="activePage = 'avatar'">
        Avatar Stage
        <small>Xem biểu cảm và lip-sync</small>
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
      </div>
      <div class="quick-actions">
        <button class="primary" type="button" @click="activePage = 'chat'">Mở chat với Hina</button>
        <button type="button" @click="activePage = 'speech'">Kiểm tra Mic / STT / TTS</button>
        <button type="button" @click="activePage = 'avatar'">Xem avatar</button>
        <button type="button" @click="activePage = 'runtime'">Quản lý widget và Safety</button>
      </div>
    </section>

    <section v-else-if="activePage === 'chat'" class="dashboard-page chat-page">
      <div class="page-heading">
        <p class="eyebrow">DASHBOARD / CHAT</p>
        <h2>Nói chuyện với Hina bằng text và voice</h2>
        <p class="purpose">Nhập câu hỏi bằng tiếng Việt. Hina trả về nội dung text trước, sau đó phát cùng nội dung bằng giọng VieNeu nếu Voice đang bật.</p>
      </div>
      <div class="chat-layout">
        <div class="chat-messages" aria-live="polite">
          <p v-if="chatMessages.length === 0" class="chat-empty">Chưa có tin nhắn. Hãy bắt đầu bằng một câu chào.</p>
          <div v-for="(message, index) in chatMessages" :key="`${index}-${message.role}`" class="chat-message" :data-role="message.role">
            <span>{{ message.role === 'user' ? 'Bạn' : message.role === 'assistant' ? 'Hina' : 'Hệ thống' }}</span>
            <p>{{ message.text }}</p>
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
          rồi gửi WAV cho Moonshine. Phần TTS gửi đoạn text cho VieNeu và phát lại WAV Hina tạo ra.
        </p>
      </div>
      <div class="speech-test-grid">
        <article class="speech-test-card">
          <p class="eyebrow">MIC → MOONSHINE STT</p>
          <h3>Hina nghe bạn nói</h3>
          <p>
            Dùng khi cần kiểm tra quyền microphone hoặc xem Moonshine nhận dạng tiếng Việt có đúng
            không. Audio chỉ được giữ trong bộ nhớ để xử lý lượt hiện tại.
          </p>
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
              Dừng &amp; nhận dạng
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
          <p class="eyebrow">TEXT → VIENEU TTS</p>
          <h3>Nghe thử giọng Hina</h3>
          <p>
            Dùng khi cần kiểm tra giọng, cảm xúc và tốc độ nói. Câu dài được pipeline tự tăng tốc
            trong giới hạn đã cấu hình; câu ngắn giữ nhịp tự nhiên.
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
