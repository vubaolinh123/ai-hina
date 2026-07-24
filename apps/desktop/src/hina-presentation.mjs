const AVATAR_STATES = Object.freeze([
  "idle",
  "listening",
  "thinking",
  "speaking",
  "interrupted",
  "error",
]);

export const HINA_PRESENTATION = Object.freeze({
  id: "hina-kawaii-v0.1",
  displayName: "Hina Kawaii · Pastel Sakura",
  description:
    "Bản Hina anime dễ thương dùng texture VRM nhúng sẵn, bảng màu và phụ kiện original của repository.",
});

export const HINA_MATERIAL_TINTS = Object.freeze({
  Body_00_SKIN: "#fff3ed",
  Bottoms_01_CLOTH: "#776a9d",
  Shoes_01_CLOTH: "#70536f",
  Tops_01_CLOTH: "#ffd1df",
  HairBack_00_HAIR: "#f4d6e4",
  FaceMouth_00_FACE: "#ff9fb1",
  EyeIris_00_EYE: "#cab8ff",
  Face_00_SKIN: "#fff5ef",
  EyeWhite_00_EYE: "#fffefe",
  FaceEyeline_00_FACE: "#72516d",
  FaceBrow_00_FACE: "#94708c",
  EyeHighlight_00_EYE: "#ffffff",
  Hair_00_HAIR: "#f4d6e4",
});

const BASE_POSE = Object.freeze({
  hips: Object.freeze({ x: 0, y: 0, z: -0.025 }),
  spine: Object.freeze({ x: 0.015, y: 0, z: 0.018 }),
  chest: Object.freeze({ x: -0.025, y: 0, z: 0.02 }),
  neck: Object.freeze({ x: 0.025, y: 0, z: -0.015 }),
  head: Object.freeze({ x: -0.035, y: 0.018, z: -0.025 }),
  leftShoulder: Object.freeze({ x: 0, y: 0, z: 0.08 }),
  leftUpperArm: Object.freeze({ x: 0.08, y: -0.04, z: -1.32 }),
  leftLowerArm: Object.freeze({ x: -0.05, y: -0.18, z: 0.12 }),
  leftHand: Object.freeze({ x: 0.02, y: -0.08, z: 0.08 }),
  rightShoulder: Object.freeze({ x: 0, y: 0, z: -0.08 }),
  rightUpperArm: Object.freeze({ x: 0.08, y: 0.04, z: 1.32 }),
  rightLowerArm: Object.freeze({ x: -0.05, y: 0.18, z: -0.12 }),
  rightHand: Object.freeze({ x: 0.02, y: 0.08, z: -0.08 }),
  leftUpperLeg: Object.freeze({ x: 0, y: 0, z: -0.025 }),
  rightUpperLeg: Object.freeze({ x: 0, y: 0, z: 0.025 }),
});

const STATE_MOTION = Object.freeze({
  idle: Object.freeze({
    sway: 0.018,
    nod: 0.012,
    arm: 0.018,
    tempo: 0.72,
  }),
  listening: Object.freeze({
    sway: 0.025,
    nod: 0.025,
    arm: 0.025,
    tempo: 0.92,
  }),
  thinking: Object.freeze({
    sway: 0.02,
    nod: 0.035,
    arm: 0.032,
    tempo: 0.56,
  }),
  speaking: Object.freeze({
    sway: 0.035,
    nod: 0.028,
    arm: 0.055,
    tempo: 1.35,
  }),
  interrupted: Object.freeze({
    sway: 0.012,
    nod: 0.02,
    arm: 0.012,
    tempo: 0.5,
  }),
  error: Object.freeze({
    sway: 0.008,
    nod: 0.014,
    arm: 0.008,
    tempo: 0.42,
  }),
});

function assertFiniteSeconds(seconds) {
  if (!Number.isFinite(seconds) || seconds < 0) {
    throw new TypeError("E_HINA_PRESENTATION_TIME");
  }
}

function resolveState(state) {
  if (!AVATAR_STATES.includes(state)) {
    throw new TypeError("E_HINA_PRESENTATION_STATE");
  }
  return state;
}

function addRotation(pose, bone, axis, value) {
  pose[bone][axis] += value;
}

export function createHinaPoseFrame(state, seconds) {
  const resolvedState = resolveState(state);
  assertFiniteSeconds(seconds);
  const motion = STATE_MOTION[resolvedState];
  const pose = Object.fromEntries(
    Object.entries(BASE_POSE).map(([bone, rotation]) => [
      bone,
      { ...rotation },
    ]),
  );
  const wave = Math.sin(seconds * motion.tempo);
  const secondaryWave = Math.sin(seconds * motion.tempo * 0.67 + 0.8);

  addRotation(pose, "hips", "z", wave * motion.sway * 0.32);
  addRotation(pose, "chest", "z", wave * motion.sway);
  addRotation(pose, "head", "y", secondaryWave * motion.nod);
  addRotation(pose, "head", "z", wave * motion.nod * 0.55);
  addRotation(pose, "leftUpperArm", "z", secondaryWave * motion.arm);
  addRotation(pose, "rightUpperArm", "z", secondaryWave * motion.arm);
  addRotation(pose, "leftLowerArm", "y", wave * motion.arm * 0.55);
  addRotation(pose, "rightLowerArm", "y", -wave * motion.arm * 0.55);

  if (resolvedState === "listening") {
    addRotation(pose, "head", "z", -0.055);
  } else if (resolvedState === "thinking") {
    addRotation(pose, "head", "y", -0.08);
    addRotation(pose, "head", "z", 0.045);
  } else if (resolvedState === "interrupted" || resolvedState === "error") {
    addRotation(pose, "head", "x", 0.06);
    addRotation(pose, "chest", "x", 0.035);
  }
  return pose;
}

export function blinkWeightAt(seconds, state) {
  const resolvedState = resolveState(state);
  assertFiniteSeconds(seconds);
  if (resolvedState === "error") return 0.28;
  const phase = (seconds + 0.37) % 4.2;
  if (phase < 3.74 || phase > 3.98) return 0;
  const distance = Math.abs(phase - 3.86);
  return Math.max(0, Math.min(1, 1 - distance / 0.12));
}

export function listHinaPoseBones() {
  return Object.keys(BASE_POSE);
}
