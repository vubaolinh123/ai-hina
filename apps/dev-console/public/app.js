const state = {
  socket: null,
  lastEnvelope: null,
  safetyStatus: null,
  lastSanitation: null,
  activeChatTurnId: null,
  chatPollTimer: null,
  speechBlob: null,
  speechBlobUrl: null,
  speechTranscript: "",
  recording: null,
  ttsUtteranceId: null,
  ttsCorrelationId: null,
  ttsAbortController: null,
  ttsBlobUrl: null,
  memoryStatus: null,
  memoryCandidates: [],
  memoryRecords: [],
  avatarStatus: null,
  avatarRefreshBusy: false,
  avatarUnavailableLogged: false,
  avatarAudioContext: null,
  avatarAudioSource: null,
  avatarAnalyser: null,
  avatarAudioFrame: null,
  avatarPlaybackActive: false,
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
    "refreshModelButton",
    "modelAvailability",
    "modelProviderValue",
    "modelNameValue",
    "modelResourceValue",
    "modelCircuitValue",
    "modelStatusBox",
    "chatPersonaBadge",
    "chatMessages",
    "chatSourceSelect",
    "chatSessionValue",
    "chatInput",
    "sendChatButton",
    "cancelChatButton",
    "replayChatButton",
    "clearChatButton",
    "chatTurnResult",
    "refreshSpeechButton",
    "speechAvailability",
    "speechModelValue",
    "speechDeviceValue",
    "speechRetentionValue",
    "startRecordingButton",
    "stopRecordingButton",
    "recordingDuration",
    "audioFileInput",
    "speechPreview",
    "transcribeAudioButton",
    "useTranscriptButton",
    "speechResult",
    "speechTranscript",
    "refreshTtsButton",
    "ttsAvailability",
    "ttsVoiceValue",
    "ttsModelValue",
    "ttsOutputValue",
    "ttsInput",
    "ttsAutoSpeak",
    "synthesizeTtsButton",
    "stopTtsButton",
    "ttsResult",
    "ttsPreview",
    "refreshSafetyButton",
    "safetyBanner",
    "emergencyState",
    "muteState",
    "auditState",
    "safetyRevision",
    "capabilitySelect",
    "trustSelect",
    "consumeCheck",
    "evaluateSafetyButton",
    "safetyDecision",
    "emergencyStopButton",
    "emergencyResetButton",
    "muteButton",
    "featureFlags",
    "revocationSelect",
    "revocationButton",
    "safetyAuditList",
    "inputSourceSelect",
    "sanitationInput",
    "sanitizeButton",
    "createContextButton",
    "sanitationResult",
    "moderationSurfaceSelect",
    "moderationSourceSelect",
    "moderationInput",
    "moderationCapability",
    "moderateButton",
    "moderationResult",
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
    "pageEyebrow",
    "pageTitle",
    "pageDescription",
    "dashboardMain",
    "refreshMemoryButton",
    "exportMemoryButton",
    "rebuildMemoryButton",
    "memoryAvailability",
    "memoryPendingValue",
    "memoryActiveValue",
    "memoryIndexValue",
    "memorySourceSelect",
    "memoryKindInput",
    "memoryTopicInput",
    "memoryContentInput",
    "memoryConfidenceInput",
    "memorySensitivitySelect",
    "memoryExpiryInput",
    "proposeMemoryButton",
    "memoryCandidateResult",
    "memoryCandidateList",
    "memorySearchInput",
    "searchMemoryButton",
    "memorySearchResult",
    "memoryRecordList",
    "refreshAvatarButton",
    "avatarViewport",
    "avatarAssetBadge",
    "avatarLiveBadge",
    "avatarMouth",
    "avatarMouthGroup",
    "avatarStateCaption",
    "avatarModeCaption",
    "avatarStateValue",
    "avatarExpressionValue",
    "avatarSourceValue",
    "avatarSequenceValue",
    "avatarPreviewState",
    "previewAvatarButton",
    "resetAvatarButton",
    "avatarMuteButton",
    "avatarEmergencyButton",
    "avatarSafetyState",
    "avatarStatusBox",
  ].map((id) => [id, document.getElementById(id)]),
);

const dashboardPages = {
  overview: {
    eyebrow: "DASHBOARD",
    title: "Tổng quan hệ thống",
    description: "Xem nhanh Hina đang sẵn sàng ở mức nào và chọn khu vực cần thao tác.",
  },
  companion: {
    eyebrow: "M03 + M04 + M05",
    title: "Trò chuyện & giọng nói",
    description: "Nhắn tin với model local, chuyển WAV hoặc microphone thành chữ và phát giọng Việt đã qua kiểm duyệt.",
  },
  memory: {
    eyebrow: "M06 / OWNER CONTROL",
    title: "Ký ức dài hạn",
    description: "Đề xuất, duyệt, sửa, ghim, tìm kiếm, xuất hoặc xóa những dữ kiện Hina được phép nhớ.",
  },
  avatar: {
    eyebrow: "M07 / AVATAR STAGE",
    title: "Avatar Stage & điều khiển",
    description: "Xem state hội thoại thật, chuyển động miệng theo WAV TTS đang phát và dùng các điều khiển an toàn của operator.",
  },
  safety: {
    eyebrow: "M02 / POLICY AUTHORITY",
    title: "Trung tâm an toàn",
    description: "Quản lý quyền hạn, dừng khẩn cấp, kiểm tra đầu vào và xem lịch sử quyết định của safety backend.",
  },
  runtime: {
    eyebrow: "M01 / OPERATIONS",
    title: "Runtime & chẩn đoán",
    description: "Kiểm tra event WebSocket, journal SQLite, binary frame, metrics và log lỗi đã che thông tin nhạy cảm.",
  },
};

const capabilityLabels = {
  "tool.safe.echo": "Kiểm tra phản hồi an toàn",
  "memory.promote": "Cho phép ghi ký ức",
  "perception.observe": "Cho phép quan sát màn hình",
  "game.action": "Cho phép hành động trong game",
  "stream.output": "Cho phép gửi nội dung livestream",
  "tool.code.execute": "Chạy mã do AI tạo (luôn chặn)",
};

const featureLabels = {
  memoryPromotion: "Duyệt ký ức",
  perception: "Quan sát màn hình",
  gameAction: "Hành động trong game",
  streamOutput: "Gửi nội dung ra livestream",
};

function renderDashboardRoute() {
  const requested = location.hash.replace(/^#\/?/, "");
  const page = Object.hasOwn(dashboardPages, requested) ? requested : "overview";
  if (requested !== page) {
    history.replaceState(null, "", `#/overview`);
  }
  const copy = dashboardPages[page];
  elements.pageEyebrow.textContent = copy.eyebrow;
  elements.pageTitle.textContent = copy.title;
  elements.pageDescription.textContent = copy.description;
  document.querySelectorAll("[data-dashboard-page]").forEach((section) => {
    section.hidden = section.dataset.dashboardPage !== page;
  });
  document.querySelectorAll("[data-dashboard-nav]").forEach((link) => {
    if (link.dataset.dashboardNav === page) {
      link.setAttribute("aria-current", "page");
    } else {
      link.removeAttribute("aria-current");
    }
  });
  document.title = `${copy.title} · Hina Dev Console`;
  elements.dashboardMain.scrollTo({ top: 0, behavior: "instant" });
  elements.dashboardMain.focus({ preventScroll: true });
  if (page === "avatar") {
    refreshAvatar();
  }
}

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

async function postJson(path, body) {
  const response = await fetch(path, {
    method: "POST",
    cache: "no-store",
    headers: {
      Accept: "application/json",
      "Content-Type": "application/json",
    },
    body: JSON.stringify(body),
  });
  const result = await response.json();
  if (!response.ok) {
    throw new Error(`${result.errorCode || response.status}: ${result.message || "request failed"}`);
  }
  return result;
}

const avatarStateLabels = {
  idle: "Nghỉ",
  listening: "Đang nghe",
  thinking: "Đang suy nghĩ",
  speaking: "Đang nói",
  interrupted: "Bị ngắt",
  error: "Có lỗi",
};

function setAvatarMouth(intensity) {
  const bounded = Math.min(1, Math.max(0, Number(intensity) || 0));
  elements.avatarMouth.setAttribute("ry", String(7 + bounded * 25));
  elements.avatarMouth.setAttribute("rx", String(32 - bounded * 4));
  const line = elements.avatarMouthGroup.querySelector(".avatar-mouth-line");
  if (line) {
    line.style.opacity = String(Math.max(0, 1 - bounded * 2.2));
  }
}

function renderAvatarStatus(status) {
  state.avatarStatus = status;
  elements.avatarViewport.dataset.state = status.state;
  elements.avatarViewport.dataset.expression = status.expression;
  elements.avatarStateValue.textContent = avatarStateLabels[status.state] || status.state;
  elements.avatarExpressionValue.textContent = status.expression;
  elements.avatarSourceValue.textContent = status.source;
  elements.avatarSequenceValue.textContent = String(status.sequence);
  elements.avatarStateCaption.textContent = status.state.toUpperCase();
  elements.avatarModeCaption.textContent = `${status.mode} · ${status.expression}`;
  elements.avatarAssetBadge.textContent = status.asset.vrmLoaded
    ? "VRM LOADED"
    : "CODE-NATIVE FALLBACK · VRM CHƯA TẢI";
  elements.avatarLiveBadge.textContent =
    `${avatarStateLabels[status.state] || status.state} · cue #${status.sequence}`;
  elements.avatarStatusBox.classList.remove("empty");
  elements.avatarStatusBox.textContent = JSON.stringify(
    {
      state: status.state,
      expression: status.expression,
      source: status.source,
      mode: status.mode,
      sequence: status.sequence,
      updatedAt: status.updatedAt,
      correlationId: status.correlationId,
      turnId: status.turnId,
      utteranceId: status.utteranceId,
      asset: status.asset,
      lipSync: status.lipSync,
      rendererContract: status.rendererContract,
    },
    null,
    2,
  );
  if (!state.avatarPlaybackActive) {
    setAvatarMouth(status.state === "speaking" ? status.intensity : 0);
  }
}

async function refreshAvatar({ logFailure = false } = {}) {
  if (state.avatarRefreshBusy || document.hidden) return;
  state.avatarRefreshBusy = true;
  try {
    const status = await fetchJson("/v1/avatar/status");
    renderAvatarStatus(status);
    state.avatarUnavailableLogged = false;
  } catch (error) {
    elements.avatarLiveBadge.textContent = "Avatar runtime unavailable";
    elements.avatarStateValue.textContent = "unavailable";
    if (logFailure || !state.avatarUnavailableLogged) {
      addActivity(`Không đọc được avatar stage: ${error.message}`, "error");
      state.avatarUnavailableLogged = true;
    }
  } finally {
    state.avatarRefreshBusy = false;
  }
}

async function applyAvatarCue(cue, { announce = true } = {}) {
  try {
    const status = await postJson("/v1/avatar/cues", cue);
    renderAvatarStatus(status);
    if (announce) {
      addActivity(
        `Avatar ${status.state} · ${status.mode} · cue #${status.sequence}.`,
        "success",
      );
    }
    return status;
  } catch (error) {
    addActivity(`Avatar cue lỗi: ${error.message}`, "error");
    return null;
  }
}

async function previewAvatarState() {
  await applyAvatarCue({
    source: "owner.console",
    state: elements.avatarPreviewState.value,
    mode: "manual-preview",
  });
}

async function resetAvatarState() {
  try {
    const status = await postJson("/v1/avatar/reset", { action: "reset" });
    renderAvatarStatus(status);
    addActivity("Avatar đã về idle trung tính.", "success");
  } catch (error) {
    addActivity(`Reset avatar lỗi: ${error.message}`, "error");
  }
}

async function ensureAvatarAudioAnalyser() {
  const AudioContextClass = window.AudioContext || window.webkitAudioContext;
  if (!AudioContextClass) {
    throw new Error("trình duyệt không hỗ trợ Web Audio API");
  }
  if (!state.avatarAudioContext) {
    state.avatarAudioContext = new AudioContextClass();
    state.avatarAudioSource =
      state.avatarAudioContext.createMediaElementSource(elements.ttsPreview);
    state.avatarAnalyser = state.avatarAudioContext.createAnalyser();
    state.avatarAnalyser.fftSize = 256;
    state.avatarAnalyser.smoothingTimeConstant = 0.55;
    state.avatarAudioSource.connect(state.avatarAnalyser);
    state.avatarAnalyser.connect(state.avatarAudioContext.destination);
  }
  if (state.avatarAudioContext.state === "suspended") {
    await state.avatarAudioContext.resume();
  }
}

function startAvatarAudioAnimation() {
  if (!state.avatarAnalyser) return;
  if (state.avatarAudioFrame !== null) {
    cancelAnimationFrame(state.avatarAudioFrame);
  }
  const samples = new Uint8Array(state.avatarAnalyser.fftSize);
  const renderFrame = () => {
    if (!state.avatarPlaybackActive || elements.ttsPreview.paused) {
      state.avatarAudioFrame = null;
      setAvatarMouth(0);
      return;
    }
    state.avatarAnalyser.getByteTimeDomainData(samples);
    let energy = 0;
    for (const sample of samples) {
      const normalized = (sample - 128) / 128;
      energy += normalized * normalized;
    }
    const rms = Math.sqrt(energy / samples.length);
    setAvatarMouth(Math.min(1, rms * 5.5));
    state.avatarAudioFrame = requestAnimationFrame(renderFrame);
  };
  renderFrame();
}

async function beginAvatarPlayback() {
  state.avatarPlaybackActive = true;
  try {
    await ensureAvatarAudioAnalyser();
    startAvatarAudioAnimation();
  } catch (error) {
    addActivity(`Lip-sync amplitude không khởi động được: ${error.message}`, "error");
  }
  await applyAvatarCue(
    {
      source: "speech.output",
      state: "speaking",
      expression: "happy",
      viseme: "A",
      intensity: 0.25,
      mode: "tts-playback",
      correlationId: state.ttsCorrelationId,
      sessionId: state.sessionId,
      utteranceId: state.ttsUtteranceId,
    },
    { announce: false },
  );
}

async function finishAvatarPlayback() {
  if (!state.avatarPlaybackActive) return;
  state.avatarPlaybackActive = false;
  if (state.avatarAudioFrame !== null) {
    cancelAnimationFrame(state.avatarAudioFrame);
    state.avatarAudioFrame = null;
  }
  setAvatarMouth(0);
  await applyAvatarCue(
    {
      source: "speech.output",
      state: "idle",
      expression: "neutral",
      viseme: "sil",
      intensity: 0,
      mode: "tts-playback",
      correlationId: state.ttsCorrelationId,
      sessionId: state.sessionId,
      utteranceId: state.ttsUtteranceId,
    },
    { announce: false },
  );
}

function setSpeechBlob(blob, label) {
  if (state.speechBlobUrl) {
    URL.revokeObjectURL(state.speechBlobUrl);
  }
  state.speechBlob = blob;
  state.speechBlobUrl = URL.createObjectURL(blob);
  state.speechTranscript = "";
  elements.speechTranscript.value = "";
  elements.useTranscriptButton.disabled = true;
  elements.transcribeAudioButton.disabled = false;
  elements.speechPreview.src = state.speechBlobUrl;
  elements.speechPreview.hidden = false;
  elements.speechResult.classList.remove("empty");
  elements.speechResult.textContent = `${label}\n${blob.size} byte · audio/wav`;
}

function renderRecordingDuration(seconds, recording = false) {
  const safeSeconds = Math.max(0, seconds);
  const minutes = Math.floor(safeSeconds / 60);
  const remainder = safeSeconds - minutes * 60;
  elements.recordingDuration.textContent =
    `${String(minutes).padStart(2, "0")}:${remainder.toFixed(1).padStart(4, "0")}`;
  elements.recordingDuration.dataset.recording = String(recording);
}

async function refreshSpeech() {
  try {
    const status = await fetchJson("/v1/speech/status");
    const configured = status.configured;
    const provider = status.provider;
    elements.speechAvailability.textContent = status.available ? "ready" : "unavailable";
    elements.speechModelValue.textContent = provider.modelLoaded
      ? "loaded"
      : provider.modelCached
        ? "cached"
        : provider.downloadOnFirstUse
          ? "download on first use"
          : "not cached";
    elements.speechModelValue.title = `${configured.model}@${configured.modelRevision}`;
    elements.speechDeviceValue.textContent =
      `${provider.effectiveDevice || configured.device} / ${configured.computeType}`;
    elements.speechRetentionValue.textContent = status.retention.rawAudio ? "enabled" : "OFF";
  } catch (error) {
    elements.speechAvailability.textContent = "unavailable";
    elements.speechModelValue.textContent = "—";
    elements.speechDeviceValue.textContent = "—";
    elements.speechRetentionValue.textContent = "unknown";
    addActivity(`Không đọc được speech input: ${error.message}`, "error");
  }
}

async function refreshTts() {
  try {
    const status = await fetchJson("/v1/tts/status");
    if (!status.configured || !status.provider) {
      elements.ttsAvailability.textContent = "unavailable";
      elements.ttsVoiceValue.textContent = "—";
      elements.ttsModelValue.textContent = status.errorCode || "not configured";
      elements.ttsOutputValue.textContent = "safety policy required";
      return;
    }
    const configured = status.configured;
    const provider = status.provider;
    elements.ttsAvailability.textContent = status.available
      ? provider.modelLoaded
        ? "ready"
        : provider.modelCached
          ? "cached"
          : "download on first use"
      : provider.drainingTimedOutInference
        ? "draining timeout"
        : "unavailable";
    elements.ttsVoiceValue.textContent = configured.voice;
    elements.ttsModelValue.textContent = provider.modelLoaded
      ? "loaded"
      : provider.modelCached
        ? "cached"
        : "not cached";
    elements.ttsModelValue.title = `${configured.model}@${configured.modelRevision}`;
    elements.ttsOutputValue.textContent =
      `${status.output.sampleRateHz / 1000} kHz · mono · ${status.output.transport}`;
  } catch (error) {
    elements.ttsAvailability.textContent = "unavailable";
    elements.ttsVoiceValue.textContent = "—";
    elements.ttsModelValue.textContent = "—";
    elements.ttsOutputValue.textContent = "unknown";
    addActivity(`Không đọc được speech output: ${error.message}`, "error");
  }
}

async function stopTts({ announce = true } = {}) {
  const utteranceId = state.ttsUtteranceId;
  const correlationId = state.ttsCorrelationId;
  if (!utteranceId && !state.ttsBlobUrl) return;
  elements.ttsPreview.pause();
  elements.ttsPreview.currentTime = 0;
  state.ttsAbortController?.abort();
  state.ttsAbortController = null;
  state.ttsUtteranceId = null;
  state.ttsCorrelationId = null;
  elements.stopTtsButton.disabled = true;
  if (utteranceId) {
    try {
      const response = await fetch(`/v1/tts/utterances/${utteranceId}/cancel`, {
        method: "POST",
        cache: "no-store",
        headers: {
          Accept: "application/json",
          "Content-Type": "application/json",
          "X-Hina-Correlation-Id": correlationId || crypto.randomUUID(),
        },
        body: "{}",
      });
      if (!response.ok) {
        const result = await response.json();
        throw new Error(`${result.errorCode || response.status}: ${result.message || "cancel failed"}`);
      }
    } catch (error) {
      if (error.name !== "AbortError") {
        addActivity(`TTS cancel lỗi: ${error.message}`, "error");
      }
    }
  }
  if (announce) {
    addActivity(`Đã dừng audio TTS${correlationId ? ` · ${correlationId}` : ""}.`, "info");
  }
}

async function synthesizeTts(text = elements.ttsInput.value, autoPlay = true) {
  const normalized = String(text || "").trim();
  if (!normalized) return;
  await stopTts({ announce: false });
  if (state.ttsBlobUrl) {
    URL.revokeObjectURL(state.ttsBlobUrl);
    state.ttsBlobUrl = null;
  }
  const utteranceId = crypto.randomUUID();
  const correlationId = crypto.randomUUID();
  const controller = new AbortController();
  state.ttsUtteranceId = utteranceId;
  state.ttsCorrelationId = correlationId;
  state.ttsAbortController = controller;
  elements.synthesizeTtsButton.disabled = true;
  elements.stopTtsButton.disabled = false;
  elements.ttsResult.classList.remove("empty");
  elements.ttsResult.textContent =
    `Đang tổng hợp giọng nói thật…\nutteranceId=${utteranceId}\ncorrelationId=${correlationId}`;
  try {
    const response = await fetch("/v1/tts/synthesis", {
      method: "POST",
      cache: "no-store",
      signal: controller.signal,
      headers: {
        Accept: "audio/wav, application/json",
        "Content-Type": "application/json",
        "X-Hina-Correlation-Id": correlationId,
      },
      body: JSON.stringify({
        text: normalized,
        utteranceId,
        sessionId: state.sessionId,
        source: "owner.console",
      }),
    });
    if (!response.ok) {
      const result = await response.json();
      elements.ttsResult.textContent = JSON.stringify(result, null, 2);
      throw new Error(
        `${result.errorCode || response.status}: ${result.message || "request failed"} · ${result.correlationId || correlationId}`,
      );
    }
    const wav = await response.blob();
    if (wav.size < 44) {
      throw new Error("runtime trả về WAV không hợp lệ");
    }
    state.ttsBlobUrl = URL.createObjectURL(wav);
    elements.ttsPreview.src = state.ttsBlobUrl;
    elements.ttsPreview.hidden = false;
    const durationMs = response.headers.get("X-Hina-Duration-Milliseconds") || "—";
    const firstChunkMs = response.headers.get("X-Hina-First-Chunk-Milliseconds") || "—";
    const processingMs = response.headers.get("X-Hina-Processing-Milliseconds") || "—";
    const alignmentHeader = response.headers.get("X-Hina-Alignment") || "[]";
    let alignment = [];
    try {
      alignment = JSON.parse(alignmentHeader);
    } catch {
      alignment = [];
    }
    elements.ttsResult.textContent = JSON.stringify(
      {
        status: "synthesized",
        utteranceId,
        correlationId,
        audioBytes: wav.size,
        durationMilliseconds: Number(durationMs) || durationMs,
        firstChunkMilliseconds: Number(firstChunkMs) || firstChunkMs,
        processingMilliseconds: Number(processingMs) || processingMs,
        alignment,
        retained: false,
      },
      null,
      2,
    );
    state.ttsAbortController = null;
    if (autoPlay) {
      try {
        await elements.ttsPreview.play();
      } catch (error) {
        addActivity(`WAV đã sẵn sàng; trình duyệt chặn autoplay: ${error.message}`, "info");
      }
    }
    addActivity(`TTS đã tạo WAV thật · ${wav.size} byte · ${correlationId}.`, "success");
    await Promise.all([refreshTts(), refreshMetrics()]);
  } catch (error) {
    if (error.name !== "AbortError") {
      addActivity(`TTS lỗi: ${error.message}`, "error");
      setTimeout(refreshErrors, 150);
    }
    if (state.ttsUtteranceId === utteranceId) {
      state.ttsUtteranceId = null;
      state.ttsCorrelationId = null;
      elements.stopTtsButton.disabled = true;
    }
  } finally {
    if (state.ttsAbortController === controller) {
      state.ttsAbortController = null;
    }
    elements.synthesizeTtsButton.disabled = false;
  }
}

function mergeFloat32Chunks(chunks, sampleCount) {
  const merged = new Float32Array(sampleCount);
  let offset = 0;
  for (const chunk of chunks) {
    merged.set(chunk, offset);
    offset += chunk.length;
  }
  return merged;
}

function resampleFloat32(samples, sourceRate, targetRate = 16000) {
  if (sourceRate === targetRate) return samples;
  const targetLength = Math.max(1, Math.round(samples.length * targetRate / sourceRate));
  const result = new Float32Array(targetLength);
  const ratio = sourceRate / targetRate;
  const last = samples.length - 1;
  for (let index = 0; index < targetLength; index += 1) {
    const position = Math.min(last, index * ratio);
    const left = Math.floor(position);
    const right = Math.min(last, left + 1);
    const fraction = position - left;
    result[index] = samples[left] + (samples[right] - samples[left]) * fraction;
  }
  return result;
}

function encodePcmWav(samples, sampleRate) {
  const buffer = new ArrayBuffer(44 + samples.length * 2);
  const view = new DataView(buffer);
  const writeAscii = (offset, value) => {
    for (let index = 0; index < value.length; index += 1) {
      view.setUint8(offset + index, value.charCodeAt(index));
    }
  };
  writeAscii(0, "RIFF");
  view.setUint32(4, 36 + samples.length * 2, true);
  writeAscii(8, "WAVE");
  writeAscii(12, "fmt ");
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true);
  view.setUint16(22, 1, true);
  view.setUint32(24, sampleRate, true);
  view.setUint32(28, sampleRate * 2, true);
  view.setUint16(32, 2, true);
  view.setUint16(34, 16, true);
  writeAscii(36, "data");
  view.setUint32(40, samples.length * 2, true);
  for (let index = 0; index < samples.length; index += 1) {
    const sample = Math.max(-1, Math.min(1, samples[index]));
    view.setInt16(
      44 + index * 2,
      sample < 0 ? sample * 0x8000 : sample * 0x7fff,
      true,
    );
  }
  return new Blob([buffer], { type: "audio/wav" });
}

async function startMicrophoneRecording() {
  if (state.recording) return;
  await stopTts({ announce: false });
  if (!navigator.mediaDevices?.getUserMedia) {
    addActivity("Trình duyệt không hỗ trợ microphone capture.", "error");
    return;
  }
  try {
    const stream = await navigator.mediaDevices.getUserMedia({
      audio: {
        channelCount: 1,
        echoCancellation: true,
        noiseSuppression: true,
        autoGainControl: true,
      },
      video: false,
    });
    const AudioContextClass = window.AudioContext || window.webkitAudioContext;
    if (!AudioContextClass) {
      stream.getTracks().forEach((track) => track.stop());
      throw new Error("Web Audio API không khả dụng.");
    }
    const context = new AudioContextClass();
    const source = context.createMediaStreamSource(stream);
    const processor = context.createScriptProcessor(4096, 1, 1);
    const chunks = [];
    let sampleCount = 0;
    const startedAt = performance.now();
    processor.onaudioprocess = (event) => {
      if (!state.recording) return;
      const chunk = new Float32Array(event.inputBuffer.getChannelData(0));
      chunks.push(chunk);
      sampleCount += chunk.length;
      const seconds = sampleCount / context.sampleRate;
      renderRecordingDuration(seconds, true);
      if (seconds >= 30) {
        stopMicrophoneRecording();
      }
    };
    source.connect(processor);
    processor.connect(context.destination);
    state.recording = {
      stream,
      context,
      source,
      processor,
      chunks,
      get sampleCount() {
        return sampleCount;
      },
      startedAt,
    };
    elements.startRecordingButton.disabled = true;
    elements.stopRecordingButton.disabled = false;
    elements.transcribeAudioButton.disabled = true;
    elements.audioFileInput.disabled = true;
    renderRecordingDuration(0, true);
    addActivity("Đang thu microphone vào RAM; giới hạn 30 giây.", "info");
  } catch (error) {
    addActivity(`Không mở được microphone: ${error.message}`, "error");
  }
}

async function stopMicrophoneRecording() {
  const recording = state.recording;
  if (!recording) return;
  state.recording = null;
  recording.processor.onaudioprocess = null;
  recording.source.disconnect();
  recording.processor.disconnect();
  recording.stream.getTracks().forEach((track) => track.stop());
  await recording.context.close();
  const seconds = recording.sampleCount / recording.context.sampleRate;
  elements.startRecordingButton.disabled = false;
  elements.stopRecordingButton.disabled = true;
  elements.audioFileInput.disabled = false;
  renderRecordingDuration(seconds, false);
  if (recording.sampleCount === 0) {
    addActivity("Không thu được sample audio nào.", "error");
    return;
  }
  const captured = mergeFloat32Chunks(recording.chunks, recording.sampleCount);
  const samples = resampleFloat32(captured, recording.context.sampleRate);
  const blob = encodePcmWav(samples, 16000);
  if (blob.size > 1048576) {
    addActivity("Audio vượt 1 MiB; hãy thu đoạn ngắn hơn.", "error");
    return;
  }
  setSpeechBlob(blob, `Mic capture ${seconds.toFixed(2)} giây`);
  addActivity(`Đã thu ${seconds.toFixed(2)} giây WAV trong RAM.`, "success");
}

async function selectAudioFile() {
  const file = elements.audioFileInput.files?.[0];
  if (!file) return;
  if (file.size > 1048576) {
    elements.audioFileInput.value = "";
    addActivity("File WAV vượt giới hạn 1 MiB.", "error");
    return;
  }
  if (!file.name.toLowerCase().endsWith(".wav")) {
    elements.audioFileInput.value = "";
    addActivity("Chỉ chấp nhận file .wav.", "error");
    return;
  }
  setSpeechBlob(file, `File ${file.name}`);
  addActivity(`Đã chọn ${file.name}; audio chưa được gửi.`, "info");
}

async function transcribeAudio() {
  const blob = state.speechBlob;
  if (!blob) return;
  const correlationId = crypto.randomUUID();
  elements.transcribeAudioButton.disabled = true;
  elements.speechResult.classList.remove("empty");
  elements.speechResult.textContent =
    `Đang transcribe…\ncorrelationId=${correlationId}\nLần đầu có thể tải model đã pin.`;
  try {
    const response = await fetch("/v1/speech/transcriptions", {
      method: "POST",
      cache: "no-store",
      headers: {
        Accept: "application/json",
        "Content-Type": "audio/wav",
        "X-Hina-Correlation-Id": correlationId,
        "X-Hina-Session-Id": state.sessionId,
        "X-Hina-Source": "owner.dev-console",
      },
      body: blob,
    });
    const result = await response.json();
    elements.speechResult.textContent = JSON.stringify(result, null, 2);
    if (!response.ok) {
      throw new Error(
        `${result.errorCode || response.status}: ${result.message || "request failed"} · ${result.correlationId || correlationId}`,
      );
    }
    state.speechTranscript = result.transcript || "";
    elements.speechTranscript.value = state.speechTranscript;
    elements.useTranscriptButton.disabled = !state.speechTranscript;
    addActivity(
      result.speechDetected
        ? `STT xong trong ${result.processingMilliseconds} ms · ${result.correlationId}.`
        : `VAD xác nhận silence · ${result.correlationId}.`,
      "success",
    );
    await Promise.all([refreshSpeech(), refreshMetrics()]);
  } catch (error) {
    state.speechTranscript = "";
    elements.speechTranscript.value = "";
    elements.useTranscriptButton.disabled = true;
    addActivity(`STT lỗi: ${error.message}`, "error");
    setTimeout(refreshErrors, 150);
  } finally {
    elements.transcribeAudioButton.disabled = false;
  }
}

function useTranscriptInChat() {
  if (!state.speechTranscript) return;
  elements.chatInput.value = state.speechTranscript;
  elements.chatInput.focus();
  addActivity("Đã chép transcript vào ô chat; chưa gửi turn.", "success");
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

async function refreshModel() {
  try {
    const status = await fetchJson("/v1/model/status");
    const provider = status.provider;
    const configured = status.configured;
    const resource = status.resource;
    elements.modelAvailability.textContent = status.available ? "ready" : "unavailable";
    elements.modelProviderValue.textContent = provider.reachable
      ? `${configured.provider} online`
      : `${configured.provider} offline`;
    elements.modelNameValue.textContent = configured.model;
    elements.modelNameValue.title = configured.model;
    elements.modelResourceValue.textContent = resource.telemetry
      ? `${resource.telemetry.freeVramMiB} MiB free`
      : `${resource.errorCode || "telemetry unavailable"}`;
    elements.modelCircuitValue.textContent = status.circuit.state;
    elements.modelStatusBox.classList.remove("empty");
    elements.modelStatusBox.textContent = JSON.stringify(status, null, 2);
  } catch (error) {
    elements.modelAvailability.textContent = "unavailable";
    elements.modelStatusBox.classList.remove("empty");
    elements.modelStatusBox.textContent = error.message;
    addActivity(`Không đọc được model gateway: ${error.message}`, "error");
  }
}

function appendChatMessage(role, text, meta = "") {
  if (elements.chatMessages.querySelector(".empty")) {
    elements.chatMessages.replaceChildren();
  }
  const article = document.createElement("article");
  article.className = `chat-message chat-${role}`;
  const heading = document.createElement("div");
  heading.className = "entry-meta";
  const label = document.createElement("strong");
  label.textContent = role === "assistant" ? "Hina" : role === "user" ? "Bạn" : "Runtime";
  const detail = document.createElement("span");
  detail.textContent = meta;
  heading.append(label, detail);
  const content = document.createElement("p");
  content.className = "entry-message";
  content.textContent = text;
  article.append(heading, content);
  elements.chatMessages.append(article);
  elements.chatMessages.scrollTop = elements.chatMessages.scrollHeight;
}

function renderChatReplay(replay) {
  elements.chatMessages.replaceChildren();
  if (replay.turns.length === 0) {
    const empty = document.createElement("p");
    empty.className = "empty";
    empty.textContent = "Chưa có lượt chat hoàn tất trong phiên này.";
    elements.chatMessages.append(empty);
    return;
  }
  for (const turn of replay.turns) {
    appendChatMessage("user", turn.user, turn.turnId.slice(0, 8));
    appendChatMessage("assistant", turn.assistant, turn.completedAt);
  }
}

async function refreshChatStatus() {
  try {
    const status = await fetchJson("/v1/chat/status");
    elements.chatPersonaBadge.textContent =
      `${status.persona.name} · ${status.persona.promptVersion}`;
    elements.chatSessionValue.textContent = state.sessionId;
    elements.chatSessionValue.title = state.sessionId;
  } catch (error) {
    elements.chatPersonaBadge.textContent = "chat unavailable";
    addActivity(`Không đọc được chat status: ${error.message}`, "error");
  }
}

async function replayChat() {
  try {
    const replay = await fetchJson(`/v1/chat/sessions/${state.sessionId}`);
    renderChatReplay(replay);
    addActivity(`Replay ${replay.turnCount} turn short-term memory.`, "info");
  } catch (error) {
    addActivity(`Replay chat lỗi: ${error.message}`, "error");
  }
}

function renderTurnSnapshot(turn) {
  elements.chatTurnResult.classList.remove("empty");
  elements.chatTurnResult.textContent = JSON.stringify(turn, null, 2);
}

async function pollChatTurn(turnId) {
  try {
    const turn = await fetchJson(`/v1/chat/turns/${turnId}`);
    renderTurnSnapshot(turn);
    if (turn.outcome === "running") {
      state.chatPollTimer = window.setTimeout(() => pollChatTurn(turnId), 150);
      return;
    }
    state.activeChatTurnId = null;
    state.chatPollTimer = null;
    elements.sendChatButton.disabled = false;
    elements.cancelChatButton.disabled = true;
    if (turn.outcome === "completed") {
      await replayChat();
      if (elements.ttsAutoSpeak.checked && typeof turn.assistant === "string") {
        synthesizeTts(turn.assistant, true);
      }
      addActivity(`Chat turn ${turn.turnId} hoàn tất qua ${turn.promptVersion}.`, "success");
    } else if (turn.outcome === "interrupted") {
      appendChatMessage("runtime", "Turn đã bị interrupt; không có partial output được phát.", turn.turnId);
      addActivity(`Chat turn ${turn.turnId} interrupted.`, "info");
    } else {
      appendChatMessage(
        "runtime",
        `${turn.errorCode || "E_CHAT_FAILED"}: ${turn.errorMessage || "turn failed"}`,
        turn.correlationId,
      );
      addActivity(
        `Chat turn lỗi ${turn.errorCode || "E_CHAT_FAILED"} · correlation ${turn.correlationId}.`,
        "error",
      );
      await refreshErrors();
    }
    await Promise.all([refreshChatStatus(), refreshModel(), refreshSafety()]);
  } catch (error) {
    state.activeChatTurnId = null;
    state.chatPollTimer = null;
    elements.sendChatButton.disabled = false;
    elements.cancelChatButton.disabled = true;
    addActivity(`Không poll được chat turn: ${error.message}`, "error");
  }
}

async function startChatTurn() {
  const text = elements.chatInput.value.trim();
  if (!text || state.activeChatTurnId) return;
  try {
    const turn = await postJson("/v1/chat/turns", {
      sessionId: state.sessionId,
      source: elements.chatSourceSelect.value,
      text,
    });
    state.activeChatTurnId = turn.turnId;
    elements.sendChatButton.disabled = true;
    elements.cancelChatButton.disabled = false;
    elements.chatInput.value = "";
    appendChatMessage("user", text, "pending moderation");
    renderTurnSnapshot(turn);
    await pollChatTurn(turn.turnId);
  } catch (error) {
    addActivity(`Không start được chat turn: ${error.message}`, "error");
  }
}

async function cancelChatTurn() {
  if (!state.activeChatTurnId) return;
  try {
    const turnId = state.activeChatTurnId;
    const turn = await postJson(`/v1/chat/turns/${turnId}/cancel`, {});
    renderTurnSnapshot(turn);
    if (state.chatPollTimer !== null) {
      clearTimeout(state.chatPollTimer);
    }
    state.activeChatTurnId = null;
    state.chatPollTimer = null;
    elements.sendChatButton.disabled = false;
    elements.cancelChatButton.disabled = true;
    appendChatMessage("runtime", "Turn đã bị interrupt; partial output đã bị loại.", turnId);
    addActivity(`Đã interrupt chat turn ${turnId}.`, "info");
  } catch (error) {
    addActivity(`Interrupt chat lỗi: ${error.message}`, "error");
  }
}

async function clearChatSession() {
  if (state.activeChatTurnId) return;
  try {
    const result = await postJson(`/v1/chat/sessions/${state.sessionId}/clear`, {
      action: "clear",
    });
    renderChatReplay({ turns: [] });
    elements.chatTurnResult.classList.add("empty");
    elements.chatTurnResult.textContent = "Short-term memory đã được xóa.";
    addActivity(`Clear chat memory · existed=${result.cleared}.`, "success");
    await refreshChatStatus();
  } catch (error) {
    addActivity(`Clear chat memory lỗi: ${error.message}`, "error");
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

function replaceOptions(select, values, labels = {}) {
  const previous = select.value;
  const current = Array.from(select.options, (option) => option.value);
  if (JSON.stringify(current) === JSON.stringify(values)) return;
  select.replaceChildren();
  for (const value of values) {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = labels[value] ? `${labels[value]} — ${value}` : value;
    select.append(option);
  }
  if (values.includes(previous)) {
    select.value = previous;
  }
}

function renderSafetyStatus(status) {
  state.safetyStatus = status;
  const safety = status.state;
  elements.emergencyState.textContent = safety.emergencyStopped ? "ACTIVE" : "ready";
  elements.muteState.textContent = safety.muted ? "muted" : "audio enabled";
  elements.auditState.textContent = status.audit.verified
    ? `${status.audit.records} verified`
    : "unavailable";
  elements.safetyRevision.textContent = String(safety.revision);
  elements.safetyBanner.classList.toggle("emergency-active", safety.emergencyStopped);
  elements.emergencyStopButton.disabled = safety.emergencyStopped;
  elements.emergencyResetButton.disabled = !safety.emergencyStopped;
  elements.muteButton.textContent = safety.muted ? "Tắt mute" : "Bật mute";
  elements.avatarMuteButton.textContent = safety.muted ? "Tắt mute" : "Bật mute";
  elements.avatarEmergencyButton.textContent = safety.emergencyStopped
    ? "Khôi phục hoạt động"
    : "Dừng khẩn cấp";
  elements.avatarEmergencyButton.className = safety.emergencyStopped
    ? "button button-secondary"
    : "button button-danger";
  elements.avatarSafetyState.dataset.emergency = String(safety.emergencyStopped);
  elements.avatarSafetyState.textContent = safety.emergencyStopped
    ? `EMERGENCY STOP đang bật · ${safety.muted ? "đang mute" : "audio chưa mute"}`
    : `Safety ready · ${safety.muted ? "đang mute" : "audio đang bật"}`;

  const capabilities = status.manifest.capabilities.map((item) => item.name);
  replaceOptions(elements.capabilitySelect, capabilities, capabilityLabels);
  replaceOptions(elements.revocationSelect, capabilities, capabilityLabels);
  replaceOptions(elements.moderationCapability, capabilities, capabilityLabels);

  elements.featureFlags.replaceChildren();
  for (const [feature, enabled] of Object.entries(safety.featureFlags)) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "toggle-button";
    button.setAttribute("aria-pressed", String(enabled));
    button.dataset.feature = feature;
    button.title = `Bật hoặc tắt nhóm tính năng: ${featureLabels[feature] || feature}`;
    const label = document.createElement("span");
    label.textContent = featureLabels[feature] || feature;
    const value = document.createElement("strong");
    value.textContent = enabled ? "ON" : "OFF";
    button.append(label, value);
    button.addEventListener("click", () => {
      applySafetyControl("set_feature", { feature, enabled: !enabled });
    });
    elements.featureFlags.append(button);
  }
  updateRevocationButton();
}

function renderSafetyAudit(result) {
  elements.safetyAuditList.replaceChildren();
  if (result.records.length === 0) {
    const empty = document.createElement("p");
    empty.className = "empty";
    empty.textContent = "Chưa có audit record.";
    elements.safetyAuditList.append(empty);
    return;
  }
  for (const record of [...result.records].reverse()) {
    const entry = document.createElement("article");
    entry.className = "audit-entry";
    const meta = document.createElement("div");
    meta.className = "entry-meta";
    const kind = document.createElement("strong");
    kind.textContent = `#${record.sequence} ${record.eventType}`;
    const outcome = document.createElement("span");
    outcome.textContent = `${record.outcome} · ${record.reasonCode}`;
    meta.append(kind, outcome);
    const message = document.createElement("p");
    message.className = "entry-message";
    message.textContent = `${record.capability || record.target || "operator"} · ${record.entryHash.slice(0, 16)}…`;
    entry.append(meta, message);
    elements.safetyAuditList.append(entry);
  }
}

async function refreshSafety() {
  try {
    const [status, audit] = await Promise.all([
      fetchJson("/v1/safety/status"),
      fetchJson("/v1/safety/audit?limit=20"),
    ]);
    renderSafetyStatus(status);
    renderSafetyAudit(audit);
  } catch (error) {
    elements.emergencyState.textContent = "unavailable";
    elements.auditState.textContent = "unavailable";
    addActivity(`Không đọc được safety policy: ${error.message}`, "error");
  }
}

async function evaluateSafety() {
  try {
    const result = await postJson("/v1/safety/evaluate", {
      capability: elements.capabilitySelect.value,
      actorId: "owner.dev-console",
      trustLevel: elements.trustSelect.value,
      correlationId: crypto.randomUUID(),
      sessionId: state.sessionId,
      consume: elements.consumeCheck.checked,
    });
    elements.safetyDecision.classList.remove("empty");
    elements.safetyDecision.textContent = JSON.stringify(result, null, 2);
    addActivity(
      `Policy ${result.decision.toUpperCase()}: ${result.capability} (${result.reasonCode}).`,
      result.decision === "deny" ? "error" : "success",
    );
    await refreshSafety();
  } catch (error) {
    addActivity(`Policy request lỗi: ${error.message}`, "error");
  }
}

async function applySafetyControl(action, extra = {}) {
  try {
    const result = await postJson("/v1/safety/control", {
      action,
      actorId: "owner.dev-console",
      trustLevel: "owner",
      correlationId: crypto.randomUUID(),
      ...extra,
    });
    addActivity(
      `Safety control ${action} đã áp dụng · audit=${result.auditRecorded}.`,
      action === "emergency_stop" ? "error" : "success",
    );
    await refreshSafety();
  } catch (error) {
    addActivity(`Safety control lỗi: ${error.message}`, "error");
  }
}

async function sanitizeInput() {
  const correlationId = crypto.randomUUID();
  try {
    const result = await postJson("/v1/safety/sanitize", {
      source: elements.inputSourceSelect.value,
      text: elements.sanitationInput.value,
      correlationId,
      sessionId: state.sessionId,
    });
    state.lastSanitation = {
      result,
      correlationId,
    };
    elements.sanitationResult.classList.remove("empty");
    elements.sanitationResult.textContent = JSON.stringify(result, null, 2);
    elements.createContextButton.disabled = !result.contextEligible;
    addActivity(
      `Sanitation ${result.contextEligible ? "PASS" : "QUARANTINE"} · ${result.evidence.trustLevel}.`,
      result.contextEligible ? "success" : "error",
    );
    await refreshSafety();
  } catch (error) {
    state.lastSanitation = null;
    elements.createContextButton.disabled = true;
    addActivity(`Sanitation lỗi: ${error.message}`, "error");
  }
}

async function createContextBundle() {
  if (!state.lastSanitation) return;
  const { result, correlationId } = state.lastSanitation;
  try {
    const bundle = await postJson("/v1/safety/context", {
      items: [
        {
          text: result.sanitizedText,
          evidence: result.evidence,
        },
      ],
      correlationId,
      sessionId: state.sessionId,
    });
    elements.sanitationResult.textContent = JSON.stringify(
      {
        sanitation: result,
        contextBundle: bundle,
      },
      null,
      2,
    );
    addActivity(`ContextBundle ${bundle.bundleId} đã tạo từ evidence hợp lệ.`, "success");
    await refreshSafety();
  } catch (error) {
    addActivity(`Context boundary từ chối: ${error.message}`, "error");
  }
}

async function moderateContent() {
  const surface = elements.moderationSurfaceSelect.value;
  const capability = elements.moderationCapability.value || "tool.safe.echo";
  const toolProposal = surface === "pre_tool"
    ? {
        capability,
        intent: "console.preview",
        arguments: { message: elements.moderationInput.value },
      }
    : null;
  try {
    const result = await postJson("/v1/safety/moderate", {
      surface,
      source: elements.moderationSourceSelect.value,
      text: elements.moderationInput.value,
      actorId: "owner.dev-console",
      correlationId: crypto.randomUUID(),
      sessionId: state.sessionId,
      toolProposal,
    });
    elements.moderationResult.classList.remove("empty");
    elements.moderationResult.textContent = JSON.stringify(result, null, 2);
    addActivity(
      `Moderation ${result.decision.toUpperCase()} · ${result.surface} (${result.reasonCode}).`,
      result.decision === "allow" ? "success" : "error",
    );
    await refreshSafety();
  } catch (error) {
    addActivity(`Moderation lỗi: ${error.message}`, "error");
  }
}

function updateRevocationButton() {
  const capability = elements.revocationSelect.value;
  const revoked = state.safetyStatus?.state.revokedCapabilities.includes(capability) || false;
  elements.revocationButton.textContent = revoked ? "Khôi phục quyền" : "Thu hồi quyền";
  elements.revocationButton.dataset.revoked = String(revoked);
}

function memoryActionButton(label, className, action) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = `button ${className}`;
  button.textContent = label;
  button.addEventListener("click", action);
  return button;
}

function renderMemoryCandidates(candidates) {
  const actionable = candidates.filter(
    (candidate) => candidate.status === "pending" || candidate.status === "quarantined",
  );
  elements.memoryCandidateList.replaceChildren();
  if (!actionable.length) {
    const empty = document.createElement("p");
    empty.className = "empty";
    empty.textContent = "Không có đề xuất nào đang chờ bạn quyết định.";
    elements.memoryCandidateList.append(empty);
    return;
  }
  for (const candidate of actionable) {
    const item = document.createElement("article");
    item.className = "memory-entry";
    item.dataset.status = candidate.status;
    const title = document.createElement("h4");
    title.textContent = candidate.topic;
    const content = document.createElement("p");
    content.textContent = candidate.status === "quarantined"
      ? "Nội dung bị cách ly vì có dấu hiệu không an toàn; bản thô không được lưu."
      : candidate.content;
    const meta = document.createElement("div");
    meta.className = "memory-meta";
    meta.textContent =
      `${candidate.kind} · ${candidate.source} · ${candidate.sensitivity} · ` +
      `tin cậy ${Math.round(candidate.confidence * 100)}% · ${candidate.status}`;
    const actions = document.createElement("div");
    actions.className = "button-row";
    if (candidate.status === "pending") {
      actions.append(
        memoryActionButton("Duyệt để Hina nhớ", "button-primary", () =>
          decideMemory(candidate, "promote")),
      );
    }
    actions.append(
      memoryActionButton("Từ chối", "button-secondary", () =>
        decideMemory(candidate, "reject")),
    );
    item.append(title, content, meta, actions);
    elements.memoryCandidateList.append(item);
  }
}

function renderMemoryRecords(records) {
  elements.memoryRecordList.replaceChildren();
  if (!records.length) {
    const empty = document.createElement("p");
    empty.className = "empty";
    empty.textContent = "Chưa có ký ức nào được bạn duyệt.";
    elements.memoryRecordList.append(empty);
    return;
  }
  for (const record of records) {
    const item = document.createElement("article");
    item.className = "memory-entry";
    item.dataset.pinned = String(record.pinned);
    const title = document.createElement("h4");
    title.textContent = `${record.pinned ? "Đã ghim · " : ""}${record.topic}`;
    const content = document.createElement("p");
    content.textContent = record.content;
    const meta = document.createElement("div");
    meta.className = "memory-meta";
    meta.textContent =
      `${record.kind} · phiên bản ${record.version} · ${record.sensitivity} · ` +
      `${record.expiresAt ? `hết hạn ${new Date(record.expiresAt).toLocaleString("vi-VN")}` : "không tự hết hạn"}`;
    const actions = document.createElement("div");
    actions.className = "button-row";
    actions.append(
      memoryActionButton("Sửa nội dung", "button-secondary", () => correctMemory(record)),
      memoryActionButton(
        record.pinned ? "Bỏ ghim" : "Ghim",
        "button-secondary",
        () => setMemoryPinned(record, !record.pinned),
      ),
      memoryActionButton("Xóa có biên nhận", "button-danger", () => deleteMemory(record)),
    );
    item.append(title, content, meta, actions);
    elements.memoryRecordList.append(item);
  }
}

async function refreshMemory() {
  try {
    const [status, candidates, records] = await Promise.all([
      fetchJson("/v1/memory/status"),
      fetchJson("/v1/memory/candidates"),
      fetchJson("/v1/memory/records"),
    ]);
    state.memoryStatus = status;
    state.memoryCandidates = candidates.candidates;
    state.memoryRecords = records.records;
    elements.memoryAvailability.textContent = status.available ? "sẵn sàng" : "không sẵn sàng";
    elements.memoryPendingValue.textContent = String(status.counts["candidates.pending"] || 0);
    elements.memoryActiveValue.textContent = String(status.counts["records.active"] || 0);
    const pendingIndex = status.counts["outbox.pending"] || 0;
    elements.memoryIndexValue.textContent = pendingIndex ? `${pendingIndex} đang chờ` : "đã đồng bộ";
    renderMemoryCandidates(candidates.candidates);
    renderMemoryRecords(records.records);
  } catch (error) {
    elements.memoryAvailability.textContent = "không sẵn sàng";
    elements.memoryIndexValue.textContent = "không đọc được";
    addActivity(`Không đọc được ký ức dài hạn: ${error.message}`, "error");
  }
}

async function proposeMemory() {
  const topic = elements.memoryTopicInput.value.trim();
  const content = elements.memoryContentInput.value.trim();
  if (!topic || !content) {
    addActivity("Hãy nhập chủ đề và nội dung cần nhớ.", "error");
    return;
  }
  const expiresAt = elements.memoryExpiryInput.value
    ? new Date(elements.memoryExpiryInput.value).toISOString()
    : null;
  try {
    const result = await postJson("/v1/memory/candidates", {
      source: elements.memorySourceSelect.value,
      sessionId: state.sessionId,
      kind: elements.memoryKindInput.value.trim(),
      topic,
      content,
      confidence: Number(elements.memoryConfidenceInput.value),
      sensitivity: elements.memorySensitivitySelect.value,
      expiresAt,
      correlationId: crypto.randomUUID(),
    });
    elements.memoryCandidateResult.classList.remove("empty");
    elements.memoryCandidateResult.textContent =
      result.candidate.status === "quarantined"
        ? "Đề xuất đã bị cách ly; nội dung thô không được lưu và không thể trở thành ký ức."
        : "Đề xuất đã được lọc và đang chờ bạn bấm Duyệt.";
    elements.memoryContentInput.value = "";
    addActivity(
      `Đã tạo đề xuất ký ức “${result.candidate.topic}” (${result.candidate.status}).`,
      result.candidate.status === "pending" ? "success" : "error",
    );
    await refreshMemory();
  } catch (error) {
    elements.memoryCandidateResult.classList.remove("empty");
    elements.memoryCandidateResult.textContent = error.message;
    addActivity(`Tạo đề xuất ký ức lỗi: ${error.message}`, "error");
  }
}

async function decideMemory(candidate, action) {
  try {
    const result = await postJson(
      `/v1/memory/candidates/${candidate.candidateId}/decision`,
      { action, expectedVersion: candidate.version },
    );
    elements.memoryCandidateResult.classList.remove("empty");
    elements.memoryCandidateResult.textContent = action === "promote"
      ? `Đã duyệt. Hina có thể dùng ký ức “${result.record.topic}” trong chat của owner.`
      : `Đã từ chối đề xuất “${result.candidate.topic}”.`;
    addActivity(
      action === "promote" ? "Đã duyệt một ký ức dài hạn." : "Đã từ chối đề xuất ký ức.",
      "success",
    );
    await refreshMemory();
  } catch (error) {
    addActivity(`Không thể quyết định đề xuất: ${error.message}`, "error");
    await refreshMemory();
  }
}

async function searchMemory() {
  const query = elements.memorySearchInput.value.trim();
  if (!query) {
    addActivity("Hãy nhập nội dung cần tìm trong ký ức.", "error");
    return;
  }
  try {
    const result = await fetchJson(`/v1/memory/search?q=${encodeURIComponent(query)}`);
    elements.memorySearchResult.classList.remove("empty");
    elements.memorySearchResult.textContent = result.memories.length
      ? result.memories
          .map(
            (item, index) =>
              `${index + 1}. ${item.record.topic} — ${item.record.content} ` +
              `(độ khớp ${item.score.toFixed(3)})`,
          )
          .join("\n")
      : "Không tìm thấy ký ức đang hoạt động phù hợp.";
    addActivity(`Tìm kiếm ký ức trả về ${result.count} kết quả.`, "success");
  } catch (error) {
    elements.memorySearchResult.classList.remove("empty");
    elements.memorySearchResult.textContent = error.message;
    addActivity(`Tìm ký ức lỗi: ${error.message}`, "error");
  }
}

async function correctMemory(record) {
  const content = window.prompt(
    "Nhập nội dung đúng thay cho ký ức hiện tại. Thao tác này tạo phiên bản mới:",
    record.content,
  );
  if (content === null || !content.trim() || content.trim() === record.content) return;
  try {
    await postJson(`/v1/memory/records/${record.memoryId}/correct`, {
      content: content.trim(),
      expectedVersion: record.version,
      correlationId: crypto.randomUUID(),
    });
    addActivity(`Đã sửa ký ức “${record.topic}”.`, "success");
    await refreshMemory();
  } catch (error) {
    addActivity(`Sửa ký ức lỗi: ${error.message}`, "error");
    await refreshMemory();
  }
}

async function setMemoryPinned(record, pinned) {
  try {
    await postJson(`/v1/memory/records/${record.memoryId}/pin`, {
      pinned,
      expectedVersion: record.version,
    });
    addActivity(`${pinned ? "Đã ghim" : "Đã bỏ ghim"} ký ức “${record.topic}”.`, "success");
    await refreshMemory();
  } catch (error) {
    addActivity(`Đổi trạng thái ghim lỗi: ${error.message}`, "error");
    await refreshMemory();
  }
}

async function deleteMemory(record) {
  if (!window.confirm(
    `Xóa ký ức “${record.topic}”? Nội dung sẽ bị xóa khỏi SQLite và chỉ mục tìm kiếm.`,
  )) return;
  try {
    const result = await postJson(`/v1/memory/records/${record.memoryId}/delete`, {
      expectedVersion: record.version,
    });
    elements.memorySearchResult.classList.remove("empty");
    elements.memorySearchResult.textContent =
      `Đã xóa. Biên nhận ${result.receipt.receiptId}; ` +
      `đã đối soát: ${result.receipt.stores.join(", ")}. ` +
      "Biên nhận không tuyên bố xóa dữ liệu khỏi model weights.";
    addActivity(`Đã xóa ký ức và nhận biên nhận ${result.receipt.receiptId}.`, "success");
    await refreshMemory();
  } catch (error) {
    addActivity(`Xóa ký ức lỗi: ${error.message}`, "error");
    await refreshMemory();
  }
}

async function exportMemory() {
  try {
    const result = await fetchJson("/v1/memory/export");
    const blob = new Blob([JSON.stringify(result, null, 2)], {
      type: "application/json",
    });
    const link = document.createElement("a");
    const url = URL.createObjectURL(blob);
    link.href = url;
    link.download = `hina-memory-${new Date().toISOString().slice(0, 10)}.json`;
    link.click();
    URL.revokeObjectURL(url);
    addActivity(`Đã xuất ${result.records.length} bản ghi ký ức và audit.`, "success");
  } catch (error) {
    addActivity(`Xuất ký ức lỗi: ${error.message}`, "error");
  }
}

async function rebuildMemory() {
  if (!window.confirm(
    "Dựng lại chỉ mục tìm kiếm từ SQLite? Dữ liệu ký ức gốc không bị thay đổi.",
  )) return;
  try {
    const result = await postJson("/v1/memory/rebuild", { action: "rebuild" });
    addActivity(`Đã dựng lại chỉ mục cho ${result.recordCount} ký ức.`, "success");
    await refreshMemory();
  } catch (error) {
    addActivity(`Dựng lại chỉ mục lỗi: ${error.message}`, "error");
  }
}

async function refreshAll({ announce = true } = {}) {
  await Promise.all([
    refreshStatus(),
    refreshMetrics(),
    refreshErrors(),
    refreshSafety(),
    refreshModel(),
    refreshChatStatus(),
    refreshSpeech(),
    refreshTts(),
    refreshMemory(),
    refreshAvatar(),
  ]);
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

function cancelTtsOnPageExit() {
  const utteranceId = state.ttsUtteranceId;
  if (!utteranceId) {
    state.ttsAbortController?.abort();
    return;
  }
  const route = `/v1/tts/utterances/${utteranceId}/cancel`;
  const body = new Blob(["{}"], { type: "application/json" });
  if (!navigator.sendBeacon?.(route, body)) {
    fetch(route, {
      method: "POST",
      cache: "no-store",
      keepalive: true,
      headers: {
        Accept: "application/json",
        "Content-Type": "application/json",
      },
      body: "{}",
    }).catch(() => {});
  }
  state.ttsAbortController?.abort();
  state.ttsAbortController = null;
  state.ttsUtteranceId = null;
  state.ttsCorrelationId = null;
}

elements.connectButton.addEventListener("click", connectWebSocket);
elements.refreshAllButton.addEventListener("click", () => refreshAll());
elements.refreshSafetyButton.addEventListener("click", refreshSafety);
elements.refreshModelButton.addEventListener("click", refreshModel);
elements.refreshSpeechButton.addEventListener("click", refreshSpeech);
elements.refreshTtsButton.addEventListener("click", refreshTts);
elements.synthesizeTtsButton.addEventListener("click", () => synthesizeTts());
elements.stopTtsButton.addEventListener("click", () => stopTts());
elements.ttsPreview.addEventListener("play", () => {
  void beginAvatarPlayback();
});
elements.ttsPreview.addEventListener("pause", () => {
  void finishAvatarPlayback();
});
elements.ttsPreview.addEventListener("ended", () => {
  void finishAvatarPlayback();
  state.ttsUtteranceId = null;
  state.ttsCorrelationId = null;
  elements.stopTtsButton.disabled = true;
});
elements.startRecordingButton.addEventListener("click", startMicrophoneRecording);
elements.stopRecordingButton.addEventListener("click", stopMicrophoneRecording);
elements.audioFileInput.addEventListener("change", selectAudioFile);
elements.transcribeAudioButton.addEventListener("click", transcribeAudio);
elements.useTranscriptButton.addEventListener("click", useTranscriptInChat);
elements.sendChatButton.addEventListener("click", startChatTurn);
elements.cancelChatButton.addEventListener("click", cancelChatTurn);
elements.replayChatButton.addEventListener("click", replayChat);
elements.clearChatButton.addEventListener("click", clearChatSession);
elements.chatInput.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    startChatTurn();
  }
});
elements.evaluateSafetyButton.addEventListener("click", evaluateSafety);
elements.emergencyStopButton.addEventListener("click", () => applySafetyControl("emergency_stop"));
elements.emergencyResetButton.addEventListener("click", () => applySafetyControl("emergency_reset"));
elements.muteButton.addEventListener("click", () => {
  const enabled = !(state.safetyStatus?.state.muted || false);
  applySafetyControl("set_mute", { enabled });
});
elements.revocationSelect.addEventListener("change", updateRevocationButton);
elements.revocationButton.addEventListener("click", () => {
  const capability = elements.revocationSelect.value;
  const enabled = elements.revocationButton.dataset.revoked !== "true";
  applySafetyControl("set_revocation", { capability, enabled });
});
elements.sanitizeButton.addEventListener("click", sanitizeInput);
elements.createContextButton.addEventListener("click", createContextBundle);
elements.moderateButton.addEventListener("click", moderateContent);
elements.refreshMetricsButton.addEventListener("click", refreshMetrics);
elements.refreshErrorsButton.addEventListener("click", refreshErrors);
elements.sendEventButton.addEventListener("click", () => sendEvent());
elements.resendButton.addEventListener("click", () => sendEvent({ resend: true }));
elements.invalidButton.addEventListener("click", () => sendEvent({ invalid: true }));
elements.replayButton.addEventListener("click", requestReplay);
elements.binaryButton.addEventListener("click", sendBinary);
elements.clearActivityButton.addEventListener("click", () => elements.activityLog.replaceChildren());
elements.refreshMemoryButton.addEventListener("click", refreshMemory);
elements.proposeMemoryButton.addEventListener("click", proposeMemory);
elements.searchMemoryButton.addEventListener("click", searchMemory);
elements.memorySearchInput.addEventListener("keydown", (event) => {
  if (event.key === "Enter") {
    event.preventDefault();
    searchMemory();
  }
});
elements.exportMemoryButton.addEventListener("click", exportMemory);
elements.rebuildMemoryButton.addEventListener("click", rebuildMemory);
elements.refreshAvatarButton.addEventListener("click", () =>
  refreshAvatar({ logFailure: true }));
elements.previewAvatarButton.addEventListener("click", previewAvatarState);
elements.resetAvatarButton.addEventListener("click", resetAvatarState);
elements.avatarMuteButton.addEventListener("click", () => {
  const enabled = !(state.safetyStatus?.state.muted || false);
  applySafetyControl("set_mute", { enabled });
});
elements.avatarEmergencyButton.addEventListener("click", () => {
  const stopped = state.safetyStatus?.state.emergencyStopped || false;
  applySafetyControl(stopped ? "emergency_reset" : "emergency_stop");
});
window.addEventListener("hashchange", renderDashboardRoute);

window.addEventListener("beforeunload", () => {
  if (state.socket?.readyState === WebSocket.OPEN) {
    state.socket.close(1000, "page unload");
  }
  if (state.chatPollTimer !== null) {
    clearTimeout(state.chatPollTimer);
  }
  if (state.recording) {
    state.recording.stream.getTracks().forEach((track) => track.stop());
  }
  if (state.speechBlobUrl) {
    URL.revokeObjectURL(state.speechBlobUrl);
  }
  cancelTtsOnPageExit();
  if (state.ttsBlobUrl) {
    URL.revokeObjectURL(state.ttsBlobUrl);
  }
  if (state.avatarAudioFrame !== null) {
    cancelAnimationFrame(state.avatarAudioFrame);
  }
  state.avatarAudioContext?.close();
});
window.addEventListener("pagehide", cancelTtsOnPageExit);

updateConnection(false);
renderDashboardRoute();
refreshAll({ announce: false });
connectWebSocket();
setInterval(() => {
  refreshStatus();
  refreshMetrics();
  refreshSafety();
  refreshModel();
  refreshChatStatus();
  refreshSpeech();
  refreshTts();
  refreshMemory();
}, 5000);
setInterval(() => {
  if (location.hash === "#/avatar" || state.avatarPlaybackActive) {
    refreshAvatar();
  }
}, 250);
