<script setup lang="ts">
const props = defineProps<{
  vtubeStatus: VTubeStudioStatus | null;
  spoutStatus: SpoutBridgeStatus | null;
  vtubeBusy: boolean;
  vtubeMessage: string;
}>();

const emit = defineEmits<{
  connect: [];
  refreshModel: [];
  disconnect: [];
  triggerHotkey: [hotkeyId: string];
  moveModel: [preset: "chat" | "screen" | "react"];
}>();
</script>

<template>
  <section class="dashboard-page live2d-page">
    <div class="page-heading">
      <p class="eyebrow">M07 / EXTERNAL LIVE2D RENDERER</p>
      <h2>Avatar Live2D qua VTube Studio</h2>
      <p class="purpose">
        Đây là cách project Neuro hiển thị nhân vật: model Live2D chạy trong
        VTube Studio, còn Hina dùng API local để xem model hiện tại, bật hotkey
        biểu cảm và đổi bố cục. Khi VTube Studio tắt, widget VRM trong suốt của
        Hina vẫn là phương án dự phòng và chat/voice không bị dừng.
      </p>
    </div>

    <div class="vtube-status-strip" :data-connected="props.vtubeStatus?.authenticated">
      <div>
        <span>Trạng thái</span>
        <strong>
          {{ props.vtubeStatus?.authenticated
            ? "Đã kết nối và xác thực"
            : props.vtubeStatus?.state === "needs_authorization"
              ? "Đang chờ bạn cấp quyền"
              : "Chưa kết nối" }}
        </strong>
      </div>
      <div>
        <span>Địa chỉ local cố định</span>
        <strong><code>{{ props.vtubeStatus?.endpoint ?? "ws://127.0.0.1:8001" }}</code></strong>
      </div>
      <div>
        <span>Renderer ưu tiên</span>
        <strong>{{ props.vtubeStatus?.model.loaded ? "Live2D đã chọn" : "VRM fallback" }}</strong>
      </div>
      <div>
        <span>Token</span>
        <strong>{{ props.vtubeStatus?.authorizationStored ? "Đã lưu cục bộ" : "Chưa có" }}</strong>
      </div>
    </div>

    <div class="live2d-grid">
      <article class="live2d-card setup-card">
        <p class="eyebrow">THIẾT LẬP MỘT LẦN</p>
        <h3>Để dùng Hiyori giống ảnh của Neuro</h3>
        <ol>
          <li>Mở VTube Studio trên Windows và vào Settings → Plugins.</li>
          <li>Bật “Allow Plugin API access”; API phải nghe ở cổng mặc định 8001.</li>
          <li>Trong VTube Studio, chọn Hiyori hoặc model Live2D bạn có quyền dùng.</li>
          <li>Chuyển sang tab Settings → biểu tượng camera → kéo xuống “Spout2 Config” và bật “Activate Spout2”.</li>
          <li>Trong phần Background chọn màu đen rồi bật “Transparent in capture” để widget không có nền.</li>
          <li>Bấm nút kết nối dưới đây rồi chọn <strong>Allow</strong> trong hộp thoại VTube Studio.</li>
        </ol>
        <div class="button-row">
          <button
            class="primary"
            type="button"
            :disabled="props.vtubeBusy || props.vtubeStatus?.authenticated"
            @click="emit('connect')"
          >
            Kết nối &amp; xin quyền
          </button>
          <button
            type="button"
            :disabled="props.vtubeBusy || !props.vtubeStatus?.authenticated"
            @click="emit('refreshModel')"
          >
            Đọc lại model
          </button>
          <button
            type="button"
            :disabled="props.vtubeBusy || !props.vtubeStatus?.connected"
            @click="emit('disconnect')"
          >
            Ngắt kết nối
          </button>
        </div>
        <p v-if="props.vtubeMessage" class="vtube-message" role="status">{{ props.vtubeMessage }}</p>
        <p v-if="props.vtubeStatus?.lastErrorCode" class="inline-error">
          {{ props.vtubeStatus.lastErrorCode }} — hãy chắc rằng VTube Studio đang mở và Plugin API đã bật.
        </p>
      </article>

      <article class="live2d-card spout-card">
        <p class="eyebrow">WIDGET / SPOUT2 FRAME BRIDGE</p>
        <h3>
          {{ props.spoutStatus?.frameReady
            ? "Widget đang nhận frame Live2D thật"
            : "Widget đang chờ frame Live2D" }}
        </h3>
        <p>
          Cầu nối này chỉ nhận sender <code>VTubeStudioSpout</code> trên loopback,
          giữ frame mới nhất trong RAM rồi đưa vào widget. Nếu bridge lỗi, VRM
          local tự hiện lại; chat, mic và kéo thả không bị khóa.
        </p>
        <div class="status-grid">
          <div>
            <span>Bridge</span>
            <strong :data-good="props.spoutStatus?.state === 'ready'">
              {{ props.spoutStatus?.state ?? "chưa đọc" }}
            </strong>
          </div>
          <div>
            <span>Sender</span>
            <strong>{{ props.spoutStatus?.sender ?? "—" }}</strong>
          </div>
          <div>
            <span>Kích thước frame</span>
            <strong>
              {{ props.spoutStatus?.width && props.spoutStatus?.height
                ? `${props.spoutStatus.width} × ${props.spoutStatus.height}`
                : "—" }}
            </strong>
          </div>
          <div>
            <span>Nền trong suốt</span>
            <strong :data-good="props.spoutStatus?.transparent">
              {{ props.spoutStatus?.transparent ? "Đã bật" : "Chưa bật" }}
            </strong>
          </div>
        </div>
        <p v-if="props.spoutStatus?.lastErrorCode" class="inline-error">
          {{ props.spoutStatus.lastErrorCode }}
        </p>
        <p v-else-if="props.spoutStatus?.frameReady && !props.spoutStatus.transparent" class="vtube-message">
          Frame đã vào widget nhưng nền vẫn opaque. Bật “Transparent in capture”
          trong VTube Studio để giữ nền desktop trong suốt.
        </p>
      </article>

      <article class="live2d-card">
        <p class="eyebrow">MODEL ĐANG CHỌN TRONG VTUBE STUDIO</p>
        <h3>{{ props.vtubeStatus?.model.name || "Chưa tải model Live2D" }}</h3>
        <div class="status-grid">
          <div><span>Model loaded</span><strong>{{ props.vtubeStatus?.model.loaded ? "Có" : "Không" }}</strong></div>
          <div><span>Model ID</span><strong>{{ props.vtubeStatus?.model.id || "—" }}</strong></div>
          <div><span>File VTS</span><strong>{{ props.vtubeStatus?.model.vtsModelName || "—" }}</strong></div>
          <div><span>Số hotkey</span><strong>{{ props.vtubeStatus?.hotkeys.length ?? 0 }}</strong></div>
        </div>
        <p>
          Hina không đọc file model từ ổ đĩa và không nhận frame video qua API.
          VTube Studio tự render Live2D; Hina chỉ gửi những lệnh đã cố định bên dưới.
        </p>
      </article>

      <article class="live2d-card hotkey-card">
        <p class="eyebrow">BIỂU CẢM / ANIMATION</p>
        <h3>Hotkey của model hiện tại</h3>
        <p>
          Dùng để thử biểu cảm hoặc animation đã được chính model cấu hình sẵn.
          Dashboard chỉ cho bấm ID vừa đọc từ model; không gửi payload tùy ý.
        </p>
        <div v-if="props.vtubeStatus?.hotkeys.length" class="hotkey-grid">
          <button
            v-for="hotkey in props.vtubeStatus.hotkeys"
            :key="hotkey.id"
            type="button"
            :disabled="props.vtubeBusy || !props.vtubeStatus.authenticated"
            :title="hotkey.type"
            @click="emit('triggerHotkey', hotkey.id)"
          >
            {{ hotkey.name }}
            <small>{{ hotkey.type }}</small>
          </button>
        </div>
        <p v-else class="empty-state">
          Chưa có hotkey. Hãy kết nối, tải model trong VTube Studio rồi bấm “Đọc lại model”.
        </p>
      </article>

      <article class="live2d-card movement-card">
        <p class="eyebrow">BỐ CỤC STREAM</p>
        <h3>Đưa nhân vật tới vị trí có sẵn</h3>
        <p>
          Ba preset chỉ thay vị trí/kích thước model đang mở. Chúng không sửa
          model, không điều khiển chuột và có thể hoàn tác trực tiếp trong VTube Studio.
        </p>
        <div class="preset-grid">
          <button
            type="button"
            :disabled="props.vtubeBusy || !props.vtubeStatus?.authenticated"
            @click="emit('moveModel', 'chat')"
          >
            Chat
            <small>Nhân vật lớn, gần trung tâm</small>
          </button>
          <button
            type="button"
            :disabled="props.vtubeBusy || !props.vtubeStatus?.authenticated"
            @click="emit('moveModel', 'screen')"
          >
            Chia sẻ màn hình
            <small>Dạt phải, dành chỗ cho nội dung</small>
          </button>
          <button
            type="button"
            :disabled="props.vtubeBusy || !props.vtubeStatus?.authenticated"
            @click="emit('moveModel', 'react')"
          >
            React
            <small>Nhỏ hơn để xem video/game</small>
          </button>
        </div>
      </article>
    </div>

    <aside class="live2d-license-notice">
      <strong>Vì sao Hiyori không nằm sẵn trong repo Hina?</strong>
      <p>
        Neuro chỉ nói rằng tác giả dùng model Hiyori mặc định; file Hiyori
        không thuộc source MIT của họ. Hiyori là sample của Live2D và chịu
        Free Material License/sample terms riêng. Vì vậy Hina kết nối tới
        model bạn tự chọn trong VTube Studio, không copy hay nhận thay điều
        khoản asset. Trang tham khảo:
        <code>live2d.com/en/learn/sample/momose-hiyori-video/</code>.
      </p>
    </aside>
  </section>
</template>
