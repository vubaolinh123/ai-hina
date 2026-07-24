export type FrameMetricsOptions = {
  targetFps?: number;
  reportEveryMs?: number;
  maxSamples?: number;
};

export type FrameMetricsReport = {
  targetFps: number;
  fps: number;
  frameTimeP95Ms: number;
  frameTimeP99Ms: number;
  droppedFramePercent: number;
  sampleCount: number;
  windowMs: number;
};

export type FrameMetrics = {
  push(timestampMs: number): FrameMetricsReport | null;
  snapshot(): FrameMetricsReport | null;
  reset(): void;
};

export function createFrameMetrics(
  options?: FrameMetricsOptions,
): FrameMetrics;
