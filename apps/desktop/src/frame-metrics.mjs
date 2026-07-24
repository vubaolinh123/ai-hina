const DEFAULT_TARGET_FPS = 60;
const DEFAULT_REPORT_EVERY_MS = 2_000;
const DEFAULT_MAX_SAMPLES = 600;

export function createFrameMetrics(options = {}) {
  const targetFps = positiveNumber(
    options.targetFps ?? DEFAULT_TARGET_FPS,
    "targetFps",
    15,
    240,
  );
  const reportEveryMs = positiveNumber(
    options.reportEveryMs ?? DEFAULT_REPORT_EVERY_MS,
    "reportEveryMs",
    250,
    60_000,
  );
  const maxSamples = positiveInteger(
    options.maxSamples ?? DEFAULT_MAX_SAMPLES,
    "maxSamples",
    30,
    3_600,
  );
  const frameTimes = [];
  let firstTimestamp = null;
  let lastTimestamp = null;

  function push(timestampMs) {
    if (!Number.isFinite(timestampMs) || timestampMs < 0) {
      throw new TypeError("E_FRAME_METRICS_TIMESTAMP: timestamp must be finite and non-negative");
    }
    if (lastTimestamp === null) {
      firstTimestamp = timestampMs;
      lastTimestamp = timestampMs;
      return null;
    }
    if (timestampMs <= lastTimestamp) {
      throw new TypeError("E_FRAME_METRICS_ORDER: timestamps must increase");
    }
    frameTimes.push(timestampMs - lastTimestamp);
    lastTimestamp = timestampMs;
    if (frameTimes.length > maxSamples) {
      frameTimes.shift();
      firstTimestamp = timestampMs - sum(frameTimes);
    }
    const elapsed = timestampMs - firstTimestamp;
    if (elapsed < reportEveryMs) return null;
    const report = summarize(frameTimes, elapsed, targetFps);
    frameTimes.length = 0;
    firstTimestamp = timestampMs;
    return report;
  }

  function snapshot() {
    if (
      frameTimes.length === 0
      || firstTimestamp === null
      || lastTimestamp === null
      || lastTimestamp <= firstTimestamp
    ) {
      return null;
    }
    return summarize(
      frameTimes,
      lastTimestamp - firstTimestamp,
      targetFps,
    );
  }

  function reset() {
    frameTimes.length = 0;
    firstTimestamp = null;
    lastTimestamp = null;
  }

  return Object.freeze({ push, snapshot, reset });
}

function summarize(frameTimes, windowMs, targetFps) {
  const sorted = [...frameTimes].sort((left, right) => left - right);
  const targetFrameMs = 1_000 / targetFps;
  const missedFrames = frameTimes.reduce(
    (total, frameTime) => (
      total + Math.max(0, Math.round(frameTime / targetFrameMs) - 1)
    ),
    0,
  );
  const totalExpectedFrames = frameTimes.length + missedFrames;
  return Object.freeze({
    targetFps,
    fps: rounded((frameTimes.length * 1_000) / windowMs, 1),
    frameTimeP95Ms: rounded(percentile(sorted, 0.95), 2),
    frameTimeP99Ms: rounded(percentile(sorted, 0.99), 2),
    droppedFramePercent: rounded(
      totalExpectedFrames === 0
        ? 0
        : (missedFrames * 100) / totalExpectedFrames,
      3,
    ),
    sampleCount: frameTimes.length,
    windowMs: rounded(windowMs, 1),
  });
}

function percentile(sorted, percentileValue) {
  const index = Math.max(0, Math.ceil(sorted.length * percentileValue) - 1);
  return sorted[index] ?? 0;
}

function sum(values) {
  return values.reduce((total, value) => total + value, 0);
}

function positiveNumber(value, name, minimum, maximum) {
  if (!Number.isFinite(value) || value < minimum || value > maximum) {
    throw new TypeError(`E_FRAME_METRICS_OPTIONS: ${name} is invalid`);
  }
  return value;
}

function positiveInteger(value, name, minimum, maximum) {
  if (!Number.isInteger(value) || value < minimum || value > maximum) {
    throw new TypeError(`E_FRAME_METRICS_OPTIONS: ${name} is invalid`);
  }
  return value;
}

function rounded(value, digits) {
  return Number(value.toFixed(digits));
}
