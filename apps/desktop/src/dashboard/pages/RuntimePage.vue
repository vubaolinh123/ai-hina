<script setup lang="ts">
const props = defineProps<{
  runtime: RuntimeHealth | null;
  widgetStatus: WidgetStatus | null;
  safety: SafetyStatus | null;
  busy: boolean;
}>();

const emit = defineEmits<{
  widgetControl: [action: "show" | "hide" | "reset_position"];
  toggleMute: [];
  toggleEmergency: [];
}>();
</script>

<template>
  <section class="dashboard-page runtime-page">
    <div class="page-heading">
      <p class="eyebrow">M07 / OPERATOR RUNTIME &amp; SAFETY</p>
      <h2>Widget, âm thanh và dừng khẩn cấp</h2>
      <p class="purpose">
        Dùng trang này để quản lý cửa sổ avatar nổi và các nút an toàn của Hina.
        Các nút chỉ phát intent đã định kiểu về App/Electron main; trang không có
        quyền điều khiển desktop, model hay mạng trực tiếp.
      </p>
    </div>

    <div class="status-grid runtime-status-grid" role="status">
      <div>
        <span>Control plane</span>
        <strong>{{ props.runtime?.status === "ready" ? "Đã kết nối" : "Đang chờ" }}</strong>
      </div>
      <div>
        <span>Widget</span>
        <strong>{{ props.widgetStatus?.visible ? "Đang hiện" : "Đang ẩn" }}</strong>
      </div>
      <div>
        <span>Âm thanh Hina</span>
        <strong>{{ props.safety?.state.muted ? "Đang mute" : "Đang bật" }}</strong>
      </div>
      <div>
        <span>Safety authority</span>
        <strong>{{ props.safety?.state.emergencyStopped ? "Đang dừng khẩn cấp" : "Đang cho phép" }}</strong>
      </div>
    </div>

    <div class="runtime-control-grid">
      <section class="control-card widget-settings-card">
        <div class="presentation-heading">
          <div>
            <p class="eyebrow">DESKTOP WIDGET</p>
            <h3>Quản lý widget avatar</h3>
          </div>
          <span class="presentation-status" :data-ready="props.widgetStatus?.visible">
            {{ props.widgetStatus?.visible ? "Đang hiện" : "Đang ẩn" }}
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
              {{ props.widgetStatus ? `${props.widgetStatus.position.x}, ${props.widgetStatus.position.y}` : "Đang đọc…" }}
            </strong>
          </div>
          <div>
            <span>Luôn nổi</span>
            <strong>{{ props.widgetStatus?.alwaysOnTop ? "Có" : "Không" }}</strong>
          </div>
        </div>
        <div class="button-row">
          <button
            :disabled="props.busy || !props.widgetStatus?.visible"
            @click="emit('widgetControl', 'hide')"
          >
            Ẩn widget
          </button>
          <button
            :disabled="props.busy || props.widgetStatus?.visible"
            @click="emit('widgetControl', 'show')"
          >
            Hiện widget
          </button>
          <button
            :disabled="props.busy || !props.widgetStatus"
            @click="emit('widgetControl', 'reset_position')"
          >
            Đặt lại vị trí
          </button>
        </div>
      </section>

      <section class="control-card runtime-safety-card">
        <p class="eyebrow">AUDIO &amp; SAFETY AUTHORITY</p>
        <h3>Âm thanh và dừng khẩn cấp</h3>
        <p>
          Mute tắt toàn bộ âm thanh phản hồi của Hina. Dừng khẩn cấp chặn hành
          động mới tại safety authority, không xóa chat, memory hay cấu hình.
        </p>
        <div class="status-grid">
          <div><span>Safety revision</span><strong>{{ props.safety?.state.revision ?? "—" }}</strong></div>
          <div><span>Trạng thái</span><strong>{{ props.safety?.state.emergencyStopped ? "Đã chặn hành động mới" : "Hoạt động bình thường" }}</strong></div>
        </div>
        <div class="button-row">
          <button :disabled="props.busy || !props.safety" @click="emit('toggleMute')">
            {{ props.safety?.state.muted ? "Tắt mute" : "Bật mute" }}
          </button>
          <button
            class="danger"
            :disabled="props.busy || !props.safety"
            @click="emit('toggleEmergency')"
          >
            {{ props.safety?.state.emergencyStopped ? "Khôi phục hoạt động" : "Dừng khẩn cấp" }}
          </button>
        </div>
      </section>
    </div>

    <aside class="limitations runtime-limitations">
      <strong>Khi nào dùng các nút này?</strong>
      <span><strong>Ẩn/hiện widget:</strong> khi cần dọn màn hình hoặc đưa Hina trở lại desktop.</span>
      <span><strong>Đặt lại vị trí:</strong> khi widget bị kéo ra mép màn hình hoặc khó tìm.</span>
      <span><strong>Mute:</strong> giữ chat/text hoạt động nhưng không phát voice.</span>
      <span><strong>Dừng khẩn cấp:</strong> dùng khi muốn Hina dừng nhận hành động mới ngay; bấm lần nữa để khôi phục.</span>
    </aside>
  </section>
</template>
