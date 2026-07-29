import {
  MinecraftAdapterError,
  type MinecraftCardinalDirection,
  type MinecraftMovementSkillRequest,
  type MinecraftMovementEvidence,
  type MinecraftVector,
  type MinecraftWorldState,
} from "./contracts.js";
import type { MinecraftBotPort } from "./ports.js";

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
const MINIMUM_TARGET_DISTANCE_BLOCKS = 0.25;
const MAXIMUM_TARGET_DISTANCE_BLOCKS = 2;

export interface MinecraftMovementPlan {
  skillId: MinecraftMovementSkillRequest["skillId"];
  yawRadians: number;
  unitX: number;
  unitZ: number;
  distanceBlocks: number;
  targetX: number;
  targetZ: number;
}

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

export function createMovementPlan(
  request: MinecraftMovementSkillRequest,
  before: MinecraftWorldState,
): MinecraftMovementPlan {
  const player = before.player;
  if (player === null) {
    throw new MinecraftAdapterError(
      "E_MINECRAFT_SKILL_PRECONDITION",
      "Player state is unavailable",
    );
  }
  if (request.skillId === "move.step.v1") {
    const direction = CARDINAL_MOVEMENT[request.arguments.direction];
    return {
      skillId: request.skillId,
      yawRadians: direction.yawRadians,
      unitX: direction.x,
      unitZ: direction.z,
      distanceBlocks: request.arguments.distanceBlocks,
      targetX: player.position.x + direction.x * request.arguments.distanceBlocks,
      targetZ: player.position.z + direction.z * request.arguments.distanceBlocks,
    };
  }
  const deltaX = request.arguments.targetX - player.position.x;
  const deltaZ = request.arguments.targetZ - player.position.z;
  const distanceBlocks = Math.hypot(deltaX, deltaZ);
  if (
    distanceBlocks < MINIMUM_TARGET_DISTANCE_BLOCKS ||
    distanceBlocks > MAXIMUM_TARGET_DISTANCE_BLOCKS
  ) {
    throw new MinecraftAdapterError(
      "E_MINECRAFT_SKILL_PRECONDITION",
      "move.to.v1 target must be 0.25-2.0 blocks from the current player position",
    );
  }
  const unitX = deltaX / distanceBlocks;
  const unitZ = deltaZ / distanceBlocks;
  return {
    skillId: request.skillId,
    yawRadians: Math.atan2(-unitX, unitZ),
    unitX,
    unitZ,
    distanceBlocks,
    targetX: request.arguments.targetX,
    targetZ: request.arguments.targetZ,
  };
}

export function movementEvidence(
  plan: MinecraftMovementPlan,
  start: MinecraftVector,
  end: MinecraftVector,
  progress: MinecraftMovementProgressTracker = createMovementProgressTracker(),
): MinecraftMovementEvidence {
  const deltaX = end.x - start.x;
  const deltaZ = end.z - start.z;
  const forwardProgressBlocks = deltaX * plan.unitX + deltaZ * plan.unitZ;
  const lateralDriftBlocks = Math.abs(
    deltaX * -plan.unitZ + deltaZ * plan.unitX,
  );
  return {
    deltaX,
    deltaZ,
    forwardProgressBlocks,
    lateralDriftBlocks,
    horizontalDistanceBlocks: Math.hypot(deltaX, deltaZ),
    remainingDistanceBlocks: Math.hypot(
      end.x - plan.targetX,
      end.z - plan.targetZ,
    ),
    physicsTicksObserved: progress.physicsTicksObserved,
    stagnantTicksObserved: progress.stagnantTicksObserved,
    maximumForwardProgressBlocks: progress.maximumForwardProgressBlocks,
  };
}

export function movementMatches(
  evidence: MinecraftMovementEvidence,
  distanceBlocks: number,
  postcondition: {
    minimumProgressRatio: number;
    maximumOvershootBlocks: number;
    lateralToleranceBlocks: number;
  },
): boolean {
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
  plan: MinecraftMovementPlan,
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
  await bot.look(plan.yawRadians, player.pitch);
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
      plan,
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
      plan,
      player.position,
      current.player.position,
      progress,
    );
    progress.lastObserved = evidence;
    if (evidence.forwardProgressBlocks >= plan.distanceBlocks) {
      return;
    }
    if (progress.stagnantTicksObserved >= 20) {
      throw new MinecraftAdapterError(
        "E_MINECRAFT_SKILL_BLOCKED",
        `${plan.skillId} made no forward progress for 20 physics ticks`,
      );
    }
    previousProgress = evidence.forwardProgressBlocks;
  }
}
