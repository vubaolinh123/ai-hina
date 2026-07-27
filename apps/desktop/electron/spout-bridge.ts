import {
  execFile,
  spawn,
  type ChildProcess,
} from "node:child_process";
import { createInterface, type Interface } from "node:readline";
import { join } from "node:path";
import { createServer } from "node:net";

const SENDER_NAME = "VTubeStudioSpout";
const START_TIMEOUT_MILLISECONDS = 20_000;
const STATUS_POLL_MILLISECONDS = 100;
const FRAME_STALE_MILLISECONDS = 2_000;

export type SpoutBridgeState =
  | "disabled"
  | "starting"
  | "ready"
  | "degraded"
  | "error";

export type SpoutBridgeStatus = {
  available: true;
  enabled: boolean;
  state: SpoutBridgeState;
  sender: typeof SENDER_NAME;
  endpoint: string | null;
  frameUrl: string | null;
  frameReady: boolean;
  frameSequence: number;
  frameAgeMilliseconds: number | null;
  width: number;
  height: number;
  transparent: boolean;
  lastErrorCode: string | null;
};

type WorkerLine = {
  kind: "READY" | "STATUS" | "ERROR";
  payload: Record<string, unknown>;
};

function boundedString(value: unknown, maxLength = 160): string | null {
  if (typeof value !== "string" || value.length === 0) return null;
  return value.slice(0, maxLength);
}

function boundedInteger(value: unknown, fallback: number): number {
  return typeof value === "number"
    && Number.isInteger(value)
    && value >= 0
    && value <= 8192
    ? value
    : fallback;
}

function boundedNonNegativeNumber(
  value: unknown,
  fallback: number | null,
): number | null {
  return typeof value === "number"
    && Number.isFinite(value)
    && value >= 0
    && value <= 60_000
    ? value
    : fallback;
}

function boundedPort(value: unknown): number | null {
  return typeof value === "number"
    && Number.isInteger(value)
    && value >= 1
    && value <= 65_535
    ? value
    : null;
}

function isFrameStale(frameReady: boolean, age: unknown): boolean {
  const boundedAge = boundedNonNegativeNumber(age, null);
  return frameReady
    && boundedAge !== null
    && boundedAge > FRAME_STALE_MILLISECONDS;
}

function parseWorkerLine(line: string): WorkerLine | null {
  const separator = line.indexOf(" ");
  if (separator <= 0) return null;
  const kind = line.slice(0, separator);
  if (kind !== "READY" && kind !== "STATUS" && kind !== "ERROR") return null;
  try {
    const payload = JSON.parse(line.slice(separator + 1));
    if (!payload || typeof payload !== "object" || Array.isArray(payload)) return null;
    return { kind, payload: payload as Record<string, unknown> };
  } catch {
    return null;
  }
}

function errorCode(error: unknown): string {
  if (error instanceof Error && error.message.startsWith("E_")) {
    return error.message.slice(0, 96);
  }
  return "E_SPOUT_BRIDGE";
}

async function terminateProcessTree(child: ChildProcess): Promise<void> {
  if (child.exitCode !== null || child.pid === undefined) return;
  if (process.platform === "win32") {
    await new Promise<void>((resolve) => {
      execFile(
        "taskkill.exe",
        ["/PID", String(child.pid), "/T", "/F"],
        { windowsHide: true },
        () => resolve(),
      );
    });
    return;
  }
  child.kill("SIGTERM");
}

async function reserveLoopbackPort(): Promise<number> {
  const server = createServer();
  return new Promise<number>((resolve, reject) => {
    server.once("error", reject);
    server.listen(0, "127.0.0.1", () => {
      const address = server.address();
      if (!address || typeof address === "string") {
        server.close();
        reject(new Error("E_SPOUT_BRIDGE_PORT"));
        return;
      }
      const port = address.port;
      server.close((error) => {
        if (error) {
          reject(new Error("E_SPOUT_BRIDGE_PORT"));
        } else {
          resolve(port);
        }
      });
    });
  });
}

export class SpoutBridge {
  private child: ChildProcess | null = null;
  private stdout: Interface | null = null;
  private statusPollTimer: NodeJS.Timeout | null = null;
  private startPromise: Promise<SpoutBridgeStatus> | null = null;
  private stopping = false;
  private statusSnapshot: SpoutBridgeStatus;

  constructor(
    private readonly options: {
      repoRoot: string;
      enabled?: boolean;
      uvPath?: string;
      log?: (level: "info" | "warn" | "error", message: string) => void;
    },
  ) {
    const enabled = options.enabled !== false;
    this.statusSnapshot = {
      available: true,
      enabled,
      state: enabled ? "starting" : "disabled",
      sender: SENDER_NAME,
      endpoint: null,
      frameUrl: null,
      frameReady: false,
      frameSequence: 0,
      frameAgeMilliseconds: null,
      width: 0,
      height: 0,
      transparent: false,
      lastErrorCode: null,
    };
  }

  status(): SpoutBridgeStatus {
    return { ...this.statusSnapshot };
  }

  start(): Promise<SpoutBridgeStatus> {
    if (!this.statusSnapshot.enabled) {
      return Promise.resolve(this.status());
    }
    if (this.startPromise) return this.startPromise;
    this.startPromise = this.startInternal().finally(() => {
      this.startPromise = null;
    });
    return this.startPromise;
  }

  async stop(): Promise<void> {
    this.stopping = true;
    if (this.statusPollTimer) {
      clearInterval(this.statusPollTimer);
      this.statusPollTimer = null;
    }
    this.stdout?.close();
    this.stdout = null;
    const child = this.child;
    this.child = null;
    if (child && !child.killed && child.exitCode === null) {
      await terminateProcessTree(child);
      if (child.exitCode === null) {
        await new Promise<void>((resolve) => {
          const timer = setTimeout(resolve, 2_000);
          child.once("exit", () => {
            clearTimeout(timer);
            resolve();
          });
        });
      }
    }
    this.statusSnapshot = {
      ...this.statusSnapshot,
      state: this.statusSnapshot.enabled ? "degraded" : "disabled",
      frameReady: false,
      frameAgeMilliseconds: null,
      endpoint: null,
      frameUrl: null,
      lastErrorCode: this.statusSnapshot.enabled
        ? "E_SPOUT_BRIDGE_STOPPED"
        : null,
    };
  }

  private async startInternal(): Promise<SpoutBridgeStatus> {
    this.stopping = false;
    this.statusSnapshot = {
      ...this.statusSnapshot,
      state: "starting",
      lastErrorCode: null,
      frameReady: false,
      frameAgeMilliseconds: null,
    };
    const port = await reserveLoopbackPort();
    const endpoint = `http://127.0.0.1:${port}`;
    this.statusSnapshot = {
      ...this.statusSnapshot,
      endpoint,
      frameUrl: `${endpoint}/frame.png`,
    };
    const scriptPath = join(this.options.repoRoot, "tools", "dev", "vts_spout_bridge.py");
    const args = [
      "run",
      "--no-project",
      "--isolated",
      "--python",
      "3.13",
      "--with",
      "liru==0.2.6",
      "--with",
      "moderngl==5.12.0",
      "--with",
      "Pillow==11.3.0",
      "python",
      scriptPath,
      "--port",
      String(port),
      "--sender",
      SENDER_NAME,
    ];
    const child = spawn(this.options.uvPath ?? "uv", args, {
      cwd: this.options.repoRoot,
      windowsHide: true,
      stdio: ["ignore", "pipe", "pipe"],
      shell: false,
    });
    this.child = child;
    child.stderr.on("data", (chunk: Buffer | string) => {
      const message = String(chunk).replace(/\s+/g, " ").trim().slice(0, 240);
      if (message) {
        this.options.log?.("warn", `[hina-spout-worker] ${message}`);
      }
    });
    child.on("error", (error) => {
      const code = errorCode(error);
      this.statusSnapshot = {
        ...this.statusSnapshot,
        state: "error",
        lastErrorCode: code,
        frameReady: false,
        frameAgeMilliseconds: null,
      };
      this.options.log?.("error", `[hina-spout] ${code}`);
    });

    let childExited = false;
    let childExitCode: number | null = null;
    child.once("exit", (code) => {
      childExited = true;
      childExitCode = code;
      if (this.stopping) return;
      const message = `E_SPOUT_BRIDGE_EXIT:${code ?? "unknown"}`;
      this.statusSnapshot = {
        ...this.statusSnapshot,
        state: "error",
        lastErrorCode: message,
        frameReady: false,
        frameAgeMilliseconds: null,
      };
    });
    this.stdout = createInterface({ input: child.stdout });
    this.stdout.on("line", (line) => {
      const parsed = parseWorkerLine(line);
      if (!parsed) return;
      this.handleWorkerLine(parsed);
    });

    const ready = new Promise<SpoutBridgeStatus>((resolve, reject) => {
      const deadline = Date.now() + START_TIMEOUT_MILLISECONDS;
      const poll = async (): Promise<void> => {
        if (childExited) {
          reject(new Error(`E_SPOUT_BRIDGE_EXIT:${childExitCode ?? "unknown"}`));
          return;
        }
        try {
          const controller = new AbortController();
          const timer = setTimeout(() => controller.abort(), 350);
          const response = await fetch(`${endpoint}/health`, {
            signal: controller.signal,
          }).finally(() => clearTimeout(timer));
          if (response.ok) {
            this.options.log?.(
              "info",
              `[hina-spout] bridge ready on 127.0.0.1:${port}`,
            );
            resolve(this.status());
            return;
          }
        } catch {
          // Worker dependency resolution and native initialization are still
          // in progress. Keep polling within the bounded startup deadline.
        }
        if (Date.now() >= deadline) {
          reject(new Error("E_SPOUT_BRIDGE_START_TIMEOUT"));
          return;
        }
        setTimeout(() => void poll(), 100);
      };
      void poll();
    });

    try {
      const status = await ready;
      this.startStatusPolling();
      return status;
    } catch (error) {
      if (this.child === child && !child.killed) {
        await terminateProcessTree(child);
      }
      const code = errorCode(error);
      this.statusSnapshot = {
        ...this.statusSnapshot,
        state: "error",
        lastErrorCode: code,
        frameReady: false,
        frameAgeMilliseconds: null,
      };
      throw error instanceof Error ? error : new Error(code);
    }
  }

  private handleWorkerLine(line: WorkerLine): void {
    const payload = line.payload;
    if (line.kind === "READY") {
      const port = boundedPort(payload.port);
      if (
        port === null
        || this.statusSnapshot.endpoint !== `http://127.0.0.1:${port}`
      ) {
        this.statusSnapshot = {
          ...this.statusSnapshot,
          state: "error",
          frameReady: false,
          frameAgeMilliseconds: null,
          lastErrorCode: "E_SPOUT_BRIDGE_PORT",
        };
        return;
      }
      return;
    }
    if (line.kind === "ERROR") {
      const code = boundedString(payload.errorCode, 96) ?? "E_SPOUT_WORKER";
      this.statusSnapshot = {
        ...this.statusSnapshot,
        state: "error",
        lastErrorCode: code,
        frameReady: false,
        frameAgeMilliseconds: null,
      };
      this.options.log?.("error", `[hina-spout] ${code}`);
      return;
    }
    if (payload.frameReady === true) {
      this.statusSnapshot = {
        ...this.statusSnapshot,
        state: "ready",
        frameReady: true,
        frameAgeMilliseconds: 0,
        width: boundedInteger(payload.width, this.statusSnapshot.width),
        height: boundedInteger(payload.height, this.statusSnapshot.height),
        transparent: payload.transparent === true,
      };
    }
  }

  private startStatusPolling(): void {
    if (this.statusPollTimer) clearInterval(this.statusPollTimer);
    this.statusPollTimer = setInterval(() => {
      void this.refreshStatusFromWorker();
    }, STATUS_POLL_MILLISECONDS);
    void this.refreshStatusFromWorker();
  }

  private async refreshStatusFromWorker(): Promise<void> {
    const endpoint = this.statusSnapshot.endpoint;
    if (!endpoint || this.stopping) return;
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 450);
    try {
      const response = await fetch(`${endpoint}/v1/status`, {
        signal: controller.signal,
      });
      if (!response.ok) throw new Error("E_SPOUT_STATUS_HTTP");
      const payload: unknown = await response.json();
      if (!payload || typeof payload !== "object" || Array.isArray(payload)) {
        throw new Error("E_SPOUT_STATUS_SCHEMA");
      }
      const record = payload as Record<string, unknown>;
      const workerState = boundedString(record.state, 32);
      const nextState: SpoutBridgeState =
        workerState === "ready"
          ? "ready"
          : workerState === "degraded"
            ? "degraded"
            : workerState === "error"
              ? "error"
              : this.statusSnapshot.state;
      const frameReady = record.frameReady === true && nextState === "ready";
      const sequence = boundedInteger(
        record.frameSequence,
        this.statusSnapshot.frameSequence,
      );
      const frameAgeMilliseconds = boundedNonNegativeNumber(
        record.frameAgeMilliseconds,
        this.statusSnapshot.frameAgeMilliseconds,
      );
      const frameStale = isFrameStale(frameReady, frameAgeMilliseconds);
      this.statusSnapshot = {
        ...this.statusSnapshot,
        state: frameStale ? "degraded" : nextState,
        frameReady: frameStale ? false : frameReady,
        frameSequence: sequence,
        frameAgeMilliseconds,
        width: boundedInteger(record.width, this.statusSnapshot.width),
        height: boundedInteger(record.height, this.statusSnapshot.height),
        transparent: record.transparent === true,
        lastErrorCode: frameStale
          ? "E_SPOUT_FRAME_STALE"
          : boundedString(record.errorCode, 96),
      };
    } catch (error) {
      if (this.statusSnapshot.state === "ready" || this.statusSnapshot.frameReady) {
        this.statusSnapshot = {
          ...this.statusSnapshot,
          state: "degraded",
          frameReady: false,
          frameAgeMilliseconds: null,
          lastErrorCode: errorCode(error),
        };
      }
    } finally {
      clearTimeout(timer);
    }
  }
}

export { isFrameStale, parseWorkerLine };
