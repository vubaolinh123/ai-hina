<script setup lang="ts">
import { computed, defineAsyncComponent, onBeforeUnmount, onMounted, ref } from "vue";

const VrmStage = defineAsyncComponent(() => import("./VrmStage.vue"));

const avatar = ref<AvatarStatus | null>(null);
const safety = ref<SafetyStatus | null>(null);
const busy = ref(false);
const vrmReady = ref(false);
const controlReady = ref(false);
let avatarTimer: number | null = null;
let safetyTimer: number | null = null;
let avatarRefreshPending = false;
let safetyRefreshPending = false;

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
  if (avatarRefreshPending) return;
  avatarRefreshPending = true;
  try {
    avatar.value = await window.hinaDesktop.getAvatarStatus();
    controlReady.value = true;
    markWidgetReady();
  } catch (error) {
    console.error(
      "[hina-widget] E_DESKTOP_WIDGET_AVATAR",
      error instanceof Error ? error.message : "unknown error",
    );
  } finally {
    avatarRefreshPending = false;
  }
}

async function refreshSafety(): Promise<void> {
  if (safetyRefreshPending) return;
  safetyRefreshPending = true;
  try {
    safety.value = await window.hinaDesktop.getSafetyStatus();
  } catch (error) {
    console.error(
      "[hina-widget] E_DESKTOP_WIDGET_SAFETY",
      error instanceof Error ? error.message : "unknown error",
    );
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
});
</script>

<template>
  <main
    class="desktop-widget"
    :data-muted="muted"
    tabindex="0"
    aria-label="Hina desktop widget. Kéo nhân vật để di chuyển; rê chuột lên nhân vật để mở Voice."
    @keydown="blurWidget"
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
    </div>
  </main>
</template>
