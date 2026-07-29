import { performance } from "node:perf_hooks";

import {
  MinecraftAdapterError,
  MINECRAFT_WORLD_FRESHNESS_MAX_AGE_MS,
  type EmergencyStopResult,
  type MinecraftAdapterErrorView,
  type MinecraftConnectionConfig,
  type MinecraftControllerStatus,
  type MinecraftDisconnectResult,
  type MinecraftLookSkillRequest,
  type MinecraftMovementSkillExecutionResult,
  type MinecraftMovementSkillRequest,
  type MinecraftMovementEvidence,
  type MinecraftRotationEvidence,
  type MinecraftSkillExecutionResult,
  type MinecraftWorldState,
  type MinecraftWorldFreshness,
} from "./contracts.js";
import { createMineflayerBot } from "./mineflayer-client.js";
import {
  createMovementPlan,
  createMovementProgressTracker,
  executeMoveStep,
  movementEvidence,
  movementMatches,
} from "./movement.js";
import type {
  MinecraftBotFactory,
  MinecraftBotPort,
} from "./ports.js";
import {
  LOOK_SKILL_DEFINITION,
  MOVE_STEP_SKILL_DEFINITION,
  MOVE_TO_SKILL_DEFINITION,
  validateMinecraftSkillRequest,
} from "./skill-registry.js";

type Clock = () => Date;

function errorView(
  code: string,
  message: string,
): MinecraftAdapterErrorView {
  return {
    code,
    message: message.replace(/[\u0000-\u001f\u007f]/g, " ").trim().slice(0, 240),
  };
}

function payloadMessage(payload: unknown, fallback: string): string {
  if (payload instanceof Error) {
    return payload.message;
  }
  if (typeof payload === "string") {
    return payload;
  }
  return fallback;
}

export class MinecraftController {
  readonly #factory: MinecraftBotFactory;
  readonly #clock: Clock;
  #bot: MinecraftBotPort | null = null;
  #config: MinecraftConnectionConfig | null = null;
  #phase: MinecraftControllerStatus["phase"] = "disconnected";
  #emergencyStopped = false;
  #sequence = 0;
  #connectedAt: Date | null = null;
  #lastError: MinecraftAdapterErrorView | null = null;
  #eventUnsubscribers: Array<() => void> = [];
  #connectPromise: Promise<MinecraftControllerStatus> | null = null;
  #cancelConnection:
    | ((code: string, message: string) => void)
    | null = null;
  #activeSkillAbort: AbortController | null = null;
  #skillExecutionSequence = 0;

  constructor(
    factory: MinecraftBotFactory = createMineflayerBot,
    clock: Clock = () => new Date(),
  ) {
    this.#factory = factory;
    this.#clock = clock;
  }

  start(config: MinecraftConnectionConfig): Promise<MinecraftControllerStatus> {
    if (this.#emergencyStopped) {
      return Promise.reject(
        new MinecraftAdapterError(
          "E_MINECRAFT_EMERGENCY_STOPPED",
          "Emergency stop is latched; restart the adapter before reconnecting",
        ),
      );
    }
    if (this.#connectPromise !== null || this.#bot !== null) {
      return Promise.reject(
        new MinecraftAdapterError(
          "E_MINECRAFT_ALREADY_STARTED",
          "Minecraft adapter has already started",
        ),
      );
    }

    this.#config = { ...config };
    this.#phase = "connecting";
    this.#sequence += 1;
    this.#connectedAt = null;
    this.#lastError = null;

    try {
      this.#bot = this.#factory(config);
    } catch (error) {
      this.#phase = "disconnected";
      this.#lastError = errorView(
        "E_MINECRAFT_CONNECT",
        payloadMessage(error, "Mineflayer failed to initialize"),
      );
      return Promise.reject(
        new MinecraftAdapterError(
          this.#lastError.code,
          this.#lastError.message,
          { cause: error },
        ),
      );
    }

    const bot = this.#bot;
    this.#connectPromise = new Promise<MinecraftControllerStatus>(
      (resolve, reject) => {
        let settled = false;
        const settleFailure = (code: string, payload: unknown): void => {
          if (settled || this.#bot !== bot) {
            return;
          }
          const message = payloadMessage(payload, "Minecraft connection failed");
          this.#lastError = errorView(code, message);
          this.#sequence += 1;
          this.#phase = this.#emergencyStopped ? "stopped" : "disconnected";
          settled = true;
          clearTimeout(timeout);
          this.#cancelConnection = null;
          this.#releaseBotAfterConnectionFailure(
            bot,
            "Hina connection attempt failed",
          );
          reject(new MinecraftAdapterError(code, this.#lastError.message));
        };
        this.#cancelConnection = settleFailure;

        const timeout = setTimeout(() => {
          settleFailure(
            "E_MINECRAFT_CONNECT_TIMEOUT",
            `Minecraft did not spawn within ${config.connectTimeoutMs} ms`,
          );
        }, config.connectTimeoutMs);
        timeout.unref();

        this.#eventUnsubscribers.push(
          bot.on("spawn", () => {
            if (
              settled ||
              this.#bot !== bot ||
              this.#emergencyStopped
            ) {
              return;
            }
            this.#phase = "online";
            this.#connectedAt = this.#clock();
            this.#sequence += 1;
            if (!settled) {
              settled = true;
              clearTimeout(timeout);
              this.#cancelConnection = null;
              resolve(this.getStatus());
            }
          }),
          bot.on("error", (payload) => {
            if (this.#bot !== bot) {
              return;
            }
            if (!settled) {
              settleFailure("E_MINECRAFT_CONNECT", payload);
              return;
            }
            this.#transitionDisconnectedBot(
              bot,
              "E_MINECRAFT_CONNECT",
              payload,
              "Minecraft connection was lost",
            );
          }),
          bot.on("kicked", (payload) => {
            if (this.#bot !== bot) {
              return;
            }
            if (!settled) {
              settleFailure("E_MINECRAFT_KICKED", payload);
              return;
            }
            this.#transitionDisconnectedBot(
              bot,
              "E_MINECRAFT_KICKED",
              payload,
              "Minecraft server kicked Hina",
            );
          }),
          bot.on("end", (payload) => {
            if (this.#bot !== bot || this.#emergencyStopped) {
              return;
            }
            if (!settled) {
              settleFailure("E_MINECRAFT_ENDED", payload);
              return;
            }
            this.#transitionDisconnectedBot(
              bot,
              "E_MINECRAFT_ENDED",
              payload,
              "Minecraft connection ended",
            );
          }),
        );
      },
    ).finally(() => {
      this.#connectPromise = null;
    });

    return this.#connectPromise;
  }

  getStatus(): MinecraftControllerStatus {
    let world: MinecraftWorldState | null = null;
    let worldFreshness: MinecraftWorldFreshness | null = null;
    if (this.#bot !== null && this.#phase === "online") {
      try {
        world = this.#bot.captureWorldState();
        worldFreshness = this.#readWorldFreshness(this.#bot);
      } catch (error) {
        this.#lastError = errorView(
          "E_MINECRAFT_SNAPSHOT",
          payloadMessage(error, "Could not normalize Minecraft state"),
        );
      }
    }
    const capturedAt = this.#clock().toISOString();
    return {
      schemaVersion: 1,
      phase: this.#phase,
      emergencyStopped: this.#emergencyStopped,
      sequence: this.#sequence,
      target:
        this.#config === null
          ? null
          : {
              host: this.#config.host,
              port: this.#config.port,
              username: this.#config.username,
              version: this.#config.version ?? null,
            },
      connectedAt: this.#connectedAt?.toISOString() ?? null,
      capturedAt,
      world,
      worldFreshness,
      lastError: this.#lastError,
    };
  }

  async executeSkill(requestValue: unknown): Promise<MinecraftSkillExecutionResult> {
    const request = validateMinecraftSkillRequest(requestValue);
    const executionId = ++this.#skillExecutionSequence;
    const startedAt = this.#clock();
    const started = performance.now();
    if (
      request.skillId === "move.step.v1" ||
      request.skillId === "move.to.v1"
    ) {
      return this.#executeMoveStepSkill(
        request,
        executionId,
        startedAt,
        started,
      );
    }
    const expected: MinecraftRotationEvidence = {
      yawRadians: request.arguments.yawRadians,
      pitchRadians: request.arguments.pitchRadians,
    };
    const finish = (
      status: MinecraftSkillExecutionResult["status"],
      preconditionPassed: boolean,
      observed: MinecraftRotationEvidence | null,
      postconditionPassed: boolean,
      error: MinecraftAdapterErrorView | null,
    ): MinecraftSkillExecutionResult => ({
      schemaVersion: 1,
      executionId,
      skillId: request.skillId,
      status,
      startedAt: startedAt.toISOString(),
      finishedAt: this.#clock().toISOString(),
      durationMs: Math.round((performance.now() - started) * 1_000) / 1_000,
      attempts: 1,
      precondition: {
        passed: preconditionPassed,
      },
      postcondition: {
        passed: postconditionPassed,
        toleranceRadians:
          LOOK_SKILL_DEFINITION.postcondition.toleranceRadians,
        expected,
        observed,
      },
      error,
    });

    if (this.#activeSkillAbort !== null) {
      return finish(
        "failed",
        false,
        null,
        false,
        errorView(
          "E_MINECRAFT_SKILL_BUSY",
          "Another deterministic Minecraft skill is already active",
        ),
      );
    }
    if (
      this.#emergencyStopped ||
      this.#phase !== "online" ||
      this.#bot === null
    ) {
      return finish(
        "failed",
        false,
        null,
        false,
        errorView(
          "E_MINECRAFT_SKILL_PRECONDITION",
          "Minecraft controller must be online and not emergency-stopped",
        ),
      );
    }

    const bot = this.#bot;
    const worldFreshness = this.#readWorldFreshness(bot);
    if (worldFreshness.state !== "fresh") {
      return finish(
        "failed",
        false,
        null,
        false,
        this.#staleWorldStateError(worldFreshness),
      );
    }
    let before: MinecraftWorldState;
    try {
      before = bot.captureWorldState();
    } catch (error) {
      return finish(
        "failed",
        false,
        null,
        false,
        errorView(
          "E_MINECRAFT_SKILL_PRECONDITION",
          payloadMessage(error, "Player state is unavailable"),
        ),
      );
    }
    if (before.player === null) {
      return finish(
        "failed",
        false,
        null,
        false,
        errorView(
          "E_MINECRAFT_SKILL_PRECONDITION",
          "Player state is unavailable",
        ),
      );
    }

    const abortController = new AbortController();
    this.#activeSkillAbort = abortController;
    let timeout: NodeJS.Timeout | null = null;
    let removeAbortListener = (): void => {};
    try {
      const timeoutPromise = new Promise<never>((_resolve, reject) => {
        timeout = setTimeout(() => {
          reject(
            new MinecraftAdapterError(
              "E_MINECRAFT_SKILL_TIMEOUT",
              `look.v1 exceeded ${LOOK_SKILL_DEFINITION.timeoutMs} ms`,
            ),
          );
        }, LOOK_SKILL_DEFINITION.timeoutMs);
        timeout.unref();
      });
      const abortPromise = new Promise<never>((_resolve, reject) => {
        const onAbort = (): void => {
          const reason = abortController.signal.reason;
          reject(reason instanceof MinecraftAdapterError
            ? reason
            : new MinecraftAdapterError(
                "E_MINECRAFT_SKILL_CANCELLED",
                "look.v1 was cancelled",
              ));
        };
        abortController.signal.addEventListener("abort", onAbort, {
          once: true,
        });
        removeAbortListener = () =>
          abortController.signal.removeEventListener("abort", onAbort);
      });
      await Promise.race([
        this.#executeLook(bot, request),
        timeoutPromise,
        abortPromise,
      ]);
    } catch (error) {
      try {
        bot.clearControlStates();
      } catch {
        // The failure result remains authoritative if the vendor client degraded.
      }
      const view =
        error instanceof MinecraftAdapterError
          ? errorView(error.code, error.message)
          : errorView(
              "E_MINECRAFT_SKILL_ACTION",
              payloadMessage(error, "Mineflayer look action failed"),
            );
      return finish("failed", true, null, false, view);
    } finally {
      if (timeout !== null) {
        clearTimeout(timeout);
      }
      removeAbortListener();
      if (this.#activeSkillAbort === abortController) {
        this.#activeSkillAbort = null;
      }
    }

    let after: MinecraftWorldState;
    try {
      after = bot.captureWorldState();
    } catch (error) {
      return finish(
        "failed",
        true,
        null,
        false,
        errorView(
          "E_MINECRAFT_SKILL_POSTCONDITION",
          payloadMessage(error, "Post-action player state is unavailable"),
        ),
      );
    }
    if (after.player === null) {
      return finish(
        "failed",
        true,
        null,
        false,
        errorView(
          "E_MINECRAFT_SKILL_POSTCONDITION",
          "Post-action player state is unavailable",
        ),
      );
    }
    const observed: MinecraftRotationEvidence = {
      yawRadians: after.player.yaw,
      pitchRadians: after.player.pitch,
    };
    const verified = this.#rotationMatches(expected, observed);
    return finish(
      verified ? "succeeded" : "failed",
      true,
      observed,
      verified,
      verified
        ? null
        : errorView(
            "E_MINECRAFT_SKILL_POSTCONDITION",
            "Player rotation did not reach the verified target",
          ),
    );
  }

  async #executeMoveStepSkill(
    request: MinecraftMovementSkillRequest,
    executionId: number,
    startedAt: Date,
    started: number,
  ): Promise<MinecraftMovementSkillExecutionResult> {
    const definition =
      request.skillId === "move.step.v1"
        ? MOVE_STEP_SKILL_DEFINITION
        : MOVE_TO_SKILL_DEFINITION;
    const movementProgress = createMovementProgressTracker();
    let targetDistanceBlocks: number | null =
      request.skillId === "move.step.v1"
        ? request.arguments.distanceBlocks
        : null;
    const finish = (
      status: MinecraftMovementSkillExecutionResult["status"],
      preconditionPassed: boolean,
      observed: MinecraftMovementEvidence | null,
      postconditionPassed: boolean,
      error: MinecraftAdapterErrorView | null,
    ): MinecraftMovementSkillExecutionResult => {
      const resultBase = {
        schemaVersion: 1 as const,
        executionId,
        status,
        startedAt: startedAt.toISOString(),
        finishedAt: this.#clock().toISOString(),
        durationMs: Math.round((performance.now() - started) * 1_000) / 1_000,
        attempts: 1 as const,
        precondition: { passed: preconditionPassed },
        error,
      };
      const progress = {
        physicsTicksObserved: movementProgress.physicsTicksObserved,
        stagnantTicksObserved: movementProgress.stagnantTicksObserved,
        maximumForwardProgressBlocks:
          movementProgress.maximumForwardProgressBlocks,
      };
      if (request.skillId === "move.step.v1") {
        return {
          ...resultBase,
          skillId: request.skillId,
          postcondition: {
            passed: postconditionPassed,
            minimumProgressBlocks:
              request.arguments.distanceBlocks *
              definition.postcondition.minimumProgressRatio,
            maximumProgressBlocks:
              request.arguments.distanceBlocks +
              definition.postcondition.maximumOvershootBlocks,
            lateralToleranceBlocks:
              definition.postcondition.lateralToleranceBlocks,
            expected: {
              direction: request.arguments.direction,
              distanceBlocks: request.arguments.distanceBlocks,
            },
            progress,
            observed,
          },
        };
      }
      return {
        ...resultBase,
        skillId: request.skillId,
        postcondition: {
          passed: postconditionPassed,
          targetDistanceBlocks,
          minimumProgressBlocks:
            targetDistanceBlocks === null
              ? null
              : targetDistanceBlocks *
                definition.postcondition.minimumProgressRatio,
          maximumProgressBlocks:
            targetDistanceBlocks === null
              ? null
              : targetDistanceBlocks +
                definition.postcondition.maximumOvershootBlocks,
          lateralToleranceBlocks:
            definition.postcondition.lateralToleranceBlocks,
          expected: {
            targetX: request.arguments.targetX,
            targetZ: request.arguments.targetZ,
          },
          progress,
          observed,
        },
      };
    };

    if (this.#activeSkillAbort !== null) {
      return finish(
        "failed",
        false,
        null,
        false,
        errorView(
          "E_MINECRAFT_SKILL_BUSY",
          "Another deterministic Minecraft skill is already active",
        ),
      );
    }
    if (
      this.#emergencyStopped ||
      this.#phase !== "online" ||
      this.#bot === null
    ) {
      return finish(
        "failed",
        false,
        null,
        false,
        errorView(
          "E_MINECRAFT_SKILL_PRECONDITION",
          "Minecraft controller must be online and not emergency-stopped",
        ),
      );
    }

    const bot = this.#bot;
    const worldFreshness = this.#readWorldFreshness(bot);
    if (worldFreshness.state !== "fresh") {
      return finish(
        "failed",
        false,
        null,
        false,
        this.#staleWorldStateError(worldFreshness),
      );
    }
    let before: MinecraftWorldState;
    try {
      before = bot.captureWorldState();
    } catch (error) {
      return finish(
        "failed",
        false,
        null,
        false,
        errorView(
          "E_MINECRAFT_SKILL_PRECONDITION",
          payloadMessage(error, "Player state is unavailable"),
        ),
      );
    }
    if (before.player === null || !before.player.onGround) {
      return finish(
        "failed",
        false,
        null,
        false,
        errorView(
          "E_MINECRAFT_SKILL_PRECONDITION",
          `${request.skillId} requires an on-ground player state`,
        ),
      );
    }

    let movementPlan;
    try {
      movementPlan = createMovementPlan(request, before);
      targetDistanceBlocks = movementPlan.distanceBlocks;
    } catch (error) {
      const view =
        error instanceof MinecraftAdapterError
          ? errorView(error.code, error.message)
          : errorView(
              "E_MINECRAFT_SKILL_PRECONDITION",
              payloadMessage(error, "Movement target is invalid"),
            );
      return finish("failed", false, null, false, view);
    }

    const abortController = new AbortController();
    this.#activeSkillAbort = abortController;
    let timeout: NodeJS.Timeout | null = null;
    let removeAbortListener = (): void => {};
    try {
      const timeoutPromise = new Promise<never>((_resolve, reject) => {
        timeout = setTimeout(() => {
          const error = new MinecraftAdapterError(
            "E_MINECRAFT_SKILL_TIMEOUT",
            `${request.skillId} exceeded ${definition.timeoutMs} ms`,
          );
          abortController.abort(error);
          reject(error);
        }, definition.timeoutMs);
        timeout.unref();
      });
      const abortPromise = new Promise<never>((_resolve, reject) => {
        const onAbort = (): void => {
          const reason = abortController.signal.reason;
          reject(
            reason instanceof MinecraftAdapterError
              ? reason
              : new MinecraftAdapterError(
                  "E_MINECRAFT_SKILL_CANCELLED",
                  `${request.skillId} was cancelled`,
                ),
          );
        };
        abortController.signal.addEventListener("abort", onAbort, {
          once: true,
        });
        removeAbortListener = () =>
          abortController.signal.removeEventListener("abort", onAbort);
      });
      await Promise.race([
        executeMoveStep(
          bot,
          movementPlan,
          before,
          abortController.signal,
          movementProgress,
        ),
        timeoutPromise,
        abortPromise,
      ]);
    } catch (error) {
      const view =
        error instanceof MinecraftAdapterError
          ? errorView(error.code, error.message)
          : errorView(
              "E_MINECRAFT_SKILL_ACTION",
              payloadMessage(error, "Mineflayer movement failed"),
            );
      return finish(
        "failed",
        true,
        movementProgress.lastObserved,
        false,
        view,
      );
    } finally {
      if (timeout !== null) {
        clearTimeout(timeout);
      }
      removeAbortListener();
      try {
        bot.clearControlStates();
      } catch {
        // The bounded failure result remains authoritative.
      }
      if (this.#activeSkillAbort === abortController) {
        this.#activeSkillAbort = null;
      }
    }

    let after: MinecraftWorldState;
    try {
      after = bot.captureWorldState();
    } catch (error) {
      return finish(
        "failed",
        true,
        null,
        false,
        errorView(
          "E_MINECRAFT_SKILL_POSTCONDITION",
          payloadMessage(error, "Post-action player state is unavailable"),
        ),
      );
    }
    if (after.player === null) {
      return finish(
        "failed",
        true,
        null,
        false,
        errorView(
          "E_MINECRAFT_SKILL_POSTCONDITION",
          "Post-action player state is unavailable",
        ),
      );
    }
    const observed = movementEvidence(
      movementPlan,
      before.player.position,
      after.player.position,
      movementProgress,
    );
    const verified = movementMatches(
      observed,
      movementPlan.distanceBlocks,
      definition.postcondition,
    );
    return finish(
      verified ? "succeeded" : "failed",
      true,
      observed,
      verified,
      verified
        ? null
        : errorView(
            "E_MINECRAFT_SKILL_POSTCONDITION",
            "Player displacement did not match the verified movement target",
          ),
    );
  }

  async #executeLook(
    bot: MinecraftBotPort,
    request: MinecraftLookSkillRequest,
  ): Promise<void> {
    await bot.look(
      request.arguments.yawRadians,
      request.arguments.pitchRadians,
    );
  }

  #readWorldFreshness(bot: MinecraftBotPort): MinecraftWorldFreshness {
    try {
      const freshness = bot.getWorldStateFreshness();
      const validAge =
        freshness.ageMs === null ||
        (Number.isFinite(freshness.ageMs) && freshness.ageMs >= 0);
      if (
        !Number.isSafeInteger(freshness.physicsTickSequence) ||
        freshness.physicsTickSequence < 0 ||
        !validAge ||
        freshness.maximumAgeMs !== MINECRAFT_WORLD_FRESHNESS_MAX_AGE_MS ||
        (freshness.state !== "fresh" &&
          freshness.state !== "stale" &&
          freshness.state !== "unavailable") ||
        (freshness.state === "unavailable" && freshness.ageMs !== null) ||
        (freshness.state !== "unavailable" && freshness.ageMs === null) ||
        (freshness.state === "fresh" &&
          freshness.ageMs !== null &&
          freshness.ageMs > freshness.maximumAgeMs) ||
        (freshness.state === "stale" &&
          freshness.ageMs !== null &&
          freshness.ageMs <= freshness.maximumAgeMs)
      ) {
        throw new Error("Minecraft physics freshness is invalid");
      }
      return { ...freshness };
    } catch {
      return {
        physicsTickSequence: 0,
        ageMs: null,
        maximumAgeMs: MINECRAFT_WORLD_FRESHNESS_MAX_AGE_MS,
        state: "unavailable",
      };
    }
  }

  #staleWorldStateError(
    freshness: MinecraftWorldFreshness,
  ): MinecraftAdapterErrorView {
    return errorView(
      "E_MINECRAFT_SKILL_STALE_STATE",
      freshness.state === "stale"
        ? `Minecraft physics state is ${freshness.ageMs ?? "unknown"} ms old; maximum is ${freshness.maximumAgeMs} ms`
        : "Minecraft physics state is unavailable; wait for a live server tick",
    );
  }

  #rotationMatches(
    expected: MinecraftRotationEvidence,
    observed: MinecraftRotationEvidence,
  ): boolean {
    const yawDelta = Math.abs(
      Math.atan2(
        Math.sin(observed.yawRadians - expected.yawRadians),
        Math.cos(observed.yawRadians - expected.yawRadians),
      ),
    );
    const pitchDelta = Math.abs(
      observed.pitchRadians - expected.pitchRadians,
    );
    const tolerance =
      LOOK_SKILL_DEFINITION.postcondition.toleranceRadians;
    return yawDelta <= tolerance && pitchDelta <= tolerance;
  }

  #transitionDisconnectedBot(
    bot: MinecraftBotPort,
    code: string,
    payload: unknown,
    quitReason: string,
  ): void {
    if (this.#bot !== bot) {
      return;
    }
    this.#lastError = errorView(
      code,
      payloadMessage(payload, "Minecraft connection ended"),
    );
    this.#phase = "disconnected";
    this.#sequence += 1;
    this.#releaseBotAfterConnectionFailure(bot, quitReason);
  }

  #releaseBotAfterConnectionFailure(
    bot: MinecraftBotPort,
    quitReason: string,
  ): void {
    if (this.#bot !== bot) {
      return;
    }
    this.#eventUnsubscribers.splice(0).forEach((unsubscribe) => {
      try {
        unsubscribe();
      } catch {
        // A vendor listener must not retain a failed connection attempt.
      }
    });
    this.#bot = null;
    this.#connectedAt = null;
    try {
      bot.clearControlStates();
    } catch {
      // The socket release below remains authoritative.
    }
    try {
      bot.quit(quitReason);
    } catch {
      // The socket may already be closed after an error or kick.
    }
  }

  async disconnect(): Promise<MinecraftDisconnectResult> {
    const started = performance.now();
    const alreadyDisconnected =
      this.#bot === null && this.#connectPromise === null;
    if (alreadyDisconnected) {
      this.#phase = this.#emergencyStopped ? "stopped" : "disconnected";
      return {
        alreadyDisconnected: true,
        localActionsStoppedAt: this.#clock().toISOString(),
        dispatchDurationMs:
          Math.round((performance.now() - started) * 1_000) / 1_000,
      };
    }

    this.#activeSkillAbort?.abort(
      new MinecraftAdapterError(
        "E_MINECRAFT_SKILL_CANCELLED",
        "look.v1 was cancelled by owner disconnect",
      ),
    );
    this.#cancelConnection?.(
      "E_MINECRAFT_DISCONNECTED",
      "Owner disconnected the Minecraft adapter",
    );
    this.#cancelConnection = null;
    const bot = this.#bot;
    if (bot !== null) {
      try {
        bot.clearControlStates();
      } catch {
        // Disconnect remains authoritative if local controls are degraded.
      }
      try {
        void bot.stopDigging().catch(() => {
          // Socket disconnect remains authoritative.
        });
      } catch {
        // A broken vendor implementation must not delay disconnect.
      }
      try {
        bot.quit("Hina owner disconnect");
      } catch {
        // The socket may already be closed.
      }
    }
    this.#eventUnsubscribers.splice(0).forEach((unsubscribe) => unsubscribe());
    this.#bot = null;
    this.#connectedAt = null;
    this.#phase = this.#emergencyStopped ? "stopped" : "disconnected";
    this.#sequence += 1;
    return {
      alreadyDisconnected: false,
      localActionsStoppedAt: this.#clock().toISOString(),
      dispatchDurationMs:
        Math.round((performance.now() - started) * 1_000) / 1_000,
    };
  }

  async emergencyStop(): Promise<EmergencyStopResult> {
    const started = performance.now();
    const alreadyStopped = this.#emergencyStopped;
    if (alreadyStopped) {
      return {
        alreadyStopped: true,
        localActionsStoppedAt: this.#clock().toISOString(),
        dispatchDurationMs:
          Math.round((performance.now() - started) * 1_000) / 1_000,
      };
    }
    this.#emergencyStopped = true;
    this.#activeSkillAbort?.abort(
      new MinecraftAdapterError(
        "E_MINECRAFT_SKILL_CANCELLED",
        "look.v1 was cancelled by emergency stop",
      ),
    );
    this.#phase = "stopping";
    this.#sequence += 1;

    const bot = this.#bot;
    this.#cancelConnection?.(
      "E_MINECRAFT_EMERGENCY_STOPPED",
      "Emergency stop interrupted the Minecraft connection",
    );
    this.#cancelConnection = null;
    if (!alreadyStopped && bot !== null) {
      try {
        bot.clearControlStates();
      } catch {
        // Emergency shutdown continues even if the vendor client is degraded.
      }
      try {
        void bot.stopDigging().catch(() => {
          // Disconnect remains authoritative if digging cancellation rejects.
        });
      } catch {
        // A broken vendor implementation must not delay disconnect.
      }
      try {
        bot.quit("Hina emergency stop");
      } catch {
        // The socket may already be closed.
      }
    }

    this.#eventUnsubscribers.splice(0).forEach((unsubscribe) => unsubscribe());
    this.#bot = null;
    this.#phase = "stopped";
    this.#sequence += 1;
    const localActionsStoppedAt = this.#clock().toISOString();
    return {
      alreadyStopped,
      localActionsStoppedAt,
      dispatchDurationMs:
        Math.round((performance.now() - started) * 1_000) / 1_000,
    };
  }
}
