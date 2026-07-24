import assert from "node:assert/strict";
import test from "node:test";
import {
  HINA_MATERIAL_TINTS,
  HINA_PRESENTATION,
  blinkWeightAt,
  createHinaPoseFrame,
  listHinaPoseBones,
} from "../src/hina-presentation.mjs";

const STATES = [
  "idle",
  "listening",
  "thinking",
  "speaking",
  "interrupted",
  "error",
];

test("Hina profile covers every embedded VRM material with a visible color", () => {
  assert.equal(HINA_PRESENTATION.id, "hina-kawaii-v0.1");
  assert.deepEqual(
    Object.keys(HINA_MATERIAL_TINTS).sort(),
    [
      "Body_00_SKIN",
      "Bottoms_01_CLOTH",
      "EyeHighlight_00_EYE",
      "EyeIris_00_EYE",
      "EyeWhite_00_EYE",
      "FaceBrow_00_FACE",
      "FaceEyeline_00_FACE",
      "FaceMouth_00_FACE",
      "Face_00_SKIN",
      "HairBack_00_HAIR",
      "Hair_00_HAIR",
      "Shoes_01_CLOTH",
      "Tops_01_CLOTH",
    ],
  );
  for (const color of Object.values(HINA_MATERIAL_TINTS)) {
    assert.match(color, /^#[0-9a-f]{6}$/i);
  }
});

test("natural pose lowers both arms and returns finite bounded state motion", () => {
  const bones = listHinaPoseBones();
  assert.ok(bones.includes("leftUpperArm"));
  assert.ok(bones.includes("rightUpperArm"));
  for (const state of STATES) {
    for (const seconds of [0, 0.1, 1, 17.25, 9_999]) {
      const pose = createHinaPoseFrame(state, seconds);
      assert.ok(pose.leftUpperArm.z <= -0.9);
      assert.ok(pose.rightUpperArm.z >= 0.9);
      assert.ok(Math.abs(pose.leftUpperArm.z + pose.rightUpperArm.z) <= 0.12);
      for (const rotation of Object.values(pose)) {
        for (const value of Object.values(rotation)) {
          assert.ok(Number.isFinite(value));
          assert.ok(Math.abs(value) <= 1.45);
        }
      }
    }
  }
});

test("blink is deterministic, brief and bounded", () => {
  for (const state of STATES) {
    for (let frame = 0; frame < 500; frame += 1) {
      const value = blinkWeightAt(frame / 60, state);
      assert.ok(Number.isFinite(value));
      assert.ok(value >= 0 && value <= 1);
    }
  }
  assert.equal(blinkWeightAt(0, "idle"), blinkWeightAt(0, "idle"));
  assert.equal(blinkWeightAt(1, "idle"), 0);
  assert.throws(
    () => createHinaPoseFrame("unknown", 0),
    /E_HINA_PRESENTATION_STATE/,
  );
  assert.throws(() => blinkWeightAt(Number.NaN, "idle"), /E_HINA_PRESENTATION_TIME/);
});
