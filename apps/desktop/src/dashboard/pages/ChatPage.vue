<script setup lang="ts">
import { computed, nextTick, ref, watch } from "vue";
import type { ChatContextUsage, ChatMessage } from "../types";

const props = defineProps<{
  input: string;
  messages: ChatMessage[];
  busy: boolean;
  turnState: AvatarState;
  error: string;
  voiceEnabled: boolean;
  safetyMuted: boolean;
  safetyAvailable: boolean;
  globalBusy: boolean;
  contextUsage: ChatContextUsage | null;
}>();

const emit = defineEmits<{
  "update:input": [value: string];
  "update:voiceEnabled": [value: boolean];
  send: [];
  cancel: [];
  toggleMute: [];
}>();

const messageList = ref<HTMLElement | null>(null);
const shouldAutoFollow = ref(true);
const inputValue = computed({
  get: () => props.input,
  set: (value: string) => emit("update:input", value),
});
const voiceValue = computed({
  get: () => props.voiceEnabled,
  set: (value: boolean) => emit("update:voiceEnabled", value),
});

const contextTitle = computed(() => {
  const usage = props.contextUsage;
  if (!usage) return "Đang đọc giới hạn context…";
  if (usage.estimatedInputTokens === null) {
    return `${usage.contextWindowTokens.toLocaleString("vi-VN")} token tối đa`;
  }
  return `~${usage.estimatedInputTokens.toLocaleString("vi-VN")} / ${usage.contextWindowTokens.toLocaleString("vi-VN")} token`;
});

const contextDetail = computed(() => {
  const usage = props.contextUsage;
  if (!usage) return "Hina sẽ hiển thị số đo sau khi control plane sẵn sàng.";
  if (usage.estimatedInputTokens === null) {
    return "Đây là cửa sổ hội thoại của model; các lượt cũ sẽ được xoay vòng khi chạm giới hạn.";
  }
  const parts = [
    `${usage.estimatedUsagePercent?.toFixed(1) ?? "?"}% ngân sách`,
    `${usage.includedMemoryTurns ?? 0} lượt gần`,
  ];
  if ((usage.includedLongTermMemories ?? 0) > 0) {
    parts.push(`${usage.includedLongTermMemories} ký ức đã duyệt`);
  }
  if ((usage.includedFreshObservations ?? 0) > 0) {
    parts.push(`${usage.includedFreshObservations} ảnh vừa chụp`);
  }
  return parts.join(" · ");
});

function updateAutoFollow(): void {
  const element = messageList.value;
  if (!element) return;
  shouldAutoFollow.value = (
    element.scrollHeight - element.scrollTop - element.clientHeight
  ) < 32;
}

function followLatestMessage(): void {
  const element = messageList.value;
  if (!element || !shouldAutoFollow.value) return;
  element.scrollTo({ top: element.scrollHeight, behavior: "smooth" });
}

watch(
  () => [props.messages.length, props.busy],
  () => void nextTick(followLatestMessage),
);
</script>

<template>
  <section class="dashboard-page chat-page">
    <div class="page-heading">
      <p class="eyebrow">DASHBOARD / CHAT</p>
      <h2>Nói chuyện với Hina bằng text và voice</h2>
      <p class="purpose">Nhập câu hỏi bằng tiếng Việt. Hina ưu tiên trò chuyện tự nhiên và phản hồi text trước, sau đó phát cùng nội dung bằng OmniVoice local khi Voice đang bật.</p>
    </div>
    <div class="chat-layout">
      <div ref="messageList" class="chat-messages" aria-live="polite" @scroll="updateAutoFollow">
        <p v-if="props.messages.length === 0" class="chat-empty">Chưa có tin nhắn. Hãy bắt đầu bằng một câu chào.</p>
        <div v-for="(message, index) in props.messages" :key="`${index}-${message.role}`" class="chat-message" :data-role="message.role">
          <span>{{ message.role === "user" ? "Bạn" : message.role === "assistant" ? "Hina" : "Hệ thống" }}</span>
          <p>{{ message.text }}</p>
        </div>
        <div
          v-if="props.busy"
          class="chat-thinking"
          role="status"
          aria-live="polite"
          data-testid="chat-thinking"
        >
          <span>Hina đang {{ props.turnState === "speaking" ? "chuẩn bị nói" : "suy nghĩ" }}…</span>
          <i aria-hidden="true"></i><i aria-hidden="true"></i><i aria-hidden="true"></i>
        </div>
      </div>
      <form class="chat-composer" @submit.prevent="emit('send')">
        <div class="chat-context-meter" role="status" aria-live="polite">
          <span>Context hội thoại của Hina</span>
          <strong>{{ contextTitle }}</strong>
          <small>{{ contextDetail }}</small>
          <small>Con số token là ước tính từ dữ liệu đã compose; không hiển thị prompt hay suy luận riêng.</small>
        </div>
        <label for="desktopChatInput">Bạn muốn nói gì với Hina?</label>
        <textarea id="desktopChatInput" v-model="inputValue" rows="4" maxlength="16384" :disabled="props.busy" placeholder="Ví dụ: Hina, hôm nay bạn thấy thế nào?"></textarea>
        <div class="chat-options">
          <label class="voice-toggle">
            <input v-model="voiceValue" type="checkbox">
            <span>Phát voice trả lời</span>
          </label>
          <span class="chat-hint">Voice vẫn tuân theo nút mute Safety.</span>
        </div>
        <div class="button-row">
          <button class="primary" type="submit" :disabled="props.busy || !props.input.trim()">Gửi cho Hina</button>
          <button type="button" :disabled="!props.busy" @click="emit('cancel')">Dừng lượt trả lời</button>
          <button type="button" :disabled="props.globalBusy || !props.safetyAvailable" @click="emit('toggleMute')">{{ props.safetyMuted ? "Bật voice toàn hệ thống" : "Tắt voice toàn hệ thống" }}</button>
        </div>
        <p v-if="props.error" class="inline-error">{{ props.error }}</p>
      </form>
    </div>
  </section>
</template>
