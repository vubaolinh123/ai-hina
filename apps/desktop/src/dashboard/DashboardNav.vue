<script setup lang="ts">
import type { DashboardPage } from "./types";

const props = defineProps<{
  activePage: DashboardPage;
}>();

const emit = defineEmits<{
  navigate: [page: DashboardPage];
}>();

const items: ReadonlyArray<{
  page: DashboardPage;
  title: string;
  description: string;
}> = [
  { page: "overview", title: "Tổng quan", description: "Nhìn nhanh trạng thái Hina" },
  { page: "chat", title: "Chat với Hina", description: "Gửi text và nghe câu trả lời" },
  { page: "speech", title: "Mic / STT / TTS", description: "Kiểm tra thu âm và giọng thật" },
  { page: "perception", title: "Quan sát", description: "Chụp màn hình và chọn model" },
  { page: "resources", title: "Tài nguyên AI", description: "RAM, VRAM và model realtime" },
  { page: "avatar", title: "Avatar Stage", description: "Xem biểu cảm và lip-sync" },
  { page: "live2d", title: "Live2D / VTube Studio", description: "Hiyori hoặc model của bạn" },
  { page: "runtime", title: "Runtime & Safety", description: "Widget, mute và dừng khẩn cấp" },
  { page: "minecraft", title: "Minecraft", description: "Kết nối và thử kỹ năng an toàn" },
];
</script>

<template>
  <nav class="desktop-nav" aria-label="Điều hướng dashboard">
    <button
      v-for="item in items"
      :key="item.page"
      type="button"
      :class="{ active: props.activePage === item.page }"
      @click="emit('navigate', item.page)"
    >
      {{ item.title }}
      <small>{{ item.description }}</small>
    </button>
  </nav>
</template>
