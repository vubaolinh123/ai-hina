const state = {
  socket: null,
  lastEnvelope: null,
  sessionId: localStorage.getItem("hina.console.session") || crypto.randomUUID(),
};

localStorage.setItem("hina.console.session", state.sessionId);

const elements = Object.fromEntries(
  [
    "connectionDot",
    "connectionText",
    "connectButton",
    "refreshAllButton",
    "healthValue",
    "uptimeValue",
    "buildValue",
    "protocolValue",
    "endpointValue",
    "metricCountValue",
    "metricCapacityValue",
    "messageInput",
    "streamInput",
    "sequenceInput",
    "sendEventButton",
    "resendButton",
    "invalidButton",
    "eventResult",
    "eventIdValue",
    "afterSequenceInput",
    "replayButton",
    "replayResult",
    "binaryInput",
    "binaryButton",
    "binaryResult",
    "metricsBody",
    "refreshMetricsButton",
    "errorsList",
    "refreshErrorsButton",
    "activityLog",
    "clearActivityButton",
  ].map((id) => [id, document.getElementById(id)]),
);

function addActivity(message, level = "info") {
  const item = document.createElement("li");
  item.className = "activity-entry";
  item.dataset.level = level;

  const meta = document.createElement("div");
  meta.className = "entry-meta";
  const time = document.createElement("span");
  time.textContent = new Date().toLocaleTimeString("vi-VN");
  const kind = document.createElement("span");
  kind.textContent = level.toUpperCase();
  meta.append(time, kind);

  const content = document.createElement("p");
  content.className = "entry-message";
  content.textContent = message;
  item.append(meta, content);
  elements.activityLog.prepend(item);

  while (elements.activityLog.children.length > 80) {
    elements.activityLog.lastElementChild.remove();
  }
}

async function fetchJson(path) {
  const response = await fetch(path, {
    cache: "no-store",
    headers: { Accept: "application/json" },
  });
  const body = await response.json();
  if (!response.ok) {
    throw new Error(`${body.errorCode || response.status}: ${body.message || "request failed"}`);
  }
  return body;
}

async function refreshStatus() {
  try {
    const [health, version, config] = await Promise.all([
      fetchJson("/v1/health"),
      fetchJson("/v1/version"),
      fetchJson("/v1/config"),
    ]);
    elements.healthValue.textContent = health.status;
    elements.uptimeValue.textContent = `${health.uptimeSeconds.toFixed(1)} giây uptime`;
    elements.buildValue.textContent = version.buildCommit.slice(0, 12);
    elements.buildValue.title = version.buildCommit;
    elements.protocolValue.textContent = version.realtimeProtocol;
    elements.endpointValue.textContent = `${config.host}:${config.port}`;
  } catch (error) {
    elements.healthValue.textContent = "offline";
    elements.uptimeValue.textContent = error.message;
    addActivity(`Không đọc được runtime: ${error.message}`, "error");
  }
}

function renderMetrics(metrics) {
  elements.metricCountValue.textContent = String(metrics.seriesCount);
  elements.metricCapacityValue.textContent = `tối đa ${metrics.maxSeries}`;
  elements.metricsBody.replaceChildren();
  if (metrics.series.length === 0) {
    const row = document.createElement("tr");
    const cell = document.createElement("td");
    cell.colSpan = 4;
    cell.className = "empty-cell";
    cell.textContent = "Chưa có metric.";
    row.append(cell);
    elements.metricsBody.append(row);
    return;
  }
  for (const metric of metrics.series) {
    const row = document.createElement("tr");
    const values = [
      metric.name,
      JSON.stringify(metric.labels),
      String(metric.value),
      String(metric.count),
    ];
    for (const value of values) {
      const cell = document.createElement("td");
      cell.textContent = value;
      row.append(cell);
    }
    elements.metricsBody.append(row);
  }
}

async function refreshMetrics() {
  try {
    renderMetrics(await fetchJson("/v1/metrics"));
  } catch (error) {
    addActivity(`Không đọc được metrics: ${error.message}`, "error");
  }
}

function renderErrors(result) {
  elements.errorsList.replaceChildren();
  if (result.records.length === 0) {
    const empty = document.createElement("p");
    empty.className = "empty";
    empty.textContent = "Chưa có lỗi.";
    elements.errorsList.append(empty);
    return;
  }
  for (const record of [...result.records].reverse()) {
    const entry = document.createElement("article");
    entry.className = "error-entry";

    const meta = document.createElement("div");
    meta.className = "entry-meta";
    const code = document.createElement("strong");
    code.textContent = record.errorCode || "E_UNKNOWN";
    const timestamp = document.createElement("span");
    timestamp.textContent = record.timestamp || "—";
    meta.append(code, timestamp);

    const message = document.createElement("p");
    message.className = "entry-message";
    message.textContent = `${record.component || "runtime"} / ${record.operation || "unknown"} — ${record.message || ""}`;
    entry.append(meta, message);
    elements.errorsList.append(entry);
  }
}

async function refreshErrors() {
  try {
    renderErrors(await fetchJson("/v1/errors?limit=20"));
  } catch (error) {
    addActivity(`Không đọc được error log: ${error.message}`, "error");
  }
}

async function refreshAll({ announce = true } = {}) {
  await Promise.all([refreshStatus(), refreshMetrics(), refreshErrors()]);
  if (announce) {
    addActivity("Đã làm mới control plane, metrics và error log.", "success");
  }
}

function updateConnection(connected) {
  elements.connectionDot.className = `status-dot ${connected ? "status-online" : "status-offline"}`;
  elements.connectionText.textContent = connected
    ? "WebSocket đã kết nối"
    : "WebSocket chưa kết nối";
  elements.connectButton.textContent = connected ? "Ngắt WebSocket" : "Kết nối WebSocket";
}

function connectWebSocket() {
  if (state.socket && state.socket.readyState <= WebSocket.OPEN) {
    state.socket.close(1000, "owner disconnect");
    return;
  }
  const scheme = location.protocol === "https:" ? "wss:" : "ws:";
  const socket = new WebSocket(
    `${scheme}//${location.host}/v1/realtime`,
    "hina.realtime.v1",
  );
  socket.binaryType = "arraybuffer";
  state.socket = socket;

  socket.addEventListener("open", () => {
    updateConnection(true);
    addActivity("WebSocket hina.realtime.v1 đã kết nối.", "success");
  });
  socket.addEventListener("close", (event) => {
    updateConnection(false);
    addActivity(`WebSocket đã đóng (code ${event.code}).`, event.code === 1000 ? "info" : "error");
  });
  socket.addEventListener("error", () => {
    addActivity("WebSocket gặp lỗi kết nối.", "error");
  });
  socket.addEventListener("message", (event) => {
    if (typeof event.data === "string") {
      handleTextMessage(event.data);
    } else {
      handleBinaryMessage(event.data);
    }
  });
}

function requireSocket() {
  if (!state.socket || state.socket.readyState !== WebSocket.OPEN) {
    addActivity("Hãy kết nối WebSocket trước khi gửi.", "error");
    return null;
  }
  return state.socket;
}

function buildEnvelope({ invalid = false } = {}) {
  const sequence = Number(elements.sequenceInput.value);
  const streamId = elements.streamInput.value.trim();
  if (!streamId || !Number.isSafeInteger(sequence) || sequence < 0) {
    throw new Error("Stream ID và sequence không hợp lệ.");
  }
  return {
    schemaVersion: "1.0",
    eventId: crypto.randomUUID(),
    type: invalid ? "hina.invalid.v1" : "hina.contract.echo.v1",
    scope: "turn",
    sessionId: state.sessionId,
    turnId: crypto.randomUUID(),
    correlationId: crypto.randomUUID(),
    causationId: null,
    source: "owner.dev-console",
    trustLevel: "owner",
    occurredAt: new Date().toISOString(),
    expiresAt: null,
    deadline: null,
    idempotencyKey: `console-${streamId}-${sequence}`,
    streamId,
    sequence,
    media: [],
    payload: {
      message: elements.messageInput.value.trim() || "Hina console echo",
      locale: "vi-VN",
      tags: ["owner", "dev-console"],
      metadata: {
        client: "hina-dev-console",
        sequence,
      },
    },
  };
}

function sendEvent({ invalid = false, resend = false } = {}) {
  const socket = requireSocket();
  if (!socket) return;
  try {
    const envelope = resend ? state.lastEnvelope : buildEnvelope({ invalid });
    if (!envelope) {
      throw new Error("Chưa có event để gửi lại.");
    }
    if (!invalid && !resend) {
      state.lastEnvelope = envelope;
      elements.resendButton.disabled = false;
    }
    socket.send(JSON.stringify({ kind: "event", envelope }));
    elements.eventIdValue.textContent = envelope.eventId;
    elements.eventResult.textContent = "Đang chờ runtime…";
    addActivity(
      `${resend ? "Gửi lại" : invalid ? "Gửi event lỗi" : "Gửi event"} ${envelope.eventId}`,
      "info",
    );
  } catch (error) {
    addActivity(error.message, "error");
  }
}

function handleTextMessage(raw) {
  let message;
  try {
    message = JSON.parse(raw);
  } catch {
    addActivity("Runtime trả về text không phải JSON.", "error");
    return;
  }
  if (message.kind === "event.accepted") {
    const result = message.deduplicated ? "Đã dedupe" : "Đã ghi journal";
    elements.eventResult.textContent = result;
    elements.eventIdValue.textContent = message.eventId;
    if (!message.deduplicated && state.lastEnvelope?.eventId === message.eventId) {
      elements.sequenceInput.value = String(state.lastEnvelope.sequence + 1);
    }
    addActivity(`${result}: ${message.eventId}`, "success");
  } else if (message.kind === "resume.events") {
    elements.replayResult.classList.remove("empty");
    elements.replayResult.textContent = JSON.stringify(message, null, 2);
    addActivity(`Replay nhận ${message.events.length} event từ ${message.streamId}.`, "success");
  } else if (message.status === "error") {
    elements.eventResult.textContent = message.errorCode || "Lỗi";
    addActivity(`${message.errorCode}: ${message.message}`, "error");
    setTimeout(refreshErrors, 150);
  } else {
    addActivity(`Realtime response: ${raw}`, "info");
  }
  refreshMetrics();
}

function requestReplay() {
  const socket = requireSocket();
  if (!socket) return;
  const streamId = elements.streamInput.value.trim();
  const afterSequence = Number(elements.afterSequenceInput.value);
  if (!streamId || !Number.isSafeInteger(afterSequence) || afterSequence < -1) {
    addActivity("Replay cursor không hợp lệ.", "error");
    return;
  }
  socket.send(JSON.stringify({ kind: "resume", streamId, afterSequence }));
  addActivity(`Yêu cầu replay ${streamId} sau sequence ${afterSequence}.`, "info");
}

function uuidToBytes(uuid) {
  const hex = uuid.replaceAll("-", "");
  return Uint8Array.from(hex.match(/.{2}/g), (byte) => Number.parseInt(byte, 16));
}

function sendBinary() {
  const socket = requireSocket();
  if (!socket) return;
  const payload = new TextEncoder().encode(elements.binaryInput.value);
  const mediaId = crypto.randomUUID();
  const sequence = Number(elements.sequenceInput.value);
  if (!Number.isInteger(sequence) || sequence < 0 || sequence > 0xffffffff) {
    addActivity("Binary sequence phải nằm trong uint32.", "error");
    return;
  }
  const frame = new Uint8Array(26 + payload.length);
  frame.set([0x48, 0x49, 0x4e, 0x41, 1, 1], 0);
  new DataView(frame.buffer).setUint32(6, sequence, false);
  frame.set(uuidToBytes(mediaId), 10);
  frame.set(payload, 26);
  socket.send(frame);
  elements.binaryResult.classList.remove("empty");
  elements.binaryResult.textContent = `Đã gửi ${frame.length} byte · media ${mediaId}`;
  addActivity(`Gửi binary opcode 2 (${payload.length} payload byte).`, "info");
}

function bytesToUuid(bytes) {
  const hex = Array.from(bytes, (value) => value.toString(16).padStart(2, "0")).join("");
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}

function handleBinaryMessage(buffer) {
  const frame = new Uint8Array(buffer);
  if (frame.length < 26) {
    addActivity("Binary response thiếu HINA header.", "error");
    return;
  }
  const view = new DataView(frame.buffer, frame.byteOffset, frame.byteLength);
  const magic = new TextDecoder().decode(frame.slice(0, 4));
  const version = frame[4];
  const flags = frame[5];
  const sequence = view.getUint32(6, false);
  const mediaId = bytesToUuid(frame.slice(10, 26));
  const payload = new TextDecoder().decode(frame.slice(26));
  elements.binaryResult.classList.remove("empty");
  elements.binaryResult.textContent = JSON.stringify(
    {
      magic,
      version,
      endOfStream: Boolean(flags & 1),
      sequence,
      mediaId,
      payloadBytes: frame.length - 26,
      payload,
    },
    null,
    2,
  );
  addActivity(`Nhận binary round-trip ${frame.length} byte từ runtime.`, "success");
  refreshMetrics();
}

elements.connectButton.addEventListener("click", connectWebSocket);
elements.refreshAllButton.addEventListener("click", () => refreshAll());
elements.refreshMetricsButton.addEventListener("click", refreshMetrics);
elements.refreshErrorsButton.addEventListener("click", refreshErrors);
elements.sendEventButton.addEventListener("click", () => sendEvent());
elements.resendButton.addEventListener("click", () => sendEvent({ resend: true }));
elements.invalidButton.addEventListener("click", () => sendEvent({ invalid: true }));
elements.replayButton.addEventListener("click", requestReplay);
elements.binaryButton.addEventListener("click", sendBinary);
elements.clearActivityButton.addEventListener("click", () => elements.activityLog.replaceChildren());

window.addEventListener("beforeunload", () => {
  if (state.socket?.readyState === WebSocket.OPEN) {
    state.socket.close(1000, "page unload");
  }
});

updateConnection(false);
refreshAll({ announce: false });
connectWebSocket();
setInterval(() => {
  refreshStatus();
  refreshMetrics();
}, 5000);
