import { createServer, type Server } from "node:http";

import type { MinecraftController } from "./controller.js";
import { MinecraftAdapterError } from "./contracts.js";

const STATUS_HOST = "127.0.0.1";
const MAX_RESPONSE_BYTES = 65_536;

export interface MinecraftStatusServer {
  host: typeof STATUS_HOST;
  port: number;
  close(): Promise<void>;
}

function sendJson(
  response: import("node:http").ServerResponse,
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
        error: {
          code: "E_MINECRAFT_STATUS_BOUNDS",
          message: "Normalized status exceeded its fixed response bound",
        },
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

export async function startMinecraftStatusServer(
  controller: MinecraftController,
  port: number,
): Promise<MinecraftStatusServer> {
  const server = createServer((request, response) => {
    if (request.method !== "GET") {
      response.setHeader("allow", "GET");
      sendJson(response, 405, {
        error: {
          code: "E_MINECRAFT_STATUS_METHOD",
          message: "Minecraft status service is read-only",
        },
      });
      return;
    }
    let pathname: string;
    try {
      pathname = new URL(
        request.url ?? "/",
        `http://${STATUS_HOST}`,
      ).pathname;
    } catch {
      sendJson(response, 400, {
        error: {
          code: "E_MINECRAFT_STATUS_REQUEST",
          message: "Malformed Minecraft status request",
        },
      });
      return;
    }
    if (pathname === "/health") {
      const status = controller.getStatus();
      sendJson(response, 200, {
        status: "ok",
        phase: status.phase,
        emergencyStopped: status.emergencyStopped,
      });
      return;
    }
    if (pathname === "/v1/minecraft/status") {
      sendJson(response, 200, controller.getStatus());
      return;
    }
    sendJson(response, 404, {
      error: {
        code: "E_MINECRAFT_STATUS_NOT_FOUND",
        message: "Unknown Minecraft status route",
      },
    });
  });

  const actualPort = await listen(server, port);
  return {
    host: STATUS_HOST,
    port: actualPort,
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
