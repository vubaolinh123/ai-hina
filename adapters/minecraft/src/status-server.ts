import { timingSafeEqual } from "node:crypto";
import {
  createServer,
  type IncomingMessage,
  type Server,
  type ServerResponse,
} from "node:http";

import { validateMinecraftConnectionInput } from "./config.js";
import type { MinecraftController } from "./controller.js";
import { MinecraftAdapterError } from "./contracts.js";

const STATUS_HOST = "127.0.0.1";
const MAX_RESPONSE_BYTES = 65_536;
const MAX_REQUEST_BYTES = 8_192;
const OWNER_SOURCE = "owner.desktop";

export interface MinecraftStatusServerOptions {
  port: number;
  controlToken?: string;
}

export interface MinecraftStatusServer {
  host: typeof STATUS_HOST;
  port: number;
  controlEnabled: boolean;
  close(): Promise<void>;
}

function sendJson(
  response: ServerResponse,
  statusCode: number,
  payload: unknown,
): void {
  const body = JSON.stringify(payload);
  if (Buffer.byteLength(body, "utf8") > MAX_RESPONSE_BYTES) {
    response.writeHead(500, {
      "content-type": "application/json; charset=utf-8",
      "cache-control": "no-store",
    });
    response.end(
      JSON.stringify({
        errorCode: "E_MINECRAFT_STATUS_BOUNDS",
        message: "Normalized status exceeded its fixed response bound",
      }),
    );
    return;
  }
  response.writeHead(statusCode, {
    "content-type": "application/json; charset=utf-8",
    "content-length": Buffer.byteLength(body, "utf8"),
    "cache-control": "no-store",
    "x-content-type-options": "nosniff",
  });
  response.end(body);
}

function boundedError(error: unknown): {
  errorCode: string;
  message: string;
} {
  if (error instanceof MinecraftAdapterError) {
    return {
      errorCode: error.code,
      message: error.message.slice(0, 240),
    };
  }
  return {
    errorCode: "E_MINECRAFT_CONTROL",
    message: error instanceof Error
      ? error.message.slice(0, 240)
      : "Minecraft control request failed",
  };
}

function validateControlToken(value: string | undefined): string | null {
  if (value === undefined) {
    return null;
  }
  if (
    value.length < 43 ||
    value.length > 256 ||
    /[^A-Za-z0-9_-]/u.test(value)
  ) {
    throw new MinecraftAdapterError(
      "E_MINECRAFT_CONTROL_TOKEN",
      "Minecraft control token must be a 32-byte-or-longer base64url secret",
    );
  }
  return value;
}

function tokenMatches(expected: string, authorization: string | undefined): boolean {
  const prefix = "Bearer ";
  if (authorization === undefined || !authorization.startsWith(prefix)) {
    return false;
  }
  const provided = authorization.slice(prefix.length);
  const expectedBytes = Buffer.from(expected, "utf8");
  const providedBytes = Buffer.from(provided, "utf8");
  return (
    expectedBytes.byteLength === providedBytes.byteLength &&
    timingSafeEqual(expectedBytes, providedBytes)
  );
}

function requireOwnerControl(
  request: IncomingMessage,
  controlToken: string | null,
): void {
  if (
    controlToken === null ||
    request.headers["x-hina-source"] !== OWNER_SOURCE ||
    !tokenMatches(controlToken, request.headers.authorization)
  ) {
    throw new MinecraftAdapterError(
      "E_MINECRAFT_CONTROL_AUTHORITY",
      "Owner-authorized Minecraft control is required",
    );
  }
}

async function readJsonBody(request: IncomingMessage): Promise<unknown> {
  const chunks: Buffer[] = [];
  let total = 0;
  for await (const chunk of request) {
    const bytes = Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk);
    total += bytes.byteLength;
    if (total > MAX_REQUEST_BYTES) {
      throw new MinecraftAdapterError(
        "E_MINECRAFT_CONTROL_BOUNDS",
        "Minecraft control body exceeds 8192 bytes",
      );
    }
    chunks.push(bytes);
  }
  if (total === 0) {
    throw new MinecraftAdapterError(
      "E_MINECRAFT_CONTROL_SCHEMA",
      "Minecraft control body is required",
    );
  }
  try {
    return JSON.parse(Buffer.concat(chunks).toString("utf8"));
  } catch {
    throw new MinecraftAdapterError(
      "E_MINECRAFT_CONTROL_SCHEMA",
      "Minecraft control body must be valid JSON",
    );
  }
}

function exactOwnerAction(
  value: unknown,
  action: "disconnect" | "emergency_stop",
): void {
  if (
    typeof value !== "object" ||
    value === null ||
    Array.isArray(value)
  ) {
    throw new MinecraftAdapterError(
      "E_MINECRAFT_CONTROL_SCHEMA",
      "Minecraft owner action must be an object",
    );
  }
  const raw = value as Record<string, unknown>;
  if (
    Object.keys(raw).sort().join(",") !==
      "action,ownerConfirmed,source" ||
    raw.action !== action ||
    raw.source !== OWNER_SOURCE ||
    raw.ownerConfirmed !== true
  ) {
    throw new MinecraftAdapterError(
      "E_MINECRAFT_CONTROL_SCHEMA",
      "Minecraft owner action fields are invalid",
    );
  }
}

function exactGoalRequest(value: unknown): unknown {
  if (
    typeof value !== "object" ||
    value === null ||
    Array.isArray(value)
  ) {
    throw new MinecraftAdapterError(
      "E_MINECRAFT_CONTROL_SCHEMA",
      "Minecraft goal request must be an object",
    );
  }
  const raw = value as Record<string, unknown>;
  if (
    Object.keys(raw).sort().join(",") !== "goalId,ownerConfirmed,source" ||
    raw.source !== OWNER_SOURCE ||
    raw.ownerConfirmed !== true ||
    raw.goalId !== "harvest.nearby-log.v1"
  ) {
    throw new MinecraftAdapterError(
      "E_MINECRAFT_CONTROL_SCHEMA",
      "Minecraft goal authority fields are invalid",
    );
  }
  return {
    goalId: raw.goalId,
  };
}

async function listen(server: Server, port: number): Promise<number> {
  await new Promise<void>((resolve, reject) => {
    server.once("error", reject);
    server.listen(port, STATUS_HOST, () => {
      server.off("error", reject);
      resolve();
    });
  });
  const address = server.address();
  if (address === null || typeof address === "string") {
    throw new MinecraftAdapterError(
      "E_MINECRAFT_STATUS_SERVER",
      "Status server did not expose a TCP address",
    );
  }
  return address.port;
}

async function handleRequest(
  request: IncomingMessage,
  response: ServerResponse,
  controller: MinecraftController,
  servicePort: number,
  controlToken: string | null,
): Promise<void> {
  let pathname: string;
  try {
    pathname = new URL(
      request.url ?? "/",
      `http://${STATUS_HOST}`,
    ).pathname;
  } catch {
    sendJson(response, 400, {
      errorCode: "E_MINECRAFT_STATUS_REQUEST",
      message: "Malformed Minecraft status request",
    });
    return;
  }

  if (request.method === "GET") {
    if (pathname === "/health") {
      const status = controller.getStatus();
      sendJson(response, 200, {
        status: "ok",
        phase: status.phase,
        emergencyStopped: status.emergencyStopped,
        controlEnabled: controlToken !== null,
      });
      return;
    }
    if (pathname === "/v1/minecraft/status") {
      sendJson(response, 200, controller.getStatus());
      return;
    }
    sendJson(response, 404, {
      errorCode: "E_MINECRAFT_STATUS_NOT_FOUND",
      message: "Unknown Minecraft status route",
    });
    return;
  }

  if (request.method !== "POST") {
    response.setHeader("allow", "GET, POST");
    sendJson(response, 405, {
      errorCode: "E_MINECRAFT_STATUS_METHOD",
      message: "Minecraft status method is not allowed",
    });
    return;
  }

  try {
    requireOwnerControl(request, controlToken);
    const body = await readJsonBody(request);
    if (pathname === "/v1/minecraft/connect") {
      const config = validateMinecraftConnectionInput(body, servicePort);
      const status = await controller.start(config);
      sendJson(response, 200, {
        status: "connected",
        minecraft: status,
      });
      return;
    }
    if (pathname === "/v1/minecraft/disconnect") {
      exactOwnerAction(body, "disconnect");
      const disconnect = await controller.disconnect();
      sendJson(response, 200, {
        status: "disconnected",
        disconnect,
        minecraft: controller.getStatus(),
      });
      return;
    }
    if (pathname === "/v1/minecraft/goals/execute") {
      const execution = await controller.executeGoal(exactGoalRequest(body));
      sendJson(response, 200, {
        status: execution.status,
        execution,
        minecraft: controller.getStatus(),
      });
      return;
    }
    if (pathname === "/v1/minecraft/emergency-stop") {
      exactOwnerAction(body, "emergency_stop");
      const emergencyStop = await controller.emergencyStop();
      sendJson(response, 200, {
        status: "emergency_stopped",
        emergencyStop,
        minecraft: controller.getStatus(),
      });
      return;
    }
    sendJson(response, 404, {
      errorCode: "E_MINECRAFT_STATUS_NOT_FOUND",
      message: "Unknown Minecraft control route",
    });
  } catch (error) {
    const bounded = boundedError(error);
    const statusCode =
      bounded.errorCode === "E_MINECRAFT_CONTROL_AUTHORITY"
        ? 401
        : bounded.errorCode === "E_MINECRAFT_CONTROL_BOUNDS"
          ? 413
          : bounded.errorCode === "E_MINECRAFT_ALREADY_STARTED" ||
              bounded.errorCode === "E_MINECRAFT_EMERGENCY_STOPPED"
            ? 409
            : 400;
    sendJson(response, statusCode, bounded);
  }
}

export async function startMinecraftStatusServer(
  controller: MinecraftController,
  options: number | MinecraftStatusServerOptions,
): Promise<MinecraftStatusServer> {
  const port = typeof options === "number" ? options : options.port;
  const controlToken = validateControlToken(
    typeof options === "number" ? undefined : options.controlToken,
  );
  let boundPort = port;
  const server = createServer((request, response) => {
    void handleRequest(
      request,
      response,
      controller,
      boundPort,
      controlToken,
    ).catch((error) => {
      if (!response.headersSent) {
        sendJson(response, 500, boundedError(error));
      } else {
        response.end();
      }
    });
  });

  const actualPort = await listen(server, port);
  boundPort = actualPort;
  return {
    host: STATUS_HOST,
    port: actualPort,
    controlEnabled: controlToken !== null,
    close: async () => {
      await new Promise<void>((resolve, reject) => {
        server.close((error) => {
          if (error === undefined) {
            resolve();
          } else {
            reject(error);
          }
        });
      });
    },
  };
}
