<script setup lang="ts">
import { computed, type Component } from "vue";
import type { FrameMetricsReport } from "../../frame-metrics.mjs";

type VrmReadyDetails = {
  displayName: string;
  presentationId: string;
  source: "bundled-vrm-1.0";
  loadedTextureCount: number;
  styledMaterialCount: number;
};

const props = defineProps<{
  stageComponent: Component;
  stageState: AvatarState;
  stageExpression: string;
  stageViseme: AvatarStatus["viseme"];
  stageIntensity: number;
  stageMouthRx: number;
  stageMouthRy: number;
  avatar: AvatarStatus | null;
  safety: SafetyStatus | null;
  busy: boolean;
  connected: boolean;
  previewState: AvatarState;
  stateLabels: Record<AvatarState, string>;
  vrmReady: boolean;
  vrmError: string;
  vrmFps: number;
  vrmDisplayName: string;
  vrmPresentationId: string;
  vrmTextureCount: number;
  vrmStyledMaterialCount: number;
  vrmPerformance: FrameMetricsReport | null;
  vrmStageKey: number;
  snapshot: string;
}>();

const emit = defineEmits<{
  "update:previewState": [value: AvatarState];
  preview: [];
  resetAvatar: [];
  retryVrm: [];
  vrmReady: [details: VrmReadyDetails];
  vrmFailed: [message: string];
  vrmPerformance: [report: FrameMetricsReport];
}>();

const previewState = computed({
  get: () => props.previewState,
  set: (value: AvatarState) => emit("update:previewState", value),
});
</script>

<template>
  <section class="stage-grid avatar-page" data-page="avatar">
    <article
      class="stage"
      :data-state="props.stageState"
      :data-expression="props.stageExpression"
      :data-viseme="props.stageViseme"
      :data-vrm-loaded="props.vrmReady"
    >
      <div class="stage-topline">
        <span>
          {{ props.vrmReady
            ? "HINA KAWAII v0.1 · COLORED ANIME PROTOTYPE"
            : props.vrmError
              ? "VRM LOAD FAILED · CODE-NATIVE FALLBACK"
              : "CODE-NATIVE FALLBACK · VRM ĐANG TẢI" }}
        </span>
        <span>#{{ props.avatar?.sequence ?? 0 }} · {{ props.avatar?.mode ?? "offline" }}</span>
      </div>
      <component
        :is="props.stageComponent"
        :key="props.vrmStageKey"
        :class="{ 'vrm-stage-hidden': !props.vrmReady }"
        :state="props.stageState"
        :expression="props.stageExpression"
        :viseme="props.stageViseme"
        :intensity="props.stageIntensity"
        @ready="emit('vrmReady', $event)"
        @failed="emit('vrmFailed', $event)"
        @performance="emit('vrmPerformance', $event)"
      />
      <svg
        v-if="!props.vrmReady"
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
            :rx="props.stageMouthRx"
            :ry="props.stageMouthRy"
          />
          <g class="hairpin">
            <path d="M130 196l66-39M136 218l67-37"/>
            <circle cx="130" cy="196" r="8"/>
            <circle cx="136" cy="218" r="8"/>
          </g>
        </g>
      </svg>
      <div class="stage-caption">
        <strong>{{ props.stateLabels[props.stageState] }}</strong>
        <span>
          {{ props.stageState }} · {{ props.avatar?.expression ?? "offline" }} ·
          {{ props.stageViseme }} {{ Math.round(props.stageIntensity * 100) }}% ·
          {{ props.vrmReady ? `${props.vrmFps || "—"} FPS` : "SVG fallback" }}
        </span>
      </div>
    </article>

    <aside class="operator-panel">
      <div>
        <p class="eyebrow">AVATAR RENDERER / LOCAL ONLY</p>
        <h2>Avatar Stage</h2>
        <p class="purpose">
          Xem Hina phản ứng theo state và khẩu hình từ âm thanh thật. Trang này
          chỉ nhận snapshot trình bày và intent đã định kiểu từ App; nó không có
          quyền gọi Node, filesystem, model, database hay mạng trực tiếp.
        </p>
      </div>

      <div class="status-grid">
        <div><span>State</span><strong>{{ props.stateLabels[props.stageState] }}</strong></div>
        <div><span>Biểu cảm</span><strong>{{ props.avatar?.expression ?? "—" }}</strong></div>
        <div><span>Khẩu hình</span><strong>{{ props.stageViseme }} · {{ Math.round(props.stageIntensity * 100) }}%</strong></div>
        <div><span>Nguồn cue</span><strong>{{ props.avatar?.source ?? "—" }}</strong></div>
        <div><span>Safety revision</span><strong>{{ props.safety?.state.revision ?? "—" }}</strong></div>
        <div><span>Visual Hina</span><strong>{{ props.vrmPresentationId || "Đang tải…" }}</strong></div>
      </div>

      <section class="control-card presentation-card">
        <div class="presentation-heading">
          <div>
            <p class="eyebrow">HINA VISUAL PROFILE</p>
            <h3>{{ props.vrmDisplayName || "Đang chuẩn bị Hina…" }}</h3>
          </div>
          <span class="presentation-status" :data-ready="props.vrmReady">
            {{ props.vrmReady ? "Đã có màu" : "Đang tải" }}
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
        <small v-if="props.vrmReady">
          Đã đọc {{ props.vrmTextureCount }} texture nhúng · đã phối màu
          {{ props.vrmStyledMaterialCount }} material.
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
          <div><span>FPS / mục tiêu</span><strong>{{ props.vrmPerformance ? `${props.vrmPerformance.fps} / ${props.vrmPerformance.targetFps}` : "Đang đo…" }}</strong></div>
          <div><span>Frame p95 / p99</span><strong>{{ props.vrmPerformance ? `${props.vrmPerformance.frameTimeP95Ms} / ${props.vrmPerformance.frameTimeP99Ms} ms` : "—" }}</strong></div>
          <div><span>Ước tính drop</span><strong>{{ props.vrmPerformance ? `${props.vrmPerformance.droppedFramePercent}%` : "—" }}</strong></div>
          <div><span>Mẫu / cửa sổ</span><strong>{{ props.vrmPerformance ? `${props.vrmPerformance.sampleCount} / ${props.vrmPerformance.windowMs} ms` : "—" }}</strong></div>
        </div>
      </section>

      <section class="control-card">
        <h3>Xem thử visual</h3>
        <p>
          Đây là <code>manual-preview</code>, chỉ đổi state renderer qua backend;
          không tạo hội thoại hay TTS giả.
        </p>
        <label for="previewState">State muốn xem</label>
        <select id="previewState" v-model="previewState" :disabled="props.busy">
          <option v-for="(label, value) in props.stateLabels" :key="value" :value="value">
            {{ label }} — {{ value }}
          </option>
        </select>
        <div class="button-row">
          <button class="primary" :disabled="props.busy || !props.connected" @click="emit('preview')">Xem thử</button>
          <button :disabled="props.busy || !props.connected" @click="emit('resetAvatar')">Đặt về idle</button>
        </div>
      </section>

      <section class="limitations">
        <strong>Giới hạn trung thực</strong>
        <span>
          VRM: {{ props.vrmReady ? "đã tải local, có texture và profile Hina" : "chưa tải; đang dùng SVG" }}
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
        <span v-if="props.vrmError" class="inline-error">Lỗi VRM: {{ props.vrmError }}</span>
        <button
          v-if="props.vrmError"
          id="retryVrmButton"
          type="button"
          @click="emit('retryVrm')"
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
        <pre>{{ props.snapshot }}</pre>
      </details>
    </aside>
  </section>
</template>
