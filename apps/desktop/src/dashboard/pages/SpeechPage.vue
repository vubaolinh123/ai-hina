<script setup lang="ts">
import { computed, toRefs } from "vue";

const props = defineProps<{
  speechRecording: boolean;
  speechBusy: boolean;
  speechLiveEnabled: boolean;
  speechStatus: string;
  speechTranscript: string;
  speechCorrelationId: string;
  speechRuntime: SpeechRuntimeStatus | null;
  ttsRuntime: TtsRuntimeStatus | null;
  speechTtsText: string;
  speechTtsAudioUrl: string;
}>();

const emit = defineEmits<{
  "update:speechLiveEnabled": [value: boolean];
  "update:speechTtsText": [value: string];
  refresh: [];
  startMic: [];
  stopMic: [];
  testTts: [];
}>();

const {
  speechRecording,
  speechBusy,
  speechStatus,
  speechTranscript,
  speechCorrelationId,
  speechRuntime,
  ttsRuntime,
  speechTtsAudioUrl,
} = toRefs(props);

const speechLiveEnabled = computed({
  get: () => props.speechLiveEnabled,
  set: (value: boolean) => emit("update:speechLiveEnabled", value),
});
const speechTtsText = computed({
  get: () => props.speechTtsText,
  set: (value: string) => emit("update:speechTtsText", value),
});
</script>

<template>
  <section class="dashboard-page speech-page">
    <div class="page-heading">
      <p class="eyebrow">DASHBOARD / MIC · STT · TTS</p>
      <h2>Kiểm tra từng phần của hội thoại bằng giọng nói</h2>
      <p class="purpose">
        Trang này dùng dịch vụ thật, không dùng dữ liệu giả. Phần Mic → STT thu âm trực tiếp
        và cập nhật transcript khi bạn còn đang nói. Phần TTS gửi đoạn text cho OmniVoice chạy
        GPU, chia câu dài thành các đoạn ổn định rồi phát lại WAV 24 kHz bằng giọng Hina.
      </p>
    </div>
    <div class="speech-runtime-strip" role="status">
      <strong>Backend đang chạy</strong>
      <span v-if="speechRuntime">
        {{ speechRuntime.configured.provider }} · {{ speechRuntime.configured.model }} ·
        {{ speechRuntime.provider.effectiveDevice.toUpperCase() }} /
        {{ speechRuntime.configured.computeType }}
      </span>
      <span v-else>Chưa đọc được trạng thái STT.</span>
      <span v-if="ttsRuntime">
        · TTS {{ ttsRuntime.provider.effectiveDevice.toUpperCase() }} /
        {{ ttsRuntime.provider.effectivePrecision }}
      </span>
      <button type="button" @click="emit('refresh')">Làm mới</button>
    </div>
    <div class="speech-test-grid">
      <article class="speech-test-card">
        <p class="eyebrow">MIC → LOCAL STT REALTIME</p>
        <h3>Hina nghe bạn nói</h3>
        <p>
          Dùng khi cần kiểm tra quyền microphone và độ chính xác nhận dạng tiếng Việt/tiếng Anh.
          Tên model cùng thiết bị GPU/CPU thật luôn hiện phía trên; audio chỉ nằm trong bộ nhớ của lượt hiện tại.
        </p>
        <label class="speech-live-toggle">
          <input v-model="speechLiveEnabled" type="checkbox" :disabled="speechRecording">
          Cập nhật transcript realtime khi đang nói
        </label>
        <div class="button-row">
          <button
            v-if="!speechRecording"
            id="speechStartMic"
            class="primary"
            type="button"
            :disabled="speechBusy"
            @click="emit('startMic')"
          >
            Thu mic
          </button>
          <button
            v-else
            id="speechStopMic"
            class="recording"
            type="button"
            @click="emit('stopMic')"
          >
            Dừng &amp; chốt transcript
          </button>
        </div>
        <div class="speech-result" aria-live="polite">
          <span>Kết quả transcript</span>
          <strong>{{ speechTranscript || "Chưa có transcript." }}</strong>
          <small v-if="speechCorrelationId">
            Correlation ID: <code>{{ speechCorrelationId }}</code>
          </small>
        </div>
      </article>

      <article class="speech-test-card">
        <p class="eyebrow">TEXT → OMNIVOICE VIETNAMESE GPU</p>
        <h3>Nghe thử giọng Hina</h3>
        <p>
          Dùng khi cần kiểm tra giọng và cảm xúc. Câu dài được tách theo dấu câu
          để giữ nhịp tự nhiên; hệ thống không ép tăng tốc làm mất chữ.
        </p>
        <label for="speechTtsText">Nội dung Hina sẽ nói</label>
        <textarea
          id="speechTtsText"
          v-model="speechTtsText"
          rows="5"
          maxlength="4000"
          :disabled="speechBusy || speechRecording"
        ></textarea>
        <button
          id="speechTestTts"
          class="primary"
          type="button"
          :disabled="speechBusy || speechRecording || !speechTtsText.trim()"
          @click="emit('testTts')"
        >
          Tạo &amp; phát giọng Hina
        </button>
        <audio
          v-if="speechTtsAudioUrl"
          class="speech-audio"
          :src="speechTtsAudioUrl"
          controls
        ></audio>
      </article>
    </div>
    <div class="speech-status" :data-recording="speechRecording" role="status">
      <strong>{{ speechRecording ? "● Đang nghe" : speechBusy ? "Đang xử lý" : "Trạng thái" }}</strong>
      <span>{{ speechStatus }}</span>
    </div>
    <aside class="speech-help">
      <strong>Nếu không nghe/không nhận được giọng:</strong>
      kiểm tra Windows đã cấp quyền microphone cho ứng dụng desktop, chọn đúng mic mặc định,
      nói gần mic rồi xem correlation ID hoặc dòng <code>[hina-error]</code> trong cửa sổ
      <code>pnpm start:desktop</code>.
    </aside>
  </section>
</template>
