<script setup lang="ts">
import { computed, ref, watch } from "vue";

const props = defineProps<{
  status: MinecraftStatus | null;
  busy: boolean;
  notice: string;
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
  look: [input: { yawRadians: number; pitchRadians: number }];
  move: [input: {
    direction: "north" | "east" | "south" | "west";
    distanceBlocks: number;
  }];
  moveTo: [input: {
    targetX: number;
    targetZ: number;
  }];
  emergencyStop: [];
}>();

const host = ref("127.0.0.1");
const port = ref(25565);
const username = ref("Hina");
const version = ref("");
const yawRadians = ref(0);
const pitchRadians = ref(0);
const moveDirection = ref<"north" | "east" | "south" | "west">("north");
const moveDistanceBlocks = ref(1);
const moveTargetX = ref(0);
const moveTargetZ = ref(0);
const moveTargetInitialized = ref(false);

const online = computed(() => props.status?.phase === "online");
const worldStateFresh = computed(
  () => props.status?.worldFreshness?.state === "fresh",
);
const canAct = computed(
  () => !props.busy && online.value && worldStateFresh.value,
);
const currentPosition = computed(
  () => props.status?.world?.player?.position ?? null,
);
const moveTargetDistance = computed(() => {
  const position = currentPosition.value;
  if (position === null) return null;
  return Math.hypot(
    Number(moveTargetX.value) - position.x,
    Number(moveTargetZ.value) - position.z,
  );
});
const moveTargetInRange = computed(
  () =>
    moveTargetDistance.value !== null &&
    moveTargetDistance.value >= 0.25 &&
    moveTargetDistance.value <= 2,
);
const canMoveTo = computed(() => canAct.value && moveTargetInRange.value);
const canConnect = computed(
  () =>
    !props.busy &&
    !props.status?.emergencyStopped &&
    (props.status === null ||
      props.status.phase === "disconnected"),
);

function requestConnect(): void {
  emit("connect", {
    host: host.value.trim(),
    port: Number(port.value),
    username: username.value.trim(),
    version: version.value.trim() || null,
  });
}

function formatNumber(value: number): string {
  return Number.isFinite(value) ? value.toFixed(2) : "—";
}

function useNearbyTarget(): void {
  const position = currentPosition.value;
  if (position === null) return;
  moveTargetX.value = Math.round((position.x + 1) * 100) / 100;
  moveTargetZ.value = Math.round(position.z * 100) / 100;
  moveTargetInitialized.value = true;
}

watch(
  currentPosition,
  (position) => {
    if (position !== null && !moveTargetInitialized.value) {
      useNearbyTarget();
    }
  },
  { immediate: true },
);
</script>

<template>
  <main class="minecraft-page">
    <header class="page-heading">
      <div>
        <p class="eyebrow">M09 / MINECRAFT AGENT</p>
        <h1>Điều khiển Minecraft có kiểm chứng</h1>
        <p>
          Trang này dùng để bạn tự kết nối Hina vào một server Minecraft local
          hoặc mạng LAN. Hiện Hina chỉ được xoay hướng nhìn và đi một bước ngắn
          do chính bạn yêu cầu; chưa tự tìm đường, phá block, đánh quái hay chạy
          lệnh do AI sinh ra.
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
            <dt>Dừng khẩn cấp</dt>
            <dd>{{ props.status?.emergencyStopped ? "Đang khóa" : "Sẵn sàng" }}</dd>
          </div>
          <div>
            <dt>Lần cập nhật</dt>
            <dd>{{ props.status?.capturedAt ?? "—" }}</dd>
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
        </dl>
        <p
          v-if="online && !worldStateFresh"
          class="minecraft-error"
          role="status"
        >
          Hina sẽ không xoay hoặc di chuyển cho tới khi nhận được trạng thái
          physics mới từ server.
        </p>
        <p v-if="props.status?.lastError" class="minecraft-error">
          {{ props.status.lastError.code }}: {{ props.status.lastError.message }}
        </p>
      </article>

      <article class="minecraft-card">
        <p class="eyebrow">KẾT NỐI DO CHỦ MÁY QUYẾT ĐỊNH</p>
        <h2>Server thử nghiệm</h2>
        <p class="minecraft-help">
          Chỉ nhập <strong>localhost</strong> hoặc IP riêng trong LAN. Nút này
          dùng tài khoản offline để thử nghiệm; không gửi mật khẩu hay token game.
        </p>
        <p class="minecraft-help">
          <strong>Minecraft ở màn hình chính chưa phải là server.</strong> Nếu chơi
          một mình, hãy vào world, nhấn <strong>Esc → Open to LAN → Start LAN World</strong>,
          rồi nhập đúng cổng game vừa hiện trong chat (thường khác 25565). Cổng
          <strong>25565</strong> thường chỉ dùng cho dedicated server tự chạy.
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

      <article class="minecraft-card">
        <p class="eyebrow">KỸ NĂNG ĐÃ ĐƯỢC DUYỆT</p>
        <h2>Xoay hướng nhìn — look.v1</h2>
        <p class="minecraft-help">
          Dùng để kiểm tra Hina có thể xoay camera tới góc yêu cầu hay không.
          Thành công chỉ được báo sau khi hệ thống đọc lại đúng góc trong game.
        </p>
        <div class="minecraft-form-grid">
          <label>
            Ngang / yaw (−3.14 đến 3.14)
            <input
              v-model.number="yawRadians"
              type="number"
              min="-3.14"
              max="3.14"
              step="0.1"
              :disabled="!canAct"
            />
          </label>
          <label>
            Dọc / pitch (−1.57 đến 1.57)
            <input
              v-model.number="pitchRadians"
              type="number"
              min="-1.57"
              max="1.57"
              step="0.1"
              :disabled="!canAct"
            />
          </label>
        </div>
        <button
          type="button"
          :disabled="!canAct"
          @click="emit('look', {
            yawRadians: Number(yawRadians),
            pitchRadians: Number(pitchRadians),
          })"
        >
          Yêu cầu Hina nhìn
        </button>
      </article>

      <article class="minecraft-card">
        <p class="eyebrow">KỸ NĂNG ĐÃ ĐƯỢC DUYỆT</p>
        <h2>Đi một bước ngắn — move.step.v1</h2>
        <p class="minecraft-help">
          Chỉ di chuyển theo bốn hướng cố định, từ 0,25 đến 2 block và không tự
          tìm đường vòng. Hina dừng ngay khi đủ khoảng cách; nếu bị chặn, lệch
          hướng hoặc không còn đứng trên đất thì hệ thống báo thất bại.
        </p>
        <div class="minecraft-form-grid">
          <label>
            Hướng
            <select
              v-model="moveDirection"
              :disabled="!canAct"
            >
              <option value="north">Bắc</option>
              <option value="east">Đông</option>
              <option value="south">Nam</option>
              <option value="west">Tây</option>
            </select>
          </label>
          <label>
            Quãng đường (0,25–2 block)
            <input
              v-model.number="moveDistanceBlocks"
              type="number"
              min="0.25"
              max="2"
              step="0.25"
              :disabled="!canAct"
            />
          </label>
        </div>
        <button
          type="button"
          :disabled="!canAct"
          @click="emit('move', {
            direction: moveDirection,
            distanceBlocks: Number(moveDistanceBlocks),
          })"
        >
          Cho Hina đi bước ngắn
        </button>
      </article>

      <article class="minecraft-card">
        <p class="eyebrow">KỸ NĂNG ĐÃ ĐƯỢC DUYỆT</p>
        <h2>Đi tới tọa độ rất gần — move.to.v1</h2>
        <p class="minecraft-help">
          Dùng khi bạn muốn Hina quay mặt rồi đi thẳng tới một điểm X/Z cách vị
          trí hiện tại từ 0,25 đến 2 block. Đây chỉ là một bước thẳng có hậu
          kiểm; Hina không tự tìm đường, né vật cản, nhảy hoặc thử lại.
        </p>
        <div class="minecraft-form-grid">
          <label>
            Tọa độ X đích
            <input
              v-model.number="moveTargetX"
              type="number"
              min="-30000000"
              max="30000000"
              step="0.05"
              :disabled="!canAct"
            />
          </label>
          <label>
            Tọa độ Z đích
            <input
              v-model.number="moveTargetZ"
              type="number"
              min="-30000000"
              max="30000000"
              step="0.05"
              :disabled="!canAct"
            />
          </label>
        </div>
        <p class="minecraft-help">
          Khoảng cách hiện tại:
          {{
            moveTargetDistance === null
              ? "chưa có vị trí"
              : `${moveTargetDistance.toFixed(3)} block`
          }}.
          {{
            moveTargetInRange
              ? "Đủ gần để thử."
              : "Hãy chọn điểm cách Hina từ 0,25 đến 2 block."
          }}
        </p>
        <div class="minecraft-actions">
          <button
            type="button"
            :disabled="!canMoveTo"
            @click="emit('moveTo', {
              targetX: Number(moveTargetX),
              targetZ: Number(moveTargetZ),
            })"
          >
            Quay và đi tới X/Z
          </button>
          <button
            type="button"
            class="secondary"
            :disabled="!canAct"
            @click="useNearbyTarget"
          >
            Gợi ý điểm cách 1 block
          </button>
        </div>
      </article>

      <article class="minecraft-card minecraft-card--danger">
        <p class="eyebrow">AN TOÀN</p>
        <h2>Dừng khẩn cấp riêng cho Minecraft</h2>
        <p class="minecraft-help">
          Dùng khi Hina có hành vi không mong muốn. Nút này hủy kỹ năng đang chạy,
          nhả mọi phím điều khiển và ngắt socket. Sau khi bấm, phải khởi động lại
          ứng dụng Desktop mới kết nối lại được.
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
          Chỉ hiển thị trạng thái người chơi, vật phẩm và thực thể gần. Chat,
          sách, biển hiệu, NBT và dữ liệu plugin không được đưa vào đây.
        </p>
      </div>
      <dl
        v-if="props.status?.world?.player"
        class="minecraft-facts minecraft-facts--world"
      >
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
            {{ props.status.world.inventory.length }} ô ·
            {{ props.status.world.nearbyEntities.length }} thực thể
          </dd>
        </div>
      </dl>
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

.minecraft-form-grid label {
  color: #c9becb;
  display: grid;
  font-size: 13px;
  gap: 7px;
}

.minecraft-form-grid input,
.minecraft-form-grid select {
  background: #0e0c12;
  border: 1px solid #443a49;
  color: #f8edf4;
  font: inherit;
  min-width: 0;
  padding: 11px 12px;
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
input:disabled {
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

.minecraft-empty {
  align-self: center;
  color: #9d91a3;
}

@media (max-width: 980px) {
  .minecraft-grid,
  .minecraft-world {
    grid-template-columns: 1fr;
  }
}
</style>
