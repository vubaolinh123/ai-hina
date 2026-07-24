import assert from "node:assert/strict";
import test from "node:test";
import { createFrameMetrics } from "../src/frame-metrics.mjs";

test("steady 60 FPS produces bounded percentiles with zero estimated drops", () => {
  const metrics = createFrameMetrics({
    targetFps: 60,
    reportEveryMs: 2_000,
    maxSamples: 600,
  });
  metrics.push(0);
  let report = null;
  for (let frame = 1; frame <= 121; frame += 1) {
    report = metrics.push(frame * (1_000 / 60)) ?? report;
  }
  assert.ok(report);
  assert.ok(report.fps >= 59.9 && report.fps <= 60.1);
  assert.ok(report.frameTimeP95Ms >= 16.66 && report.frameTimeP95Ms <= 16.67);
  assert.ok(report.frameTimeP99Ms >= 16.66 && report.frameTimeP99Ms <= 16.67);
  assert.equal(report.droppedFramePercent, 0);
  assert.ok(report.sampleCount >= 120);
});

test("a long frame contributes deterministic estimated dropped frames", () => {
  const metrics = createFrameMetrics({
    targetFps: 60,
    reportEveryMs: 250,
    maxSamples: 60,
  });
  metrics.push(0);
  let emitted = null;
  for (const timestamp of [16.67, 33.34, 83.34, 100.01, 116.68, 266.68]) {
    emitted = metrics.push(timestamp) ?? emitted;
  }
  const report = emitted ?? metrics.snapshot();
  assert.ok(report);
  assert.equal(report.sampleCount, 6);
  assert.ok(report.frameTimeP95Ms >= 150);
  assert.ok(report.frameTimeP99Ms >= 150);
  assert.ok(report.droppedFramePercent > 50);
  assert.ok(report.droppedFramePercent <= 100);
});

test("sample retention remains bounded", () => {
  const metrics = createFrameMetrics({
    targetFps: 60,
    reportEveryMs: 60_000,
    maxSamples: 30,
  });
  metrics.push(0);
  for (let frame = 1; frame <= 100; frame += 1) {
    metrics.push(frame * 16.67);
  }
  const report = metrics.snapshot();
  assert.ok(report);
  assert.equal(report.sampleCount, 30);
  assert.ok(report.windowMs <= 501);
});

test("invalid options and timestamps fail closed", () => {
  assert.throws(
    () => createFrameMetrics({ targetFps: 0 }),
    /E_FRAME_METRICS_OPTIONS/,
  );
  assert.throws(
    () => createFrameMetrics({ maxSamples: 10 }),
    /E_FRAME_METRICS_OPTIONS/,
  );
  const metrics = createFrameMetrics();
  assert.throws(() => metrics.push(Number.NaN), /E_FRAME_METRICS_TIMESTAMP/);
  metrics.push(10);
  assert.throws(() => metrics.push(10), /E_FRAME_METRICS_ORDER/);
});
