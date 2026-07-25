import assert from "node:assert/strict";
import test from "node:test";
import { createAutoListenDetector } from "../src/auto-listen-detector.mjs";

function samples(level, count = 1_600) {
  return new Float32Array(count).fill(level);
}

test("ambient silence never submits a voice turn", () => {
  const detector = createAutoListenDetector();
  assert.equal(detector.push(samples(0.002), 0, 0.1).voiceDetected, false);
  const decision = detector.push(samples(0.001), 2_000, 2.1);
  assert.equal(decision.voiceDetected, false);
  assert.equal(decision.shouldSubmit, false);
});

test("speech followed by bounded silence submits exactly once", () => {
  const detector = createAutoListenDetector();
  assert.equal(detector.push(samples(0.04), 100, 0.5).voiceDetected, true);
  assert.equal(detector.push(samples(0.002), 200, 0.6).shouldSubmit, false);
  const decision = detector.push(samples(0.002), 1_000, 1.4);
  assert.equal(decision.shouldSubmit, true);
  assert.equal(detector.push(samples(0.002), 2_000, 2.4).shouldSubmit, false);
});

test("a natural pause with residual speech resets the silence timer", () => {
  const detector = createAutoListenDetector();
  detector.push(samples(0.04), 0, 0.4);
  detector.push(samples(0.002), 100, 0.5);
  detector.push(samples(0.014), 700, 1.1);
  assert.equal(detector.push(samples(0.002), 800, 1.2).shouldSubmit, false);
  assert.equal(detector.push(samples(0.002), 1_600, 2.0).shouldSubmit, true);
});

test("invalid samples and thresholds fail closed", () => {
  assert.throws(
    () => createAutoListenDetector({ silenceRms: 0.02, startRms: 0.01 }),
    /E_AUTO_LISTEN_CONFIG/,
  );
  const detector = createAutoListenDetector();
  assert.throws(() => detector.push(new Float32Array(), 0, 0), /E_AUTO_LISTEN_SAMPLES/);
});
