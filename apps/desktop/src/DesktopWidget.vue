<script setup lang="ts">
import { computed, defineAsyncComponent, onBeforeUnmount, onMounted, ref } from "vue";
import { createAutoListenDetector } from "./auto-listen-detector.mjs";
import { encodePcmWav, mergeAudioChunks, resampleAudio } from "./audio-utils";
import {
  MicrophoneRecorder,
  type MicrophoneCapture,
} from "./microphone-recorder";

const VrmStage = defineAsyncComponent(() => import("./VrmStage.vue"));

const avatar = ref<AvatarStatus | null>(null);
const safety = ref<SafetyStatus | null>(null);
const busy = ref(false);
const hovered = ref(false);
const vrmReady = ref(false);
const controlReady = ref(false);
const micRecording = ref(false);
const autoListenEnabled = ref(false);
const voiceBusy = ref(false);
const voiceStatus = ref("");
const chatSessionId = crypto.randomUUID();
let avatarTimer: number | null = null;
let safetyTimer: number | null = null;
let avatarRefreshPending = false;
let safetyRefreshPending = false;
let controlRetryAt = 0;
let controlRetryDelay = 1_000;
let recording: MicrophoneRecorder | null = null;
let activeTurnId: string | null = null;
let finishingCapture = false;
let captureMode: "manual" | "auto" | null = null;
let autoRestartTimer: number | null = null;
const autoListenDetector = createAutoListenDetector();

function controlRequestAllowed(): boolean {
  return Date.now() >= controlRetryAt;
}

function noteControlFailure(error: unknown, operation: string): void {
  const message = error instanceof Error ? error.message : "E_DESKTOP_CONTROL_OFFLINE";
  console.warn(`[hina-widget] ${operation}`, message);
  if (message.includes("E_DESKTOP_CONTROL_OFFLINE")) {
    controlRetryAt = Date.now() + controlRetryDelay;
    controlRetryDelay = Math.min(controlRetryDelay * 2, 30_000);
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
const muted = computed(() => safety.value?.state.muted ?? false);
const voiceLabel = computed(() => (
  muted.value ? "Voice · Bật giọng Hina" : "Voice · Tắt giọng Hina"
));

function markWidgetReady(): void {
  if (vrmReady.value && controlReady.value) {
    document.documentElement.dataset.widgetReady = "true";
    delete document.documentElement.dataset.widgetError;
  }
}

async function refreshAvatar(): Promise<void> {
  if (avatarRefreshPending || !controlRequestAllowed()) return;
  avatarRefreshPending = true;
  try {
    avatar.value = await window.hinaDesktop.getAvatarStatus();
    controlReady.value = true;
    markWidgetReady();
  } catch (error) {
    noteControlFailure(error, "E_DESKTOP_WIDGET_AVATAR");
  } finally {
    avatarRefreshPending = false;
  }
}

async function refreshSafety(): Promise<void> {
  if (safetyRefreshPending || !controlRequestAllowed()) return;
  safetyRefreshPending = true;
  try {
    safety.value = await window.hinaDesktop.getSafetyStatus();
  } catch (error) {
    noteControlFailure(error, "E_DESKTOP_WIDGET_SAFETY");
  } finally {
    safetyRefreshPending = false;
  }
}

async function toggleVoice(): Promise<void> {
  if (!safety.value || busy.value) return;
  busy.value = true;
  try {
    await window.hinaDesktop.applySafetyControl({
      action: "set_mute",
      enabled: !safety.value.state.muted,
    });
    await refreshSafety();
  } catch (error) {
    console.error(
      "[hina-widget] E_DESKTOP_WIDGET_VOICE",
      error instanceof Error ? error.message : "unknown error",
    );
  } finally {
    busy.value = false;
  }
}

async function playVoice(text: string): Promise<void> {
  if (muted.value || !text.trim()) return;
  const bytes = await window.hinaDesktop.synthesizeSpeech({
    text,
    utteranceId: crypto.randomUUID(),
    sessionId: chatSessionId,
    source: "owner.console",
  });
  const url = URL.createObjectURL(new Blob([Uint8Array.from(bytes)], { type: "audio/wav" }));
  const audio = new Audio(url);
  await new Promise<void>((resolve, reject) => {
    const cleanup = (): void => URL.revokeObjectURL(url);
    audio.addEventListener("ended", () => {
      cleanup();
      resolve();
    }, { once: true });
    audio.addEventListener("error", () => {
      cleanup();
      reject(new Error("E_WIDGET_TTS_PLAYBACK: không thể phát giọng Hina"));
    }, { once: true });
    void audio.play().catch((error: unknown) => {
      cleanup();
      reject(error);
    });
  });
}

async function pollVoiceTurn(turnId: string): Promise<void> {
  const turn = await window.hinaDesktop.getChatTurn(turnId);
  if (turn.outcome === "running") {
    await new Promise<void>((resolve) => window.setTimeout(resolve, 180));
    return pollVoiceTurn(turnId);
  }
  activeTurnId = null;
  if (turn.outcome === "completed" && turn.assistant) {
    voiceStatus.value = "Hina đang trả lời bằng giọng nói…";
    await playVoice(turn.assistant);
    voiceStatus.value = autoListenEnabled.value
      ? "Hina đã trả lời. Auto nghe sẽ mở lại sau một nhịp."
      : "Đã trả lời. Bạn có thể bấm Mic để nói tiếp.";
  } else if (turn.outcome === "interrupted") {
    voiceStatus.value = "Lượt nói đã được dừng.";
  } else {
    throw new Error(
      `${turn.errorCode ?? "E_CHAT_FAILED"}: ${turn.errorMessage ?? "Hina không thể trả lời."}`,
    );
  }
}

function handleVoiceError(error: unknown): void {
  activeTurnId = null;
  voiceBusy.value = false;
  voiceStatus.value = error instanceof Error ? error.message : "E_WIDGET_VOICE";
  console.error("[hina-widget] E_WIDGET_VOICE", voiceStatus.value);
}

function clearAutoRestart(): void {
  if (autoRestartTimer !== null) {
    window.clearTimeout(autoRestartTimer);
    autoRestartTimer = null;
  }
}

function scheduleAutoListenRestart(): void {
  clearAutoRestart();
  if (!autoListenEnabled.value) return;
  autoRestartTimer = window.setTimeout(() => {
    autoRestartTimer = null;
    if (autoListenEnabled.value && !voiceBusy.value && !micRecording.value) {
      void startMicCapture("auto");
    }
  }, 450);
}

function monitorAutoListen(capture: Readonly<{
  chunks: Float32Array[];
  sampleCount: number;
  sampleRate: number;
}>): void {
  if (
    captureMode !== "auto"
    || finishingCapture
    || voiceBusy.value
    || capture.chunks.length === 0
  ) return;
  const samples = capture.chunks[capture.chunks.length - 1];
  if (!samples) return;
  const decision = autoListenDetector.push(
    samples,
    performance.now(),
    capture.sampleCount / capture.sampleRate,
  );
  if (decision.voiceDetected && !decision.shouldSubmit) {
    voiceStatus.value = "Đang nghe bạn nói… Hina sẽ tự gửi khi bạn dừng lại.";
  }
  if (decision.shouldSubmit) {
    void finishMicCapture();
  }
}

async function restartSilentAutoCapture(): Promise<void> {
  const current = recording;
  if (!current || captureMode !== "auto" || finishingCapture) return;
  finishingCapture = true;
  recording = null;
  micRecording.value = false;
  captureMode = null;
  try {
    await current.stop();
  } finally {
    finishingCapture = false;
    autoListenDetector.reset();
    scheduleAutoListenRestart();
  }
}

async function finishMicCapture(): Promise<void> {
  if (finishingCapture) return;
  const current = recording;
  if (!current) return;
  finishingCapture = true;
  recording = null;
  micRecording.value = false;
  captureMode = null;
  let capture: MicrophoneCapture;
  try {
    capture = await current.stop();
  } catch (error) {
    finishingCapture = false;
    handleVoiceError(error);
    scheduleAutoListenRestart();
    return;
  }
  if (capture.sampleCount < capture.sampleRate * 0.25) {
    voiceStatus.value = "Đoạn ghi quá ngắn; hãy nói ít nhất một phần tư giây.";
    finishingCapture = false;
    scheduleAutoListenRestart();
    return;
  }
  const pcm = resampleAudio(
    mergeAudioChunks(capture.chunks, capture.sampleCount),
    capture.sampleRate,
    16_000,
  );
  const wav = encodePcmWav(pcm, 16_000);
  if (wav.byteLength > 1_048_576) {
    voiceStatus.value = "Audio vượt 1 MiB; hãy nói đoạn ngắn hơn.";
    finishingCapture = false;
    scheduleAutoListenRestart();
    return;
  }
  voiceBusy.value = true;
  voiceStatus.value = "Đang nhận diện giọng nói bằng Moonshine…";
  try {
    const transcription = await window.hinaDesktop.transcribeSpeech(wav, chatSessionId);
    const text = transcription.transcript.trim();
    if (!text) {
      voiceStatus.value = "Hina không nghe thấy câu nói; hãy thử lại.";
      return;
    }
    voiceStatus.value = `Bạn: ${text}`;
    const turn = await window.hinaDesktop.startChatTurn({
      sessionId: chatSessionId,
      source: "owner.console",
      text,
    });
    activeTurnId = turn.turnId;
    voiceStatus.value = "Hina đang suy nghĩ…";
    await pollVoiceTurn(turn.turnId);
  } catch (error) {
    handleVoiceError(error);
  } finally {
    voiceBusy.value = false;
    finishingCapture = false;
    autoListenDetector.reset();
    scheduleAutoListenRestart();
  }
}

async function startMicCapture(mode: "manual" | "auto"): Promise<void> {
  if (voiceBusy.value || micRecording.value || finishingCapture) return;
  if (!navigator.mediaDevices?.getUserMedia) {
    voiceStatus.value = "Electron không cung cấp quyền microphone.";
    return;
  }
  try {
    recording = await MicrophoneRecorder.start({
      maximumSeconds: mode === "auto" ? 15 : 30,
      chunkNotificationMilliseconds: 100,
      onChunk: mode === "auto" ? monitorAutoListen : undefined,
      onMaximumDuration: () => {
        if (mode === "auto" && !autoListenDetector.snapshot().voiceDetected) {
          void restartSilentAutoCapture();
        } else {
          void finishMicCapture();
        }
      },
    });
    captureMode = mode;
    autoListenDetector.reset();
    micRecording.value = true;
    voiceStatus.value = mode === "auto"
      ? "Auto nghe đang bật. Hãy nói, Hina sẽ tự gửi khi bạn dừng."
      : "Đang nghe… bấm Mic lần nữa để gửi câu nói.";
    await window.hinaDesktop.applyAvatarCue({
      source: "owner.console",
      state: "listening",
      mode: "manual-preview",
    });
  } catch (error) {
    streamCleanup();
    handleVoiceError(error);
  }
}

async function toggleMic(): Promise<void> {
  if (voiceBusy.value) return;
  if (autoListenEnabled.value) {
    autoListenEnabled.value = false;
    clearAutoRestart();
  }
  if (micRecording.value) {
    await finishMicCapture();
    return;
  }
  await startMicCapture("manual");
}

async function toggleAutoListen(): Promise<void> {
  if (voiceBusy.value) return;
  autoListenEnabled.value = !autoListenEnabled.value;
  clearAutoRestart();
  if (!autoListenEnabled.value) {
    streamCleanup();
    voiceStatus.value = "Auto nghe đã tắt. Bấm Mic để nói thủ công.";
    return;
  }
  if (micRecording.value) streamCleanup();
  await startMicCapture("auto");
}

function streamCleanup(): void {
  clearAutoRestart();
  if (!recording) return;
  void recording.stop();
  recording = null;
  micRecording.value = false;
  captureMode = null;
  autoListenDetector.reset();
}

function handleVrmReady(details: {
  displayName: string;
  presentationId: string;
  source: "bundled-vrm-1.0";
  loadedTextureCount: number;
  styledMaterialCount: number;
}): void {
  vrmReady.value = true;
  document.documentElement.dataset.vrmReady = "true";
  document.documentElement.dataset.avatarPresentation = details.presentationId;
  document.documentElement.dataset.avatarTextureCount =
    String(details.loadedTextureCount);
  document.documentElement.dataset.avatarStyledMaterialCount =
    String(details.styledMaterialCount);
  markWidgetReady();
}

function handleVrmFailure(message: string): void {
  vrmReady.value = false;
  delete document.documentElement.dataset.widgetReady;
  document.documentElement.dataset.widgetError = message.slice(0, 200);
  console.error("[hina-widget] E_DESKTOP_WIDGET_VRM", message.slice(0, 200));
}

function blurWidget(event: KeyboardEvent): void {
  if (event.key === "Escape" && event.currentTarget instanceof HTMLElement) {
    event.currentTarget.blur();
  }
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
}

onMounted(async () => {
  await Promise.all([refreshAvatar(), refreshSafety()]);
  avatarTimer = window.setInterval(refreshAvatar, 250);
  safetyTimer = window.setInterval(refreshSafety, 1_000);
  window.addEventListener("beforeunload", stopPolling, { once: true });
});

onBeforeUnmount(() => {
  window.removeEventListener("beforeunload", stopPolling);
  stopPolling();
  streamCleanup();
});
</script>

<template>
  <main
    class="desktop-widget"
    :data-muted="muted"
    :data-hovered="hovered"
    :data-auto-listen="autoListenEnabled"
    tabindex="0"
    aria-label="Hina desktop widget. Kéo nhân vật để di chuyển; rê chuột lên nhân vật để mở Voice và Mic."
    @keydown="blurWidget"
    @pointerenter="hovered = true"
    @pointermove.passive="hovered = true"
    @pointerleave="hovered = false"
  >
    <section
      class="widget-avatar-surface"
      :data-state="stageState"
      :data-expression="stageExpression"
      :data-viseme="stageViseme"
      aria-label="Avatar Hina có thể kéo để di chuyển"
    >
      <VrmStage
        :class="{ 'vrm-stage-hidden': !vrmReady }"
        :state="stageState"
        :expression="stageExpression"
        :viseme="stageViseme"
        :intensity="stageIntensity"
        @ready="handleVrmReady"
        @failed="handleVrmFailure"
      />
    </section>

    <div class="widget-voice-controls">
      <button
        id="widgetMicButton"
        class="widget-control widget-mic-button"
        type="button"
        :aria-pressed="micRecording && !autoListenEnabled"
        :aria-label="micRecording && !autoListenEnabled ? 'Dừng microphone và gửi cho Hina' : 'Bật microphone để nói với Hina'"
        :title="micRecording && !autoListenEnabled ? 'Dừng microphone và gửi cho Hina' : 'Bật microphone để nói với Hina'"
        :disabled="voiceBusy || !safety"
        @click="toggleMic"
      >
        <span aria-hidden="true">{{ micRecording && !autoListenEnabled ? "⏹" : "🎙️" }}</span>
        <span>{{ micRecording && !autoListenEnabled ? "Dừng & gửi" : "Nói với Hina" }}</span>
      </button>
      <button
        id="widgetAutoListenButton"
        class="widget-control widget-auto-listen-button"
        type="button"
        :aria-pressed="autoListenEnabled"
        :aria-label="autoListenEnabled ? 'Tắt tự động nghe' : 'Bật tự động nghe và trả lời'"
        :title="autoListenEnabled ? 'Tắt tự động nghe' : 'Bật tự động nghe và trả lời'"
        :disabled="voiceBusy || !safety"
        @click="toggleAutoListen"
      >
        <span aria-hidden="true">{{ autoListenEnabled ? "🟢" : "⚪" }}</span>
        <span>Auto nghe · {{ autoListenEnabled ? "Đang bật" : "Đang tắt" }}</span>
      </button>
      <button
        id="widgetVoiceButton"
        class="widget-control widget-voice-button"
        type="button"
        :aria-pressed="muted"
        :aria-label="voiceLabel"
        :title="voiceLabel"
        :disabled="busy || !safety"
        @click="toggleVoice"
      >
        <span aria-hidden="true">{{ muted ? "🔇" : "🔊" }}</span>
        <span>Voice · {{ muted ? "Bật giọng" : "Tắt giọng" }}</span>
      </button>
      <small v-if="voiceStatus" class="widget-voice-status" role="status">
        {{ voiceStatus }}
      </small>
    </div>
  </main>
</template>
