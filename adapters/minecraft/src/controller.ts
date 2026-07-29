import { performance } from "node:perf_hooks";

import {
  MinecraftAdapterError,
  type EmergencyStopResult,
  type MinecraftAdapterErrorView,
  type MinecraftConnectionConfig,
  type MinecraftControllerStatus,
  type MinecraftWorldState,
} from "./contracts.js";
import { createMineflayerBot } from "./mineflayer-client.js";
import type {
  MinecraftBotFactory,
  MinecraftBotPort,
} from "./ports.js";

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
  #cancelConnection: (() => void) | null = null;

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
        this.#cancelConnection = () => {
          settleFailure(
            "E_MINECRAFT_EMERGENCY_STOPPED",
            "Emergency stop interrupted the Minecraft connection",
          );
        };

        const timeout = setTimeout(() => {
          settleFailure(
            "E_MINECRAFT_CONNECT_TIMEOUT",
            `Minecraft did not spawn within ${config.connectTimeoutMs} ms`,
          );
          void this.emergencyStop();
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
    this.#phase = "stopping";
    this.#sequence += 1;

    const bot = this.#bot;
    this.#cancelConnection?.();
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
