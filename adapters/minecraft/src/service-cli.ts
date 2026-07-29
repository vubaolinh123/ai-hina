import {
  MinecraftAdapterError,
  MinecraftController,
  startMinecraftStatusServer,
} from "./index.js";

const DEFAULT_PORT = 8_766;

function readControlToken(): string {
  const token = process.env.HINA_MINECRAFT_CONTROL_TOKEN;
  if (token === undefined || token.length === 0) {
    throw new MinecraftAdapterError(
      "E_MINECRAFT_CONTROL_TOKEN",
      "HINA_MINECRAFT_CONTROL_TOKEN is required",
    );
  }
  return token;
}

function readServicePort(): number {
  const raw = process.env.HINA_MINECRAFT_STATUS_PORT;
  if (raw === undefined || raw.length === 0) {
    return DEFAULT_PORT;
  }
  if (!/^[0-9]+$/u.test(raw)) {
    throw new MinecraftAdapterError(
      "E_MINECRAFT_CONFIG",
      "HINA_MINECRAFT_STATUS_PORT must be an integer",
    );
  }
  const port = Number.parseInt(raw, 10);
  if (port < 1 || port > 65_535) {
    throw new MinecraftAdapterError(
      "E_MINECRAFT_CONFIG",
      "HINA_MINECRAFT_STATUS_PORT must be between 1 and 65535",
    );
  }
  return port;
}

function boundedError(error: unknown): {
  code: string;
  message: string;
} {
  if (error instanceof MinecraftAdapterError) {
    return {
      code: error.code,
      message: error.message.slice(0, 240),
    };
  }
  return {
    code: "E_MINECRAFT_SERVICE",
    message:
      error instanceof Error
        ? error.message.slice(0, 240)
        : "Minecraft service failed",
  };
}

function log(
  level: "INFO" | "ERROR",
  event: string,
  fields: Record<string, unknown> = {},
): void {
  const line = JSON.stringify({
    timestamp: new Date().toISOString(),
    component: "hina-minecraft-service",
    level,
    event,
    ...fields,
  });
  (level === "ERROR" ? process.stderr : process.stdout).write(`${line}\n`);
}

async function main(): Promise<void> {
  const controller = new MinecraftController();
  const server = await startMinecraftStatusServer(controller, {
    port: readServicePort(),
    controlToken: readControlToken(),
  });
  let shuttingDown = false;
  const shutdown = async (signal: string): Promise<void> => {
    if (shuttingDown) {
      return;
    }
    shuttingDown = true;
    const result = await controller.emergencyStop();
    log("INFO", "shutdown", {
      signal,
      dispatchDurationMs: result.dispatchDurationMs,
    });
    await server.close();
  };

  process.once("SIGINT", () => {
    void shutdown("SIGINT").catch((error) => {
      log("ERROR", "shutdown_failed", boundedError(error));
      process.exitCode = 1;
    });
  });
  process.once("SIGTERM", () => {
    void shutdown("SIGTERM").catch((error) => {
      log("ERROR", "shutdown_failed", boundedError(error));
      process.exitCode = 1;
    });
  });

  log("INFO", "ready", {
    host: server.host,
    port: server.port,
    controlEnabled: server.controlEnabled,
    phase: controller.getStatus().phase,
  });
}

main().catch((error) => {
  log("ERROR", "startup_failed", boundedError(error));
  process.exitCode = 1;
});
