<script setup lang="ts">
import type { DashboardPage } from "../types";

const props = defineProps<{
  connected: boolean;
  stateLabel: string;
  avatar: AvatarStatus | null;
  stageViseme: string;
  muted: boolean;
  vtubeStatus: VTubeStudioStatus | null;
}>();

const emit = defineEmits<{
  navigate: [page: DashboardPage];
}>();
</script>

<template>
  <section class="dashboard-page overview-page">
    <div class="page-heading">
      <p class="eyebrow">DASHBOARD / TỔNG QUAN</p>
      <h2>Chào bạn, đây là bảng điều khiển Hina</h2>
      <p class="purpose">Các thẻ dưới đây cho biết Hina đang kết nối hay không, avatar đang làm gì và bạn có thể đi tới chức năng nào tiếp theo.</p>
    </div>
    <div class="overview-grid">
      <article class="overview-card">
        <span>Kết nối control plane</span>
        <strong :data-good="props.connected">{{ props.connected ? "Đang hoạt động" : "Chưa sẵn sàng" }}</strong>
        <p>{{ props.connected ? "Desktop đang đọc dữ liệu thật từ runtime local." : "Hãy chạy start:desktop; hệ thống sẽ tự khởi control plane." }}</p>
      </article>
      <article class="overview-card">
        <span>Trạng thái Hina</span>
        <strong>{{ props.stateLabel }}</strong>
        <p>Biểu cảm {{ props.avatar?.expression ?? "chưa có" }} · viseme {{ props.stageViseme }}.</p>
      </article>
      <article class="overview-card">
        <span>Voice phản hồi</span>
        <strong>{{ props.muted ? "Đang tắt" : "Đang bật" }}</strong>
        <p>Vào Chat với Hina để gửi câu hỏi. Khi bật voice, câu trả lời sẽ phát thành WAV thật.</p>
      </article>
      <article class="overview-card">
        <span>Avatar Live2D bên ngoài</span>
        <strong :data-good="props.vtubeStatus?.authenticated">
          {{ props.vtubeStatus?.authenticated ? "VTube Studio đã nối" : "Chưa kết nối" }}
        </strong>
        <p>
          {{ props.vtubeStatus?.model.loaded
            ? `Model: ${props.vtubeStatus.model.name || props.vtubeStatus.model.vtsModelName}`
            : "VRM local vẫn là fallback; vào trang Live2D để thiết lập." }}
        </p>
      </article>
    </div>
    <div class="quick-actions">
      <button class="primary" type="button" @click="emit('navigate', 'chat')">Mở chat với Hina</button>
      <button type="button" @click="emit('navigate', 'speech')">Kiểm tra Mic / STT / TTS</button>
      <button type="button" @click="emit('navigate', 'perception')">Thiết lập đọc màn hình</button>
      <button type="button" @click="emit('navigate', 'resources')">Theo dõi RAM / VRAM</button>
      <button type="button" @click="emit('navigate', 'avatar')">Xem avatar</button>
      <button type="button" @click="emit('navigate', 'live2d')">Thiết lập Live2D / Hiyori</button>
      <button type="button" @click="emit('navigate', 'runtime')">Quản lý widget và Safety</button>
    </div>
  </section>
</template>
