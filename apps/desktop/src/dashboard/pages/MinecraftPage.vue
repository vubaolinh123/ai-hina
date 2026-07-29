<script setup lang="ts">
import { computed, ref } from "vue";

const props = defineProps<{
  status: MinecraftStatus | null;
  busy: boolean;
  notice: string;
  gameActionEnabled: boolean;
}>();

const emit = defineEmits<{
  refresh: [];
  connect: [input: {
    host: string;
    port: number;
    username: string;
    version: string | null;
  }];
  disconnect: [];
  submitGoal: [input: { text: string }];
  emergencyStop: [];
}>();

const host = ref("127.0.0.1");
const port = ref(25565);
const username = ref("Hina");
const version = ref("");
const goalText = ref("");

const online = computed(() => props.status?.phase === "online");
const worldStateFresh = computed(
  () => props.status?.worldFreshness?.state === "fresh",
);
const canConnect = computed(
  () =>
    !props.busy
    && !props.status?.emergencyStopped
    && (props.status === null || props.status.phase === "disconnected"),
);
const canRunGoal = computed(
  () =>
    !props.busy
    && props.gameActionEnabled
    && online.value
    && worldStateFresh.value
    && !props.status?.emergencyStopped
    && goalText.value.trim().length > 0,
);
const currentPosition = computed(
  () => props.status?.world?.player?.position ?? null,
);
const inventoryEntries = computed(
  () => props.status?.world?.inventory ?? [],
);
const nearbyEntities = computed(
  () => props.status?.world?.nearbyEntities ?? [],
);
const goalAvailabilityMessage = computed(() => {
  if (!props.gameActionEnabled) {
    return "Quyền hành động Minecraft đang tắt. Bật nó ở Runtime & Safety trước khi giao mục tiêu.";
  }
  if (!online.value) {
    return "Kết nối Hina vào một LAN world hoặc server riêng trước khi giao mục tiêu.";
  }
  if (props.status?.emergencyStopped) {
    return "Minecraft đang bị dừng khẩn cấp; hãy khởi động lại Desktop trước khi kết nối và giao mục tiêu mới.";
  }
  if (!worldStateFresh.value) {
    return "Hina đang chờ physics tick mới từ game để không hành động dựa trên trạng thái cũ.";
  }
  return "Sẵn sàng: Hina sẽ phân tích câu lệnh, chọn đúng goal tĩnh đã duyệt, thực hiện một lần và hậu kiểm trong game.";
});

function requestConnect(): void {
  emit("connect", {
    host: host.value.trim(),
    port: Number(port.value),
    username: username.value.trim(),
    version: version.value.trim() || null,
  });
}

function submitGoal(): void {
  const text = goalText.value.trim();
  if (!text) return;
  emit("submitGoal", { text });
}

function formatNumber(value: number): string {
  return Number.isFinite(value) ? value.toFixed(2) : "—";
}
</script>

<template>
  <main class="minecraft-page">
    <header class="page-heading">
      <div>
        <p class="eyebrow">M09 / MINECRAFT AGENT</p>
        <h1>Giao mục tiêu Minecraft cho Hina</h1>
        <p>
          Bạn chỉ cần nói việc muốn làm. Hina sẽ phân tích ý định, chọn một goal an toàn
          từ allowlist, rồi controller Minecraft tự kiểm tra điều kiện và kết quả trong game.
          Không còn nhập yaw, tọa độ hoặc bấm từng bước di chuyển.
        </p>
      </div>
      <button type="button" :disabled="props.busy" @click="emit('refresh')">
        Đọc lại trạng thái
      </button>
    </header>

    <p v-if="props.notice" class="minecraft-notice" role="status">
      {{ props.notice }}
    </p>

    <section class="minecraft-grid">
      <article class="minecraft-card minecraft-card--status">
        <p class="eyebrow">TRẠNG THÁI THỰC</p>
        <h2>
          {{
            props.status === null
              ? "Dịch vụ chưa phản hồi"
              : props.status.phase === "online"
                ? "Đã vào server"
                : props.status.phase === "connecting"
                  ? "Đang kết nối"
                  : props.status.emergencyStopped
                    ? "Đã dừng khẩn cấp"
                    : "Chưa kết nối game"
          }}
        </h2>
        <dl class="minecraft-facts">
          <div>
            <dt>Đích kết nối</dt>
            <dd>
              {{
                props.status?.target
                  ? `${props.status.target.host}:${props.status.target.port}`
                  : "Chưa có"
              }}
            </dd>
          </div>
          <div>
            <dt>Tên nhân vật</dt>
            <dd>{{ props.status?.target?.username ?? "Hina" }}</dd>
          </div>
          <div>
            <dt>Quyền hành động</dt>
            <dd>{{ props.gameActionEnabled ? "Đã bật" : "Đang tắt" }}</dd>
          </div>
          <div>
            <dt>Dừng khẩn cấp</dt>
            <dd>{{ props.status?.emergencyStopped ? "Đang khóa" : "Sẵn sàng" }}</dd>
          </div>
          <div>
            <dt>Độ tươi trạng thái game</dt>
            <dd>
              {{
                props.status?.worldFreshness?.state === "fresh"
                  ? `Mới · ${props.status.worldFreshness.ageMs ?? 0} ms`
                  : props.status?.worldFreshness?.state === "stale"
                    ? `Đã cũ · ${props.status.worldFreshness.ageMs ?? "?"} ms`
                    : online
                      ? "Chưa nhận physics tick"
                      : "Chưa có"
              }}
            </dd>
          </div>
          <div>
            <dt>Lần cập nhật</dt>
            <dd>{{ props.status?.capturedAt ?? "—" }}</dd>
          </div>
        </dl>
        <p v-if="props.status?.lastError" class="minecraft-error">
          {{ props.status.lastError.code }}: {{ props.status.lastError.message }}
        </p>
      </article>

      <article class="minecraft-card">
        <p class="eyebrow">KẾT NỐI DO CHỦ MÁY QUYẾT ĐỊNH</p>
        <h2>Server thử nghiệm</h2>
        <p class="minecraft-help">
          Chỉ nhập <strong>localhost</strong> hoặc IP riêng trong LAN. Nút này dùng tài khoản
          offline để thử nghiệm; không gửi mật khẩu hay token game.
        </p>
        <p class="minecraft-help">
          <strong>Minecraft ở màn hình chính chưa phải là server.</strong> Nếu chơi một mình,
          vào world rồi chọn <strong>Esc → Open to LAN → Start LAN World</strong>, sau đó nhập
          đúng cổng vừa hiện trong chat. Cổng 25565 thường chỉ là dedicated server tự chạy.
        </p>
        <div class="minecraft-form-grid">
          <label>
            IP server
            <input v-model="host" :disabled="props.busy || online" />
          </label>
          <label>
            Port
            <input
              v-model.number="port"
              type="number"
              min="1"
              max="65535"
              :disabled="props.busy || online"
            />
          </label>
          <label>
            Tên Hina trong game
            <input
              v-model="username"
              maxlength="16"
              :disabled="props.busy || online"
            />
          </label>
          <label>
            Phiên bản (để trống = tự nhận)
            <input
              v-model="version"
              placeholder="Ví dụ: 1.21.8"
              :disabled="props.busy || online"
            />
          </label>
        </div>
        <div class="minecraft-actions">
          <button type="button" :disabled="!canConnect" @click="requestConnect">
            Kết nối Hina
          </button>
          <button
            type="button"
            class="secondary"
            :disabled="props.busy || !props.status || props.status.phase === 'disconnected'"
            @click="emit('disconnect')"
          >
            Ngắt kết nối
          </button>
        </div>
      </article>

      <article class="minecraft-card minecraft-card--goal">
        <p class="eyebrow">MỤC TIÊU TỰ NHIÊN → HÀNH ĐỘNG ĐÃ KIỂM CHỨNG</p>
        <h2>Bạn muốn Hina làm gì?</h2>
        <p class="minecraft-help">
          Gõ một câu tự nhiên, ví dụ: <strong>“Hina, chặt một khúc gỗ ở gần đi.”</strong>
          Model chỉ được chọn goal trong danh sách an toàn cố định; không tạo code, lệnh,
          tọa độ hay chuỗi thao tác tự do.
        </p>
        <label class="minecraft-goal-input">
          Mục tiêu cho Hina
          <textarea
            v-model="goalText"
            maxlength="480"
            rows="4"
            :disabled="props.busy"
            placeholder="Ví dụ: Hina, chặt một khúc gỗ ở gần đi."
          />
        </label>
        <p class="minecraft-goal-state" :data-ready="canRunGoal">
          {{ goalAvailabilityMessage }}
        </p>
        <div class="minecraft-actions">
          <button type="button" :disabled="!canRunGoal" @click="submitGoal">
            Giao mục tiêu cho Hina
          </button>
        </div>
        <aside class="minecraft-scope">
          <strong>Khả năng chạy thật hiện tại</strong>
          <span>
            Hina có thể chặt đúng một khúc gỗ allowlist ở trong tầm với, một lần, rồi xác minh
            block đó đã biến mất. Chưa có tự đi tìm đường, chế rìu, trang bị rìu, lặp thu thập
            hay thử lại khi thất bại. Những phần đó sẽ được thêm sau dưới dạng state machine
            có kiểm chứng, không phải lời hứa từ model.
          </span>
        </aside>
      </article>

      <article class="minecraft-card minecraft-card--danger">
        <p class="eyebrow">AN TOÀN</p>
        <h2>Dừng khẩn cấp riêng cho Minecraft</h2>
        <p class="minecraft-help">
          Dùng khi Hina có hành vi không mong muốn. Nút này hủy goal đang chạy, nhả mọi phím
          điều khiển và ngắt socket. Sau đó phải khởi động lại Desktop mới kết nối lại được.
        </p>
        <button
          type="button"
          class="danger"
          :disabled="props.status?.emergencyStopped"
          @click="emit('emergencyStop')"
        >
          Dừng Minecraft ngay
        </button>
      </article>
    </section>

    <section class="minecraft-card minecraft-world">
      <div>
        <p class="eyebrow">WORLD STATE ĐÃ GIỚI HẠN</p>
        <h2>Hina đang thấy gì trong game?</h2>
        <p class="minecraft-help">
          Chỉ hiển thị trạng thái người chơi, vật phẩm và thực thể gần. Chat, sách, biển hiệu,
          NBT và dữ liệu plugin không được đưa vào đây hoặc tự đưa vào model.
        </p>
      </div>
      <div v-if="props.status?.world?.player" class="minecraft-world-data">
        <dl class="minecraft-facts minecraft-facts--world">
          <div>
            <dt>Máu / thức ăn</dt>
            <dd>
              {{ props.status.world.player.health }} /
              {{ props.status.world.player.food }}
            </dd>
          </div>
          <div>
            <dt>Vị trí</dt>
            <dd>
              {{ formatNumber(props.status.world.player.position.x) }},
              {{ formatNumber(props.status.world.player.position.y) }},
              {{ formatNumber(props.status.world.player.position.z) }}
            </dd>
          </div>
          <div>
            <dt>Góc nhìn</dt>
            <dd>
              yaw {{ formatNumber(props.status.world.player.yaw) }} · pitch
              {{ formatNumber(props.status.world.player.pitch) }}
            </dd>
          </div>
          <div>
            <dt>Kho đồ / thực thể gần</dt>
            <dd>
              {{ inventoryEntries.length }} ô ·
              {{ nearbyEntities.length }} thực thể
            </dd>
          </div>
        </dl>

        <section class="minecraft-world-detail" aria-labelledby="minecraft-inventory-title">
          <h3 id="minecraft-inventory-title">Túi đồ của Hina</h3>
          <p class="minecraft-help">
            Đây là các ô đồ Hina đang mang ở lần đọc mới nhất; không phải dữ liệu demo.
          </p>
          <ul v-if="inventoryEntries.length" class="minecraft-list">
            <li v-for="item in inventoryEntries" :key="item.slot">
              <strong>{{ item.displayName }}</strong>
              <span>
                Ô {{ item.slot }} · x{{ item.count }} · metadata {{ item.metadata }}
              </span>
            </li>
          </ul>
          <p v-else class="minecraft-empty">Túi đồ hiện chưa có vật phẩm.</p>
        </section>

        <section class="minecraft-world-detail" aria-labelledby="minecraft-entities-title">
          <h3 id="minecraft-entities-title">Thực thể gần Hina</h3>
          <p class="minecraft-help">
            Tên và loại thực thể đến trực tiếp từ game, chỉ để bạn quan sát. Không có nút
            biến thực thể hoặc tọa độ này thành lệnh di chuyển thủ công.
          </p>
          <ul v-if="nearbyEntities.length" class="minecraft-list">
            <li v-for="entity in nearbyEntities" :key="entity.id">
              <strong>{{ entity.name }}</strong>
              <span>
                #{{ entity.id }} · {{ entity.type }} · cách
                {{ formatNumber(entity.distance) }} block
              </span>
              <span>
                X {{ formatNumber(entity.position.x) }} · Y
                {{ formatNumber(entity.position.y) }} · Z
                {{ formatNumber(entity.position.z) }}
              </span>
            </li>
          </ul>
          <p v-else class="minecraft-empty">Chưa có thực thể nào trong snapshot gần Hina.</p>
        </section>
      </div>
      <p v-else class="minecraft-empty">
        Kết nối vào server để xem trạng thái thật. Đây không phải dữ liệu demo.
      </p>
    </section>
  </main>
</template>

<style scoped>
.minecraft-page {
  display: grid;
  gap: 24px;
  padding: 28px 32px 48px;
}

.page-heading {
  align-items: end;
  display: flex;
  gap: 24px;
  justify-content: space-between;
}

.page-heading h1,
.minecraft-card h2 {
  margin: 6px 0 10px;
}

.page-heading p,
.minecraft-help {
  color: #b8adba;
  line-height: 1.55;
  margin: 0;
  max-width: 880px;
}

.eyebrow {
  color: #ff9a7c !important;
  font-family: monospace;
  font-size: 12px;
  font-weight: 800;
  letter-spacing: 0.08em;
  margin: 0;
}

.minecraft-grid {
  display: grid;
  gap: 18px;
  grid-template-columns: repeat(2, minmax(0, 1fr));
}

.minecraft-card {
  background: #18151d;
  border: 1px solid #37303d;
  min-width: 0;
  padding: 22px;
}

.minecraft-card--status {
  border-color: #47765f;
}

.minecraft-card--goal {
  border-color: #8a6547;
}

.minecraft-card--danger {
  border-color: #754651;
}

.minecraft-notice {
  background: #26202b;
  border-left: 3px solid #ff9475;
  margin: 0;
  padding: 12px 14px;
}

.minecraft-error {
  color: #ff8895;
  overflow-wrap: anywhere;
}

.minecraft-facts {
  display: grid;
  gap: 12px;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  margin: 18px 0 0;
}

.minecraft-facts div {
  border-top: 1px solid #332d38;
  padding-top: 10px;
}

.minecraft-facts dt {
  color: #9d91a3;
  font-size: 12px;
}

.minecraft-facts dd {
  margin: 5px 0 0;
  overflow-wrap: anywhere;
}

.minecraft-form-grid {
  display: grid;
  gap: 14px;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  margin: 18px 0;
}

.minecraft-form-grid label,
.minecraft-goal-input {
  color: #c9becb;
  display: grid;
  font-size: 13px;
  gap: 7px;
}

.minecraft-form-grid input,
.minecraft-goal-input textarea {
  background: #0e0c12;
  border: 1px solid #443a49;
  color: #f8edf4;
  font: inherit;
  min-width: 0;
  padding: 11px 12px;
}

.minecraft-goal-input {
  margin-top: 18px;
}

.minecraft-goal-input textarea {
  line-height: 1.5;
  resize: vertical;
}

.minecraft-goal-state {
  border-left: 3px solid #8a6547;
  color: #c8b7aa;
  line-height: 1.5;
  margin: 14px 0;
  padding: 8px 10px;
}

.minecraft-goal-state[data-ready="true"] {
  border-color: #4eaa7c;
  color: #b9dfca;
}

.minecraft-scope {
  border-top: 1px solid #4a3d32;
  color: #b8adba;
  display: grid;
  gap: 7px;
  line-height: 1.55;
  margin-top: 18px;
  padding-top: 16px;
}

.minecraft-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
}

button {
  background: #d47b61;
  border: 1px solid #ee9b80;
  color: #170d0b;
  cursor: pointer;
  font: inherit;
  font-weight: 800;
  padding: 11px 15px;
}

button.secondary {
  background: transparent;
  border-color: #695c6e;
  color: #eee3ec;
}

button.danger {
  background: #8c394b;
  border-color: #db6e82;
  color: white;
}

button:disabled,
input:disabled,
textarea:disabled {
  cursor: not-allowed;
  opacity: 0.48;
}

.minecraft-world {
  display: grid;
  gap: 22px;
  grid-template-columns: minmax(260px, 0.8fr) minmax(320px, 1.2fr);
}

.minecraft-facts--world {
  margin: 0;
}

.minecraft-world-data {
  display: grid;
  gap: 22px;
  min-width: 0;
}

.minecraft-world-detail {
  border-top: 1px solid #332d38;
  padding-top: 18px;
}

.minecraft-world-detail h3 {
  margin: 0 0 8px;
}

.minecraft-list {
  display: grid;
  gap: 8px;
  list-style: none;
  margin: 14px 0 0;
  padding: 0;
}

.minecraft-list li {
  background: #100e14;
  border: 1px solid #332d38;
  display: grid;
  gap: 4px;
  padding: 11px 12px;
}

.minecraft-list span {
  color: #a99cab;
  font-size: 12px;
  overflow-wrap: anywhere;
}

.minecraft-list strong {
  overflow-wrap: anywhere;
}

.minecraft-empty {
  align-self: center;
  color: #9d91a3;
}

@media (max-width: 980px) {
  .minecraft-grid,
  .minecraft-world,
  .minecraft-form-grid {
    grid-template-columns: 1fr;
  }

  .page-heading {
    align-items: flex-start;
    flex-direction: column;
  }
}
</style>
