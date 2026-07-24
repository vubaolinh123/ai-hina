<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch } from "vue";
import * as THREE from "three";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";
import {
  type VRMHumanBoneName,
  VRMLoaderPlugin,
  VRMUtils,
  type VRM,
} from "@pixiv/three-vrm";
import motionProfile from "./avatar-motion.json";
import {
  HINA_MATERIAL_TINTS,
  HINA_PRESENTATION,
  blinkWeightAt,
  createHinaPoseFrame,
} from "./hina-presentation.mjs";
import {
  createFrameMetrics,
  type FrameMetricsReport,
} from "./frame-metrics.mjs";

const VRM_ASSET_URL = new URL(
  "../../../assets/avatars/vrm1-constraint-twist-sample/VRM1_Constraint_Twist_Sample.vrm",
  import.meta.url,
).href;
const TARGET_FPS = 60;
const TARGET_FRAME_MS = 1_000 / TARGET_FPS;
const PERFORMANCE_WARMUP_FRAMES = 30;
const KNOWN_EXPRESSIONS = [
  "happy",
  "sad",
  "relaxed",
  "surprised",
  "blink",
  "aa",
  "ih",
  "ou",
  "ee",
  "oh",
] as const;
const VISEME_EXPRESSIONS = Object.freeze({
  A: "aa",
  I: "ih",
  U: "ou",
  E: "ee",
  O: "oh",
} as const);

const props = defineProps<{
  state: AvatarState;
  expression: string;
  viseme: AvatarStatus["viseme"];
  intensity: number;
}>();
const emit = defineEmits<{
  ready: [details: {
    displayName: string;
    presentationId: string;
    source: "bundled-vrm-1.0";
    loadedTextureCount: number;
    styledMaterialCount: number;
  }];
  failed: [message: string];
  performance: [value: FrameMetricsReport];
}>();

const canvas = ref<HTMLCanvasElement | null>(null);
const frameMetrics = createFrameMetrics({
  targetFps: TARGET_FPS,
  reportEveryMs: 2_000,
  maxSamples: 600,
});
let renderer: THREE.WebGLRenderer | null = null;
let scene: THREE.Scene | null = null;
let camera: THREE.PerspectiveCamera | null = null;
let vrm: VRM | null = null;
let resizeObserver: ResizeObserver | null = null;
let animationFrame: number | null = null;
let canvasElement: HTMLCanvasElement | null = null;
let disposed = false;
let lastFrameTime = 0;
let nextRenderAt = 0;
let performanceWarmupRemaining = PERFORMANCE_WARMUP_FRAMES;

type StylableMaterial = THREE.Material & {
  color?: THREE.Color;
  map?: THREE.Texture | null;
};

function listMaterials(root: THREE.Object3D): StylableMaterial[] {
  const materials = new Set<StylableMaterial>();
  root.traverse((object) => {
    if (!(object instanceof THREE.Mesh)) return;
    const candidates = Array.isArray(object.material)
      ? object.material
      : [object.material];
    for (const material of candidates) {
      materials.add(material as StylableMaterial);
    }
  });
  return [...materials];
}

function applyHinaPalette(root: THREE.Object3D): {
  loadedTextureCount: number;
  styledMaterialCount: number;
} {
  let loadedTextureCount = 0;
  let styledMaterialCount = 0;
  for (const material of listMaterials(root)) {
    const tint = HINA_MATERIAL_TINTS[material.name];
    if (tint && material.color) {
      material.color.set(tint);
      material.needsUpdate = true;
      styledMaterialCount += 1;
    }
    if (material.map) {
      material.map.colorSpace = THREE.SRGBColorSpace;
      material.map.needsUpdate = true;
      loadedTextureCount += 1;
    }
  }
  return { loadedTextureCount, styledMaterialCount };
}

function createPastelMaterial(color: number): THREE.MeshToonMaterial {
  return new THREE.MeshToonMaterial({
    color,
  });
}

function createBow(
  color: number,
  centerColor: number,
  scale = 1,
): THREE.Group {
  const group = new THREE.Group();
  const material = createPastelMaterial(color);
  const centerMaterial = createPastelMaterial(centerColor);
  const lobeGeometry = new THREE.SphereGeometry(0.045 * scale, 18, 12);
  const centerGeometry = new THREE.SphereGeometry(0.025 * scale, 18, 12);
  const left = new THREE.Mesh(lobeGeometry, material);
  left.scale.set(1.45, 0.85, 0.55);
  left.position.x = -0.04 * scale;
  left.rotation.z = -0.32;
  const right = new THREE.Mesh(lobeGeometry.clone(), material.clone());
  right.scale.set(1.45, 0.85, 0.55);
  right.position.x = 0.04 * scale;
  right.rotation.z = 0.32;
  const center = new THREE.Mesh(centerGeometry, centerMaterial);
  center.position.z = 0.016 * scale;
  group.add(left, right, center);
  return group;
}

function addHinaAccessories(target: VRM): void {
  const head = target.humanoid.getNormalizedBoneNode("head");
  if (head) {
    const hairBow = createBow(0xff86b6, 0xffd76d, 0.64);
    hairBow.name = "HinaHairBow";
    hairBow.position.set(-0.145, 0.16, 0.07);
    hairBow.rotation.set(0.04, -0.12, -0.2);
    head.add(hairBow);

    const star = new THREE.Mesh(
      new THREE.CircleGeometry(0.028, 5),
      new THREE.MeshBasicMaterial({
        color: 0xffe48a,
        side: THREE.DoubleSide,
      }),
    );
    star.name = "HinaStarHairpin";
    star.position.set(-0.12, 0.105, 0.112);
    star.rotation.z = -0.15;
    head.add(star);

    const blushMaterial = new THREE.MeshBasicMaterial({
      color: 0xff769f,
      depthWrite: false,
      opacity: 0.14,
      transparent: true,
    });
    for (const x of [-0.047, 0.047]) {
      const blush = new THREE.Mesh(
        new THREE.CircleGeometry(0.014, 20),
        blushMaterial.clone(),
      );
      blush.name = x < 0 ? "HinaBlushLeft" : "HinaBlushRight";
      blush.position.set(x, -0.008, 0.118);
      blush.scale.set(1.15, 0.4, 1);
      head.add(blush);
    }
  }

  const upperChest = target.humanoid.getNormalizedBoneNode("upperChest");
  if (upperChest) {
    const neckBow = createBow(0xff8fb8, 0xffd96f, 0.72);
    neckBow.name = "HinaNeckBow";
    neckBow.position.set(0, 0.055, 0.125);
    neckBow.rotation.x = -0.05;
    upperChest.add(neckBow);
  }

  const hips = target.humanoid.getNormalizedBoneNode("hips");
  if (hips) {
    const skirt = new THREE.Group();
    skirt.name = "HinaPastelSkirt";
    const skirtBody = new THREE.Mesh(
      new THREE.CylinderGeometry(0.16, 0.285, 0.31, 32, 1, true),
      new THREE.MeshToonMaterial({
        color: 0x8170aa,
        side: THREE.DoubleSide,
      }),
    );
    skirtBody.position.y = -0.145;
    const hem = new THREE.Mesh(
      new THREE.CylinderGeometry(0.282, 0.292, 0.035, 32, 1, true),
      new THREE.MeshToonMaterial({
        color: 0xff9fc3,
        side: THREE.DoubleSide,
      }),
    );
    hem.position.y = -0.292;
    const waist = new THREE.Mesh(
      new THREE.TorusGeometry(0.165, 0.018, 10, 32),
      createPastelMaterial(0xffd5e4),
    );
    waist.rotation.x = Math.PI / 2;
    waist.position.y = 0.006;
    skirt.add(skirtBody, hem, waist);
    hips.add(skirt);
  }
}

function applyHinaPose(time: number): void {
  if (!vrm) return;
  const pose = createHinaPoseFrame(props.state, time);
  for (const [boneName, rotation] of Object.entries(pose)) {
    const bone = vrm.humanoid.getNormalizedBoneNode(
      boneName as VRMHumanBoneName,
    );
    bone?.rotation.set(rotation.x, rotation.y, rotation.z, "XYZ");
  }
  vrm.humanoid.getNormalizedBoneNode("head")?.scale.setScalar(1.07);
  vrm.expressionManager?.setValue(
    "blink",
    blinkWeightAt(time, props.state),
  );
}

function applyExpression(): void {
  const manager = vrm?.expressionManager;
  if (!manager) return;
  for (const name of KNOWN_EXPRESSIONS) {
    manager.setValue(name, 0);
  }
  const profile = motionProfile.states[props.state];
  const alias = motionProfile.expressionAliases[
    props.expression as keyof typeof motionProfile.expressionAliases
  ];
  const expression = alias ?? "neutral";
  if (expression !== "neutral") {
    manager.setValue(expression, profile.expressionWeight);
  }
  const vowelExpression = VISEME_EXPRESSIONS[
    props.viseme as keyof typeof VISEME_EXPRESSIONS
  ];
  if (vowelExpression && props.state === "speaking") {
    manager.setValue(
      vowelExpression,
      Math.min(1, Math.max(0, Number(props.intensity) || 0)),
    );
  }
}

function resize(): void {
  if (!canvas.value || !renderer || !camera) return;
  const width = Math.max(1, canvas.value.clientWidth);
  const height = Math.max(1, canvas.value.clientHeight);
  renderer.setSize(width, height, false);
  camera.aspect = width / height;
  camera.updateProjectionMatrix();
}

function renderFrame(timeMilliseconds: number): void {
  if (disposed || !renderer || !scene || !camera) return;
  if (nextRenderAt > 0 && timeMilliseconds < nextRenderAt) {
    animationFrame = window.requestAnimationFrame(renderFrame);
    return;
  }
  nextRenderAt = nextRenderAt === 0
    ? timeMilliseconds + TARGET_FRAME_MS
    : nextRenderAt + TARGET_FRAME_MS;
  if (timeMilliseconds - nextRenderAt > TARGET_FRAME_MS) {
    nextRenderAt = timeMilliseconds + TARGET_FRAME_MS;
  }
  try {
    const time = timeMilliseconds / 1_000;
    if (vrm) {
      applyHinaPose(time);
      const delta = lastFrameTime === 0 ? 0 : time - lastFrameTime;
      vrm.update(Math.min(0.05, Math.max(0, delta)));
    }
    lastFrameTime = time;
    renderer.render(scene, camera);
    if (performanceWarmupRemaining > 0) {
      performanceWarmupRemaining -= 1;
      if (performanceWarmupRemaining === 0) frameMetrics.reset();
    } else {
      const performanceReport = frameMetrics.push(timeMilliseconds);
      if (performanceReport) {
        emit("performance", performanceReport);
      }
    }
    animationFrame = window.requestAnimationFrame(renderFrame);
  } catch (error) {
    const message = error instanceof Error
      ? error.message
      : "E_DESKTOP_RENDER_FRAME";
    emit("failed", `E_DESKTOP_RENDER_FRAME: ${message}`.slice(0, 200));
    disposeGraphics();
  }
}

function disposeGraphics(): void {
  if (animationFrame !== null) {
    window.cancelAnimationFrame(animationFrame);
    animationFrame = null;
  }
  canvasElement?.removeEventListener("webglcontextlost", handleWebglContextLost);
  resizeObserver?.disconnect();
  resizeObserver = null;
  if (vrm && scene) {
    scene.remove(vrm.scene);
    VRMUtils.deepDispose(vrm.scene);
  }
  renderer?.dispose();
  renderer?.forceContextLoss();
  vrm = null;
  renderer = null;
  scene = null;
  camera = null;
  canvasElement = null;
  frameMetrics.reset();
  lastFrameTime = 0;
  nextRenderAt = 0;
  performanceWarmupRemaining = PERFORMANCE_WARMUP_FRAMES;
}

function handleWebglContextLost(event: Event): void {
  event.preventDefault();
  if (disposed) return;
  emit(
    "failed",
    "E_DESKTOP_WEBGL_CONTEXT_LOST: ngữ cảnh đồ họa bị mất; SVG fallback vẫn hoạt động",
  );
  disposeGraphics();
}

onMounted(async () => {
  const target = canvas.value;
  if (!target) return;
  canvasElement = target;
  target.addEventListener("webglcontextlost", handleWebglContextLost);
  try {
    renderer = new THREE.WebGLRenderer({
      canvas: target,
      alpha: true,
      antialias: true,
      powerPreference: "high-performance",
    });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 1.5));
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    renderer.toneMapping = THREE.ACESFilmicToneMapping;
    renderer.toneMappingExposure = 0.94;

    scene = new THREE.Scene();
    camera = new THREE.PerspectiveCamera(24, 1, 0.1, 20);
    camera.position.set(0, 1.08, 2.75);
    camera.lookAt(0, 1.01, 0);

    const key = new THREE.DirectionalLight(0xffe4d7, 1.35);
    key.position.set(1.5, 2.6, 2.2);
    scene.add(key);
    const fill = new THREE.DirectionalLight(0xaec4ff, 0.72);
    fill.position.set(-2, 1.5, 1.2);
    scene.add(fill);
    const rim = new THREE.DirectionalLight(0xff9fca, 0.48);
    rim.position.set(0.4, 2.1, -1.8);
    scene.add(rim);
    scene.add(new THREE.HemisphereLight(0xfff1f6, 0x251d38, 0.88));

    resizeObserver = new ResizeObserver(resize);
    resizeObserver.observe(target);
    resize();

    const loader = new GLTFLoader();
    loader.register((parser) => new VRMLoaderPlugin(parser));
    const gltf = await loader.loadAsync(VRM_ASSET_URL);
    const loaded = gltf.userData.vrm as VRM | undefined;
    if (!loaded) {
      throw new Error("E_DESKTOP_VRM_DATA: bundled file has no VRM payload");
    }
    if (disposed) {
      VRMUtils.deepDispose(loaded.scene);
      return;
    }
    VRMUtils.removeUnnecessaryVertices(loaded.scene);
    loaded.scene.position.set(0, 0, 0);
    scene.add(loaded.scene);
    vrm = loaded;
    const materialReport = applyHinaPalette(loaded.scene);
    addHinaAccessories(loaded);
    applyHinaPose(0);
    applyExpression();
    loaded.update(0);
    emit("ready", {
      displayName: HINA_PRESENTATION.displayName,
      presentationId: HINA_PRESENTATION.id,
      source: "bundled-vrm-1.0",
      ...materialReport,
    });
    animationFrame = window.requestAnimationFrame(renderFrame);
  } catch (error) {
    const message = error instanceof Error ? error.message : "E_DESKTOP_VRM_LOAD";
    emit("failed", message.slice(0, 200));
    disposeGraphics();
  }
});

watch(
  () => [props.state, props.expression, props.viseme, props.intensity],
  applyExpression,
);

onBeforeUnmount(() => {
  disposed = true;
  disposeGraphics();
});
</script>

<template>
  <canvas
    ref="canvas"
    class="vrm-canvas"
    aria-label="Avatar Hina anime màu pastel"
  ></canvas>
</template>
