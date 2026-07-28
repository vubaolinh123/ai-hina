import { computed, ref } from "vue";
import type { FrameMetricsReport } from "../frame-metrics.mjs";

type VrmReadyDetails = {
  displayName: string;
  presentationId: string;
  source: "bundled-vrm-1.0";
  loadedTextureCount: number;
  styledMaterialCount: number;
};

type WidgetControlAction = "show" | "hide" | "reset_position";

export function useAvatarRuntime() {
  const avatar = ref<AvatarStatus | null>(null);
  const safety = ref<SafetyStatus | null>(null);
  const widgetStatus = ref<WidgetStatus | null>(null);
  const runtime = ref<RuntimeHealth | null>(null);
  const previewState = ref<AvatarState>("idle");
  const errorMessage = ref("");
  const busy = ref(false);
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

  const stageState = computed<AvatarState>(() => avatar.value?.state ?? "error");
  const stageExpression = computed(() => avatar.value?.expression ?? "concerned");
  const stageViseme = computed<AvatarStatus["viseme"]>(
    () => avatar.value?.viseme ?? "sil",
  );
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

  async function refreshAll(): Promise<void> {
    await Promise.all([refreshAvatar(), refreshSafety(), refreshWidget()]);
  }

  function startPolling(): void {
    if (avatarTimer === null) {
      avatarTimer = window.setInterval(refreshAvatar, 250);
    }
    if (safetyTimer === null) {
      safetyTimer = window.setInterval(refreshSafety, 1_000);
    }
    if (widgetTimer === null) {
      widgetTimer = window.setInterval(refreshWidget, 1_000);
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
    if (widgetTimer !== null) {
      window.clearInterval(widgetTimer);
      widgetTimer = null;
    }
  }

  async function retryConnection(): Promise<void> {
    busy.value = true;
    try {
      resetControlBackoff();
      await refreshAll();
    } finally {
      busy.value = false;
    }
  }

  async function applyWidgetControl(action: WidgetControlAction): Promise<void> {
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

  function handleVrmReady(details: VrmReadyDetails): void {
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

  return {
    avatar,
    safety,
    widgetStatus,
    runtime,
    previewState,
    errorMessage,
    busy,
    vrmReady,
    vrmError,
    vrmFps,
    vrmDisplayName,
    vrmPresentationId,
    vrmTextureCount,
    vrmStyledMaterialCount,
    vrmPerformance,
    vrmStageKey,
    stageState,
    stageExpression,
    stageViseme,
    stageIntensity,
    stageMouthRx,
    stageMouthRy,
    connected,
    snapshot,
    refreshSafety,
    refreshAll,
    startPolling,
    stopPolling,
    retryConnection,
    applyWidgetControl,
    preview,
    resetAvatar,
    toggleMute,
    toggleEmergency,
    handleVrmReady,
    handleVrmFailure,
    handleVrmPerformance,
    retryVrm,
  };
}
