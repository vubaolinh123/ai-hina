import {
  MinecraftAdapterError,
  type MinecraftCardinalDirection,
  type MinecraftMoveSkillRequest,
  type MinecraftMovementEvidence,
  type MinecraftVector,
  type MinecraftWorldState,
} from "./contracts.js";
import type { MinecraftBotPort } from "./ports.js";
import { MOVE_STEP_SKILL_DEFINITION } from "./skill-registry.js";

const CARDINAL_MOVEMENT = Object.freeze({
  north: { yawRadians: Math.PI, x: 0, z: -1 },
  east: { yawRadians: -Math.PI / 2, x: 1, z: 0 },
  south: { yawRadians: 0, x: 0, z: 1 },
  west: { yawRadians: Math.PI / 2, x: -1, z: 0 },
} satisfies Record<
  MinecraftCardinalDirection,
  { yawRadians: number; x: number; z: number }
>);

const MAXIMUM_RECORDED_PHYSICS_TICKS = 80;

export interface MinecraftMovementProgressTracker {
  physicsTicksObserved: number;
  stagnantTicksObserved: number;
  maximumForwardProgressBlocks: number;
  lastObserved: MinecraftMovementEvidence | null;
}

export function createMovementProgressTracker(): MinecraftMovementProgressTracker {
  return {
    physicsTicksObserved: 0,
    stagnantTicksObserved: 0,
    maximumForwardProgressBlocks: 0,
    lastObserved: null,
  };
}

export function movementEvidence(
  direction: MinecraftCardinalDirection,
  start: MinecraftVector,
  end: MinecraftVector,
  progress: MinecraftMovementProgressTracker = createMovementProgressTracker(),
): MinecraftMovementEvidence {
  const vector = CARDINAL_MOVEMENT[direction];
  const deltaX = end.x - start.x;
  const deltaZ = end.z - start.z;
  const forwardProgressBlocks = deltaX * vector.x + deltaZ * vector.z;
  const lateralDriftBlocks = Math.abs(
    deltaX * -vector.z + deltaZ * vector.x,
  );
  return {
    deltaX,
    deltaZ,
    forwardProgressBlocks,
    lateralDriftBlocks,
    horizontalDistanceBlocks: Math.hypot(deltaX, deltaZ),
    physicsTicksObserved: progress.physicsTicksObserved,
    stagnantTicksObserved: progress.stagnantTicksObserved,
    maximumForwardProgressBlocks: progress.maximumForwardProgressBlocks,
  };
}

export function movementMatches(
  evidence: MinecraftMovementEvidence,
  distanceBlocks: number,
): boolean {
  const postcondition = MOVE_STEP_SKILL_DEFINITION.postcondition;
  return (
    evidence.forwardProgressBlocks >=
      distanceBlocks * postcondition.minimumProgressRatio &&
    evidence.forwardProgressBlocks <=
      distanceBlocks + postcondition.maximumOvershootBlocks &&
    evidence.lateralDriftBlocks <= postcondition.lateralToleranceBlocks
  );
}

export async function executeMoveStep(
  bot: MinecraftBotPort,
  request: MinecraftMoveSkillRequest,
  before: MinecraftWorldState,
  signal: AbortSignal,
  progress: MinecraftMovementProgressTracker,
): Promise<void> {
  const player = before.player;
  if (player === null) {
    throw new MinecraftAdapterError(
      "E_MINECRAFT_SKILL_PRECONDITION",
      "Player state is unavailable",
    );
  }
  const direction = CARDINAL_MOVEMENT[request.arguments.direction];
  await bot.look(direction.yawRadians, player.pitch);
  if (signal.aborted) {
    throw signal.reason;
  }
  bot.setControlState("forward", true);
  let previousProgress = 0;
  while (true) {
    await bot.waitForPhysicsTick(signal);
    progress.physicsTicksObserved = Math.min(
      MAXIMUM_RECORDED_PHYSICS_TICKS,
      progress.physicsTicksObserved + 1,
    );
    const current = bot.captureWorldState();
    if (current.player === null) {
      throw new MinecraftAdapterError(
        "E_MINECRAFT_SKILL_ACTION",
        "Player state disappeared during move.step.v1",
      );
    }
    let evidence = movementEvidence(
      request.arguments.direction,
      player.position,
      current.player.position,
      progress,
    );
    progress.maximumForwardProgressBlocks = Math.max(
      progress.maximumForwardProgressBlocks,
      evidence.forwardProgressBlocks,
    );
    if (evidence.forwardProgressBlocks <= previousProgress + 0.005) {
      progress.stagnantTicksObserved = Math.min(
        20,
        progress.stagnantTicksObserved + 1,
      );
    } else {
      progress.stagnantTicksObserved = 0;
    }
    evidence = movementEvidence(
      request.arguments.direction,
      player.position,
      current.player.position,
      progress,
    );
    progress.lastObserved = evidence;
    if (evidence.forwardProgressBlocks >= request.arguments.distanceBlocks) {
      return;
    }
    if (progress.stagnantTicksObserved >= 20) {
      throw new MinecraftAdapterError(
        "E_MINECRAFT_SKILL_BLOCKED",
        "move.step.v1 made no forward progress for 20 physics ticks",
      );
    }
    previousProgress = evidence.forwardProgressBlocks;
  }
}
