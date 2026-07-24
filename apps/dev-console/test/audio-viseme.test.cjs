const assert = require("node:assert/strict");
const test = require("node:test");
const {
  classifyAudioViseme,
  createVisemeStabilizer,
} = require("../public/audio-viseme.js");

const SAMPLE_RATE = 48_000;
const FFT_SIZE = 2_048;

function timeSamples(amplitude = 32) {
  return Uint8Array.from(
    { length: FFT_SIZE },
    (_, index) => 128 + (index % 2 === 0 ? amplitude : -amplitude),
  );
}

function frequencySamples({ low = 0, mid = 0, high = 0 }) {
  const result = new Uint8Array(FFT_SIZE / 2);
  const binHz = SAMPLE_RATE / FFT_SIZE;
  for (let index = 1; index < result.length; index += 1) {
    const hz = index * binHz;
    if (hz >= 180 && hz < 700) result[index] = low;
    else if (hz >= 700 && hz < 1_800) result[index] = mid;
    else if (hz >= 1_800 && hz < 4_000) result[index] = high;
  }
  return result;
}

test("silence closes the mouth with bounded heuristic metadata", () => {
  const result = classifyAudioViseme(
    timeSamples(1),
    frequencySamples({ low: 0, mid: 0, high: 0 }),
    SAMPLE_RATE,
    FFT_SIZE,
  );
  assert.deepEqual(result, {
    viseme: "sil",
    intensity: 0,
    accuracy: "audio_spectral_heuristic",
  });
});

for (const [expected, bands] of [
  ["A", { low: 180, mid: 170, high: 150 }],
  ["I", { low: 80, mid: 100, high: 240 }],
  ["U", { low: 240, mid: 90, high: 60 }],
  ["E", { low: 80, mid: 240, high: 100 }],
  ["O", { low: 210, mid: 180, high: 70 }],
]) {
  test(`spectral profile maps to ${expected}`, () => {
    const result = classifyAudioViseme(
      timeSamples(),
      frequencySamples(bands),
      SAMPLE_RATE,
      FFT_SIZE,
    );
    assert.equal(result.viseme, expected);
    assert.ok(result.intensity > 0 && result.intensity <= 1);
    assert.equal(result.accuracy, "audio_spectral_heuristic");
  });
}

test("stabilizer requires consecutive frames and silence resets immediately", () => {
  const tracker = createVisemeStabilizer(2);
  const frame = { viseme: "I", intensity: 0.7, accuracy: "audio_spectral_heuristic" };
  assert.equal(tracker.push(frame).viseme, "sil");
  assert.equal(tracker.push(frame).viseme, "I");
  assert.equal(tracker.push({ ...frame, viseme: "A" }).viseme, "I");
  assert.deepEqual(
    tracker.push({ ...frame, viseme: "sil", intensity: 0 }),
    { viseme: "sil", intensity: 0, accuracy: "audio_spectral_heuristic" },
  );
});

test("invalid analyser input fails closed", () => {
  assert.throws(
    () => classifyAudioViseme([], new Uint8Array(2), 48_000, 4),
    /E_AUDIO_VISEME_INPUT/,
  );
  assert.throws(() => createVisemeStabilizer(0), /E_AUDIO_VISEME_STABILIZER/);
});
