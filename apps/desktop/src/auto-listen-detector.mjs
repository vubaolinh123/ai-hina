const DEFAULT_START_RMS = 0.018;
const DEFAULT_SILENCE_RMS = 0.010;
const DEFAULT_SILENCE_MS = 750;
const DEFAULT_MIN_CAPTURE_SECONDS = 0.8;

export function createAutoListenDetector(options = {}) {
  const startRms = boundedNumber(
    options.startRms ?? DEFAULT_START_RMS,
    "startRms",
    0.001,
    1,
  );
  const silenceRms = boundedNumber(
    options.silenceRms ?? DEFAULT_SILENCE_RMS,
    "silenceRms",
    0,
    startRms,
  );
  const silenceMs = boundedNumber(
    options.silenceMs ?? DEFAULT_SILENCE_MS,
    "silenceMs",
    100,
    5_000,
  );
  const minCaptureSeconds = boundedNumber(
    options.minCaptureSeconds ?? DEFAULT_MIN_CAPTURE_SECONDS,
    "minCaptureSeconds",
    0.25,
    10,
  );
  let voiceDetected = false;
  let silenceStartedAt = null;
  let submitted = false;

  function push(samples, nowMs, captureSeconds) {
    if (!(samples instanceof Float32Array) || samples.length === 0) {
      throw new TypeError("E_AUTO_LISTEN_SAMPLES: samples must be a non-empty Float32Array");
    }
    if (!Number.isFinite(nowMs) || nowMs < 0) {
      throw new TypeError("E_AUTO_LISTEN_TIME: nowMs must be finite and non-negative");
    }
    if (!Number.isFinite(captureSeconds) || captureSeconds < 0) {
      throw new TypeError(
        "E_AUTO_LISTEN_DURATION: captureSeconds must be finite and non-negative",
      );
    }
    const rms = calculateRms(samples);
    if (submitted) return snapshot(rms, false);
    if (rms >= startRms) {
      voiceDetected = true;
      silenceStartedAt = null;
      return snapshot(rms, false);
    }
    if (!voiceDetected) return snapshot(rms, false);
    if (rms > silenceRms) {
      silenceStartedAt = null;
      return snapshot(rms, false);
    }
    silenceStartedAt ??= nowMs;
    const shouldSubmit = (
      captureSeconds >= minCaptureSeconds
      && nowMs - silenceStartedAt >= silenceMs
    );
    if (shouldSubmit) submitted = true;
    return snapshot(rms, shouldSubmit);
  }

  function snapshot(rms = 0, shouldSubmit = false) {
    return Object.freeze({
      rms,
      voiceDetected,
      shouldSubmit,
    });
  }

  function reset() {
    voiceDetected = false;
    silenceStartedAt = null;
    submitted = false;
  }

  return Object.freeze({ push, snapshot, reset });
}

function calculateRms(samples) {
  let sum = 0;
  for (const sample of samples) sum += sample * sample;
  return Math.sqrt(sum / samples.length);
}

function boundedNumber(value, name, minimum, maximum) {
  if (!Number.isFinite(value) || value < minimum || value > maximum) {
    throw new TypeError(
      `E_AUTO_LISTEN_CONFIG: ${name} must be between ${minimum} and ${maximum}`,
    );
  }
  return value;
}
