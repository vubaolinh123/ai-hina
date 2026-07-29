import {
  MinecraftAdapterError,
  parseMinecraftConnectionConfig,
  MinecraftController,
  startMinecraftStatusServer,
} from "./index.js";

function boundedMessage(error: unknown): {
  code: string;
  message: string;
} {
  if (error instanceof MinecraftAdapterError) {
    return { code: error.code, message: error.message };
  }
  if (error instanceof Error) {
    return {
      code: "E_MINECRAFT_RUNTIME",
      message: error.message.slice(0, 240),
    };
  }
  return {
    code: "E_MINECRAFT_RUNTIME",
    message: "Unknown Minecraft adapter failure",
  };
}

function log(
  level: "INFO" | "ERROR",
  event: string,
  fields: Record<string, unknown> = {},
): void {
  const line = JSON.stringify({
    timestamp: new Date().toISOString(),
    component: "hina-minecraft",
    level,
    event,
    ...fields,
  });
  if (level === "ERROR") {
    process.stderr.write(`${line}\n`);
  } else {
    process.stdout.write(`${line}\n`);
  }
}

async function main(): Promise<void> {
  const config = parseMinecraftConnectionConfig(process.argv.slice(2));
  const controller = new MinecraftController();
  const statusServer = await startMinecraftStatusServer(
    controller,
    config.statusPort,
  );
  let shuttingDown = false;

  const shutdown = async (signal: string): Promise<void> => {
    if (shuttingDown) {
      return;
    }
    shuttingDown = true;
    const result = await controller.emergencyStop();
    log("INFO", "emergency_stop", {
      signal,
      dispatchDurationMs: result.dispatchDurationMs,
      alreadyStopped: result.alreadyStopped,
    });
    await statusServer.close();
  };

  process.once("SIGINT", () => {
    void shutdown("SIGINT").catch((error) => {
      log("ERROR", "shutdown_failed", boundedMessage(error));
      process.exitCode = 1;
    });
  });
  process.once("SIGTERM", () => {
    void shutdown("SIGTERM").catch((error) => {
      log("ERROR", "shutdown_failed", boundedMessage(error));
      process.exitCode = 1;
    });
  });

  log("INFO", "status_ready", {
    url: `http://${statusServer.host}:${statusServer.port}/v1/minecraft/status`,
  });
  try {
    await controller.start(config);
  } catch (error) {
    await controller.emergencyStop();
    await statusServer.close();
    throw error;
  }
  log("INFO", "connected", {
    host: config.host,
    port: config.port,
    username: config.username,
    version: config.version ?? "auto",
  });
}

main().catch((error) => {
  log("ERROR", "startup_failed", boundedMessage(error));
  process.exitCode = 1;
});
