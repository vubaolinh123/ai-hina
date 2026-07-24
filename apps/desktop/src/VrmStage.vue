<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch } from "vue";
import * as THREE from "three";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";
import {
  VRMLoaderPlugin,
  VRMUtils,
  type VRM,
} from "@pixiv/three-vrm";
import motionProfile from "./avatar-motion.json";

const VRM_ASSET_URL = new URL(
  "../../../assets/avatars/vrm1-constraint-twist-sample/VRM1_Constraint_Twist_Sample.vrm",
  import.meta.url,
).href;
const DISPLAY_NAME = "VRM1_Constraint_Twist_Sample";
const KNOWN_EXPRESSIONS = [
  "happy",
  "sad",
  "relaxed",
  "surprised",
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
  ready: [details: { displayName: string; source: "bundled-vrm-1.0" }];
  failed: [message: string];
  fps: [value: number];
}>();

const canvas = ref<HTMLCanvasElement | null>(null);
let renderer: THREE.WebGLRenderer | null = null;
let scene: THREE.Scene | null = null;
let camera: THREE.PerspectiveCamera | null = null;
let vrm: VRM | null = null;
let resizeObserver: ResizeObserver | null = null;
let animationFrame: number | null = null;
let disposed = false;
let frameCount = 0;
let frameWindowStarted = 0;
let lastFrameTime = 0;

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
  const time = timeMilliseconds / 1_000;
  if (vrm) {
    const profile = motionProfile.states[props.state];
    const chest = vrm.humanoid.getNormalizedBoneNode("chest");
    const head = vrm.humanoid.getNormalizedBoneNode("head");
    if (chest) {
      chest.rotation.z = Math.sin(time * 1.7) * profile.breathAmplitude;
    }
    if (head) {
      head.rotation.y = Math.sin(time * 0.72) * profile.headAmplitude;
      head.rotation.z = Math.sin(time * 0.51) * profile.headAmplitude * 0.45;
    }
    const delta = lastFrameTime === 0 ? 0 : time - lastFrameTime;
    vrm.update(Math.min(0.05, Math.max(0, delta)));
  }
  lastFrameTime = time;
  renderer.render(scene, camera);

  frameCount += 1;
  if (frameWindowStarted === 0) frameWindowStarted = timeMilliseconds;
  const elapsed = timeMilliseconds - frameWindowStarted;
  if (elapsed >= 1_000) {
    emit("fps", Math.round((frameCount * 1_000) / elapsed));
    frameCount = 0;
    frameWindowStarted = timeMilliseconds;
  }
  animationFrame = window.requestAnimationFrame(renderFrame);
}

function disposeGraphics(): void {
  if (animationFrame !== null) {
    window.cancelAnimationFrame(animationFrame);
    animationFrame = null;
  }
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
}

onMounted(async () => {
  const target = canvas.value;
  if (!target) return;
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
    renderer.toneMappingExposure = 1.08;

    scene = new THREE.Scene();
    camera = new THREE.PerspectiveCamera(25, 1, 0.1, 20);
    camera.position.set(0, 1.32, 2.75);
    camera.lookAt(0, 1.24, 0);

    const key = new THREE.DirectionalLight(0xffe4d7, 2.2);
    key.position.set(1.5, 2.6, 2.2);
    scene.add(key);
    const fill = new THREE.DirectionalLight(0x9bbcff, 1.35);
    fill.position.set(-2, 1.5, 1.2);
    scene.add(fill);
    scene.add(new THREE.HemisphereLight(0xf8e9df, 0x251d38, 1.25));

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
    scene.add(loaded.scene);
    vrm = loaded;
    applyExpression();
    emit("ready", {
      displayName: DISPLAY_NAME,
      source: "bundled-vrm-1.0",
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
  <canvas ref="canvas" class="vrm-canvas" aria-label="Avatar VRM development sample"></canvas>
</template>
