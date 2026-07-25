export type AutoListenDetectorOptions = {
  startRms?: number;
  silenceRms?: number;
  silenceMs?: number;
  minCaptureSeconds?: number;
};

export type AutoListenDecision = {
  rms: number;
  voiceDetected: boolean;
  shouldSubmit: boolean;
};

export type AutoListenDetector = {
  push(
    samples: Float32Array,
    nowMs: number,
    captureSeconds: number,
  ): AutoListenDecision;
  snapshot(): AutoListenDecision;
  reset(): void;
};

export function createAutoListenDetector(
  options?: AutoListenDetectorOptions,
): AutoListenDetector;
