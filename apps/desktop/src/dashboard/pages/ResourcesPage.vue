<script setup lang="ts">
import { toRefs } from "vue";

const props = defineProps<{
  resourceStatus: ResourceStatus | null;
  resourcePending: boolean;
  resourceError: string;
  resourceAnalysis: {
    level: string;
    title: string;
    message: string;
  };
  resourceTelemetry: ResourceTelemetry | null;
  resourceVramPercent: number;
  resourceRamPercent: number;
  resourceSampleCount: number;
  vramSparklinePoints: string;
  ramSparklinePoints: string;
  gpuSparklinePoints: string;
  resourceLoadedCount: number;
  resourceCloudCount: number;
  resourceControlBusyId: string | null;
  resourceControlMessage: string;
  resourceLargestLease: ResourceLease | null;
}>();

const emit = defineEmits<{
  refresh: [];
  controlModel: [payload: {
    model: ResourceModel;
    action: "load" | "unload";
  }];
}>();

const {
  resourceStatus,
  resourcePending,
  resourceError,
  resourceAnalysis,
  resourceTelemetry,
  resourceVramPercent,
  resourceRamPercent,
  resourceSampleCount,
  vramSparklinePoints,
  ramSparklinePoints,
  gpuSparklinePoints,
  resourceLoadedCount,
  resourceCloudCount,
  resourceControlBusyId,
  resourceControlMessage,
  resourceLargestLease,
} = toRefs(props);

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

function resourceTransitionLabel(transition: ResourceModelTransition): string {
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
</script>

<template>
  <section class="dashboard-page resources-page">
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
      <button type="button" :disabled="resourcePending" @click="emit('refresh')">
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
            <strong>{{ formatMetric(resourceTelemetry?.gpuUtilizationPercent, "%") }}</strong>
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
            <strong>{{ formatMiB(resourceStatus.processes.coreRuntime.rssMiB) }}</strong>
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
            <polyline :points="vramSparklinePoints" />
          </svg>
          <small>{{ resourceSampleCount }}/60 mẫu gần nhất</small>
        </article>
        <article class="resource-chart-card">
          <div>
            <span>Xu hướng RAM</span>
            <strong>{{ formatMiB(resourceTelemetry?.usedRamMiB) }}</strong>
          </div>
          <svg viewBox="0 0 300 80" role="img" aria-label="Biểu đồ RAM realtime">
            <path d="M0 72H300" />
            <polyline :points="ramSparklinePoints" />
          </svg>
          <small>{{ resourceSampleCount }}/60 mẫu gần nhất</small>
        </article>
        <article class="resource-chart-card">
          <div>
            <span>Mức tải GPU</span>
            <strong>{{ formatMetric(resourceTelemetry?.gpuUtilizationPercent, "%") }}</strong>
          </div>
          <svg viewBox="0 0 300 80" role="img" aria-label="Biểu đồ tải GPU realtime">
            <path d="M0 72H300" />
            <polyline :points="gpuSparklinePoints" />
          </svg>
          <small>{{ resourceSampleCount }}/60 mẫu gần nhất</small>
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
                    @click="emit('controlModel', { model, action: 'load' })"
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
                    @click="emit('controlModel', { model, action: 'unload' })"
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
</template>
