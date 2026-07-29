<script setup lang="ts">
import { computed, toRefs } from "vue";

const props = defineProps<{
  safetyAvailable: boolean;
  perceptionFeatureEnabled: boolean;
  screenCaptureBusy: boolean;
  screenCaptureListing: ScreenCaptureSourceListing | null;
  screenCaptureSourceToken: string;
  selectedScreenCaptureSource: ScreenCaptureSource | null;
  screenCaptureMaxSide: 640 | 960 | 1280;
  screenCaptureLabel: string;
  screenCaptureAnalyzeVision: boolean;
  screenCaptureVisionQuestion: string;
  screenCaptureMessage: string;
  screenCaptureResult: DesktopPerceptionCaptureResult | null;
  chatBusy: boolean;
  visionProviderStatus: VisionProviderDashboardStatus | null;
  visionProvider: VisionProviderChoice;
  visionApiKey: string;
  selectableVisionModels: VisionModelOption[];
  visionModel: string;
  visionBusy: boolean;
  visionMessage: string;
  visionConfigurationActionLabel: string;
}>();

const emit = defineEmits<{
  "update:screenCaptureSourceToken": [value: string];
  "update:screenCaptureMaxSide": [value: 640 | 960 | 1280];
  "update:screenCaptureLabel": [value: string];
  "update:screenCaptureAnalyzeVision": [value: boolean];
  "update:screenCaptureVisionQuestion": [value: string];
  "update:visionProvider": [value: VisionProviderChoice];
  "update:visionApiKey": [value: string];
  "update:visionModel": [value: string];
  visionPreferenceTouched: [];
  togglePerceptionFeature: [];
  listScreenCaptureSources: [];
  captureSelectedScreenSource: [];
  askHinaAboutLastCapture: [];
  discoverVisionModels: [];
  applyVisionProvider: [];
  clearVisionProviderKey: [];
  refreshVisionProviderStatus: [];
}>();

const {
  safetyAvailable,
  perceptionFeatureEnabled,
  screenCaptureBusy,
  screenCaptureListing,
  selectedScreenCaptureSource,
  screenCaptureMessage,
  screenCaptureResult,
  chatBusy,
  visionProviderStatus,
  selectableVisionModels,
  visionBusy,
  visionMessage,
  visionConfigurationActionLabel,
} = toRefs(props);

const screenCaptureSourceToken = computed({
  get: () => props.screenCaptureSourceToken,
  set: (value: string) => emit("update:screenCaptureSourceToken", value),
});
const screenCaptureMaxSide = computed({
  get: () => props.screenCaptureMaxSide,
  set: (value: 640 | 960 | 1280) => emit("update:screenCaptureMaxSide", value),
});
const screenCaptureLabel = computed({
  get: () => props.screenCaptureLabel,
  set: (value: string) => emit("update:screenCaptureLabel", value),
});
const screenCaptureAnalyzeVision = computed({
  get: () => props.screenCaptureAnalyzeVision,
  set: (value: boolean) => emit("update:screenCaptureAnalyzeVision", value),
});
const screenCaptureVisionQuestion = computed({
  get: () => props.screenCaptureVisionQuestion,
  set: (value: string) => emit("update:screenCaptureVisionQuestion", value),
});
const visionProvider = computed({
  get: () => props.visionProvider,
  set: (value: VisionProviderChoice) => emit("update:visionProvider", value),
});
const visionApiKey = computed({
  get: () => props.visionApiKey,
  set: (value: string) => emit("update:visionApiKey", value),
});
const visionModel = computed({
  get: () => props.visionModel,
  set: (value: string) => emit("update:visionModel", value),
});

type VisionObservation = NonNullable<
  NonNullable<DesktopPerceptionCaptureResult["observation"]>["vision"]
>;

function visionAnalysisErrorCode(vision: VisionObservation): string {
  return (
    vision.providerErrorCode
    || vision.modelErrorCode
    || vision.errorCode
    || "E_PERCEPTION_VISION"
  );
}

function formatVisionConfidence(vision: VisionObservation): string {
  if (typeof vision.confidence !== "number" || !Number.isFinite(vision.confidence)) {
    return "chưa đo được";
  }
  return `${Math.round(Math.max(0, Math.min(vision.confidence, 1)) * 100)}%`;
}

function visionAbstentionReason(vision: VisionObservation): string {
  switch (vision.abstainReason) {
    case "model-explicitly-uncertain":
      return "Model tự báo rằng ảnh không đủ rõ hoặc không đủ dữ kiện.";
    case "summary-too-short":
      return "Mô tả trả về quá ngắn để dùng làm ngữ cảnh đáng tin.";
    case "summary-confidence-below-threshold":
      return "Mô tả chứa quá nhiều dấu hiệu không chắc chắn.";
    default:
      return "Kết quả chưa đạt ngưỡng an toàn để đưa vào hội thoại.";
  }
}

function formatVisionModelSize(bytes: number | null): string {
  if (bytes === null) return "Cloud / không tải vào máy";
  return `${(bytes / 1024 ** 3).toFixed(1)} GB`;
}
</script>

<template>
  <section class="dashboard-page perception-page">
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
          :disabled="screenCaptureBusy || !safetyAvailable"
          @click="emit('togglePerceptionFeature')"
        >
          {{ perceptionFeatureEnabled ? "Tắt quyền quan sát" : "Bật quyền quan sát" }}
        </button>
        <button
          class="primary"
          type="button"
          :disabled="screenCaptureBusy || !perceptionFeatureEnabled"
          @click="emit('listScreenCaptureSources')"
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
            <input
              v-model="screenCaptureAnalyzeVision"
              type="checkbox"
              :disabled="!visionProviderStatus?.runtime.available"
              @change="emit('visionPreferenceTouched')"
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
            @click="emit('captureSelectedScreenSource')"
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
                : screenCaptureResult.observation?.vision?.state === "abstained"
                  ? "Hina chưa đủ chắc chắn nên không đoán"
                  : "Hina đã nhận ảnh nhưng chưa phân tích thành công"
          }}
        </strong>
        <span>
          {{ screenCaptureResult.desktopCapture.width }}×{{ screenCaptureResult.desktopCapture.height }}
          · {{ Math.ceil(screenCaptureResult.desktopCapture.bytes / 1024) }} KB
          · full frame · correlation {{ screenCaptureResult.correlationId }}
        </span>
        <p
          v-if="
            screenCaptureResult.observation?.vision?.state === 'ready'
              && screenCaptureResult.observation.vision.summary
          "
        >
          <b>Model vision:</b> {{ screenCaptureResult.observation.vision.summary }}
        </p>
        <p
          v-if="screenCaptureResult.observation?.vision?.state === 'ready'"
          class="capture-confidence"
        >
          <b>Độ chắc chắn nội bộ:</b>
          {{ formatVisionConfidence(screenCaptureResult.observation.vision) }}.
          Đây là điểm heuristic
          {{ screenCaptureResult.observation.vision.confidenceCalibrated ? "đã hiệu chuẩn" : "chưa hiệu chuẩn" }},
          không phải xác suất model nhìn đúng;
          kết quả vẫn là dữ liệu không tin cậy và chưa được dùng để tự điều khiển game.
        </p>
        <div
          v-else-if="screenCaptureResult.observation?.vision?.state === 'abstained'"
          class="capture-analysis-abstained"
        >
          <p>
            <b>Hina chủ động không đoán:</b>
            {{ visionAbstentionReason(screenCaptureResult.observation.vision) }}
          </p>
          <p v-if="screenCaptureResult.observation.vision.summary">
            <b>Bản mô tả chỉ để bạn tham khảo:</b>
            {{ screenCaptureResult.observation.vision.summary }}
          </p>
          <p>
            Điểm heuristic
            {{ screenCaptureResult.observation.vision.confidenceCalibrated ? "đã hiệu chuẩn" : "chưa hiệu chuẩn" }}:
            {{ formatVisionConfidence(screenCaptureResult.observation.vision) }}.
            Nội dung này không được đưa vào Chat, memory, TTS hay quyết định game.
          </p>
        </div>
        <p
          v-else-if="screenCaptureResult.observation?.vision?.requested"
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
        <div
          v-if="screenCaptureResult.observation?.vision?.state === 'ready'"
          class="button-row"
        >
          <button
            class="primary"
            type="button"
            :disabled="chatBusy"
            @click="emit('askHinaAboutLastCapture')"
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
          @click="emit('discoverVisionModels')"
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
            @click="emit('applyVisionProvider')"
          >
            {{ visionConfigurationActionLabel }}
          </button>
          <button
            type="button"
            :disabled="visionBusy || !visionProviderStatus?.persistence.apiKeyConfigured"
            @click="emit('clearVisionProviderKey')"
          >
            Xóa API key đã lưu
          </button>
          <button
            type="button"
            :disabled="visionBusy"
            @click="emit('refreshVisionProviderStatus')"
          >
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
      Kết quả ảnh luôn bị coi là dữ liệu không đáng tin, không tự điều khiển game.
    </aside>
  </section>
</template>
