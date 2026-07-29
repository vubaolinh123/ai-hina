import { performance } from "node:perf_hooks";

import {
  MinecraftAdapterError,
  type EmergencyStopResult,
  type MinecraftAdapterErrorView,
  type MinecraftConnectionConfig,
  type MinecraftControllerStatus,
  type MinecraftDisconnectResult,
  type MinecraftLookSkillRequest,
  type MinecraftMoveSkillExecutionResult,
  type MinecraftMoveSkillRequest,
  type MinecraftMovementEvidence,
  type MinecraftRotationEvidence,
  type MinecraftSkillExecutionResult,
  type MinecraftWorldState,
} from "./contracts.js";
import { createMineflayerBot } from "./mineflayer-client.js";
import {
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
    this.#lastError = null;

    try {
      this.#bot = this.#factory(config);
    } catch (error) {
      this.#phase = "error";
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

    this.#connectPromise = new Promise<MinecraftControllerStatus>(
      (resolve, reject) => {
        let settled = false;
        const settleFailure = (code: string, payload: unknown): void => {
          const message = payloadMessage(payload, "Minecraft connection failed");
          this.#lastError = errorView(code, message);
          this.#sequence += 1;
          if (settled) {
            return;
          }
          this.#phase = "error";
          settled = true;
          clearTimeout(timeout);
          this.#cancelConnection = null;
          reject(new MinecraftAdapterError(code, this.#lastError.message));
        };
        this.#cancelConnection = settleFailure;

        const timeout = setTimeout(() => {
          settleFailure(
            "E_MINECRAFT_CONNECT_TIMEOUT",
            `Minecraft did not spawn within ${config.connectTimeoutMs} ms`,
          );
          void this.disconnect();
        }, config.connectTimeoutMs);
        timeout.unref();

        this.#eventUnsubscribers.push(
          this.#bot!.on("spawn", () => {
            if (this.#emergencyStopped) {
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
          this.#bot!.on("error", (payload) => {
            settleFailure("E_MINECRAFT_CONNECT", payload);
          }),
          this.#bot!.on("kicked", (payload) => {
            if (settled) {
              this.#lastError = errorView(
                "E_MINECRAFT_KICKED",
                payloadMessage(payload, "Minecraft server kicked the bot"),
              );
              this.#phase = "disconnected";
              this.#sequence += 1;
              return;
            }
            settleFailure("E_MINECRAFT_KICKED", payload);
          }),
          this.#bot!.on("end", (payload) => {
            if (!this.#emergencyStopped) {
              this.#phase = "disconnected";
              this.#sequence += 1;
              if (!settled) {
                settleFailure("E_MINECRAFT_ENDED", payload);
              }
            }
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
    if (this.#bot !== null && this.#phase === "online") {
      try {
        world = this.#bot.captureWorldState();
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
      lastError: this.#lastError,
    };
  }

  async executeSkill(requestValue: unknown): Promise<MinecraftSkillExecutionResult> {
    const request = validateMinecraftSkillRequest(requestValue);
    const executionId = ++this.#skillExecutionSequence;
    const startedAt = this.#clock();
    const started = performance.now();
    if (request.skillId === "move.step.v1") {
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
    request: MinecraftMoveSkillRequest,
    executionId: number,
    startedAt: Date,
    started: number,
  ): Promise<MinecraftMoveSkillExecutionResult> {
    const definition = MOVE_STEP_SKILL_DEFINITION;
    if (definition.id !== "move.step.v1") {
      throw new MinecraftAdapterError(
        "E_MINECRAFT_SKILL_REGISTRY",
        "move.step.v1 definition is unavailable",
      );
    }
    const expected = {
      direction: request.arguments.direction,
      distanceBlocks: request.arguments.distanceBlocks,
    };
    const minimumProgressBlocks =
      expected.distanceBlocks * definition.postcondition.minimumProgressRatio;
    const maximumProgressBlocks =
      expected.distanceBlocks + definition.postcondition.maximumOvershootBlocks;
    const finish = (
      status: MinecraftMoveSkillExecutionResult["status"],
      preconditionPassed: boolean,
      observed: MinecraftMovementEvidence | null,
      postconditionPassed: boolean,
      error: MinecraftAdapterErrorView | null,
    ): MinecraftMoveSkillExecutionResult => ({
      schemaVersion: 1,
      executionId,
      skillId: "move.step.v1",
      status,
      startedAt: startedAt.toISOString(),
      finishedAt: this.#clock().toISOString(),
      durationMs: Math.round((performance.now() - started) * 1_000) / 1_000,
      attempts: 1,
      precondition: { passed: preconditionPassed },
      postcondition: {
        passed: postconditionPassed,
        minimumProgressBlocks,
        maximumProgressBlocks,
        lateralToleranceBlocks:
          definition.postcondition.lateralToleranceBlocks,
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
          "move.step.v1 requires an on-ground player state",
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
          const error = new MinecraftAdapterError(
            "E_MINECRAFT_SKILL_TIMEOUT",
            `move.step.v1 exceeded ${definition.timeoutMs} ms`,
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
                  "move.step.v1 was cancelled",
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
        executeMoveStep(bot, request, before, abortController.signal),
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
      return finish("failed", true, null, false, view);
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
      request.arguments.direction,
      before.player.position,
      after.player.position,
    );
    const verified = movementMatches(observed, expected.distanceBlocks);
    return finish(
      verified ? "succeeded" : "failed",
      true,
      observed,
      verified,
      verified
        ? null
        : errorView(
            "E_MINECRAFT_SKILL_POSTCONDITION",
            "Player displacement did not match the verified cardinal target",
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
