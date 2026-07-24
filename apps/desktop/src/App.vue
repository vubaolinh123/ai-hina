<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from "vue";
import VrmStage from "./VrmStage.vue";

const stateLabels: Record<AvatarState, string> = {
  idle: "Nghỉ",
  listening: "Đang nghe",
  thinking: "Đang suy nghĩ",
  speaking: "Đang nói",
  interrupted: "Bị ngắt",
  error: "Có lỗi",
};

const avatar = ref<AvatarStatus | null>(null);
const safety = ref<SafetyStatus | null>(null);
const runtime = ref<RuntimeHealth | null>(null);
const previewState = ref<AvatarState>("idle");
const errorMessage = ref("");
const busy = ref(false);
const vrmReady = ref(false);
const vrmError = ref("");
const vrmFps = ref(0);
const vrmDisplayName = ref("");
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
        fps: vrmFps.value || null,
        developmentSample: true,
        phonemeAccurate: false,
      },
    }, null, 2)
  : "Chưa nhận được snapshot từ control plane.");

async function refreshAvatar(): Promise<void> {
  if (avatarRefreshPending) return;
  avatarRefreshPending = true;
  try {
    avatar.value = await window.hinaDesktop.getAvatarStatus();
    errorMessage.value = "";
  } catch (error) {
    errorMessage.value = error instanceof Error
      ? error.message
      : "E_DESKTOP_CONTROL_OFFLINE";
  } finally {
    avatarRefreshPending = false;
  }
}

async function refreshSafety(): Promise<void> {
  if (safetyRefreshPending) return;
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
    errorMessage.value = error instanceof Error ? error.message : "E_DESKTOP_SAFETY";
  } finally {
    safetyRefreshPending = false;
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
  source: "bundled-vrm-1.0";
}): void {
  vrmReady.value = true;
  vrmError.value = "";
  vrmDisplayName.value = details.displayName;
  document.documentElement.dataset.vrmReady = "true";
  delete document.documentElement.dataset.vrmError;
}

function handleVrmFailure(message: string): void {
  vrmReady.value = false;
  vrmError.value = message.slice(0, 200);
  document.documentElement.dataset.vrmError = vrmError.value;
  delete document.documentElement.dataset.vrmReady;
}

onMounted(async () => {
  await Promise.all([refreshAvatar(), refreshSafety()]);
  avatarTimer = window.setInterval(refreshAvatar, 250);
  safetyTimer = window.setInterval(refreshSafety, 1_000);
});

onBeforeUnmount(() => {
  if (avatarTimer !== null) window.clearInterval(avatarTimer);
  if (safetyTimer !== null) window.clearInterval(safetyTimer);
});
</script>

<template>
  <main class="desktop-shell">
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

    <section v-if="errorMessage" class="error-banner" role="alert">
      <strong>Không đọc được dữ liệu thật.</strong>
      <span>{{ errorMessage }}</span>
      <small>Hãy chạy <code>pnpm start:dev-console</code> trước, rồi mở lại desktop.</small>
    </section>

    <section class="stage-grid">
      <article
        class="stage"
        :data-state="stageState"
        :data-expression="stageExpression"
        :data-viseme="stageViseme"
        :data-vrm-loaded="vrmReady"
      >
        <div class="stage-topline">
          <span>
            {{ vrmReady
              ? "VRM 1.0 DEV SAMPLE · FINAL HINA ASSET PENDING"
              : vrmError
                ? "VRM LOAD FAILED · CODE-NATIVE FALLBACK"
                : "CODE-NATIVE FALLBACK · VRM ĐANG TẢI" }}
          </span>
          <span>#{{ avatar?.sequence ?? 0 }} · {{ avatar?.mode ?? "offline" }}</span>
        </div>
        <VrmStage
          v-show="vrmReady"
          :state="stageState"
          :expression="stageExpression"
          :viseme="stageViseme"
          :intensity="stageIntensity"
          @ready="handleVrmReady"
          @failed="handleVrmFailure"
          @fps="vrmFps = $event"
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
        </div>

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
            VRM: {{ vrmReady ? "đã tải sample official có license" : "chưa tải; đang dùng SVG" }}
          </span>
          <span>Nhân vật: sample phát triển, chưa phải thiết kế Hina cuối cùng</span>
          <span>
            Miệng desktop: theo viseme phổ âm thanh thật khi Dev Console phát TTS;
            đây là heuristic, chưa phải căn phoneme chính xác
          </span>
          <span v-if="vrmError" class="inline-error">Lỗi VRM: {{ vrmError }}</span>
        </section>

        <section class="asset-notice">
          <strong>Asset đang dùng để làm gì?</strong>
          <p>
            <code>VRM1_Constraint_Twist_Sample</code> là model VRM 1.0 chính thức
            dùng để kiểm tra renderer, biểu cảm và chuyển động. Model thuộc pixiv
            Inc., cho phép avatar use, commercial use và redistribution theo VRM
            Public License 1.0; không phải artwork Hina do dự án sở hữu.
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
