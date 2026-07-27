const VTS_ENDPOINT = "ws://127.0.0.1:8001";
const API_NAME = "VTubeStudioPublicAPI";
const API_VERSION = "1.0";
const REQUEST_TIMEOUT_MILLISECONDS = 5_000;
const MAX_MESSAGE_BYTES = 262_144;
const MAX_TOKEN_CHARACTERS = 2_048;
export const VTS_TOKEN_STATE_MAX_BYTES = 4_096;

export type VTubeStudioState =
  | "offline"
  | "connecting"
  | "needs_authorization"
  | "connected"
  | "error";

export type VTubeStudioHotkey = {
  id: string;
  name: string;
  type: string;
};

export type VTubeStudioStatus = {
  available: true;
  endpoint: typeof VTS_ENDPOINT;
  state: VTubeStudioState;
  connected: boolean;
  authenticated: boolean;
  authorizationStored: boolean;
  model: {
    loaded: boolean;
    id: string | null;
    name: string | null;
    vtsModelName: string | null;
  };
  hotkeys: VTubeStudioHotkey[];
  lastErrorCode: string | null;
  renderer: "external-vtube-studio";
  offlineFallback: "hina-vrm-widget";
  hiyoriBundled: false;
};

export type VTubeStudioTokenStore = {
  load(): Promise<string | null>;
  save(token: string): Promise<void>;
  clear(): Promise<void>;
};

type VTubeStudioPreset = "chat" | "screen" | "react";

type WebSocketEvent = {
  data?: unknown;
};

type WebSocketLike = {
  readonly readyState: number;
  addEventListener(
    type: "open" | "error" | "close" | "message",
    listener: (event: WebSocketEvent) => void,
  ): void;
  send(data: string): void;
  close(code?: number, reason?: string): void;
};

type PendingRequest = {
  resolve(value: Record<string, unknown>): void;
  reject(reason: Error): void;
  timer: NodeJS.Timeout;
};

type RequestEnvelope = {
  apiName: typeof API_NAME;
  apiVersion: typeof API_VERSION;
  requestID: string;
  messageType: string;
  data: Record<string, unknown>;
};

const MOVE_PRESETS: Readonly<Record<VTubeStudioPreset, Record<string, number | boolean>>> =
  Object.freeze({
    chat: Object.freeze({
      timeInSeconds: 0.8,
      valuesAreRelativeToModel: false,
      positionX: 0.35,
      positionY: -1.35,
      rotation: 0,
      size: -35,
    }),
    screen: Object.freeze({
      timeInSeconds: 0.8,
      valuesAreRelativeToModel: false,
      positionX: 0.64,
      positionY: -1.55,
      rotation: 0,
      size: -44,
    }),
    react: Object.freeze({
      timeInSeconds: 0.8,
      valuesAreRelativeToModel: false,
      positionX: 0.7,
      positionY: -1.68,
      rotation: 0,
      size: -48,
    }),
  });

export class VTubeStudioClient {
  private socket: WebSocketLike | null = null;
  private pending = new Map<string, PendingRequest>();
  private connecting: Promise<VTubeStudioStatus> | null = null;
  private state: VTubeStudioState = "offline";
  private authenticated = false;
  private authorizationStored = false;
  private lastErrorCode: string | null = null;
  private model: VTubeStudioStatus["model"] = {
    loaded: false,
    id: null,
    name: null,
    vtsModelName: null,
  };
  private hotkeys: VTubeStudioHotkey[] = [];

  constructor(
    private readonly tokenStore: VTubeStudioTokenStore,
    private readonly webSocketFactory: (url: string) => WebSocketLike = (
      url,
    ) => new WebSocket(url),
  ) {}

  status(): VTubeStudioStatus {
    return {
      available: true,
      endpoint: VTS_ENDPOINT,
      state: this.state,
      connected: this.isSocketOpen(),
      authenticated: this.authenticated,
      authorizationStored: this.authorizationStored,
      model: { ...this.model },
      hotkeys: this.hotkeys.map((item) => ({ ...item })),
      lastErrorCode: this.lastErrorCode,
      renderer: "external-vtube-studio",
      offlineFallback: "hina-vrm-widget",
      hiyoriBundled: false,
    };
  }

  connect(requestPermission = false): Promise<VTubeStudioStatus> {
    if (this.connecting) return this.connecting;
    this.connecting = this.connectInternal(requestPermission).finally(() => {
      this.connecting = null;
    });
    return this.connecting;
  }

  async disconnect(): Promise<VTubeStudioStatus> {
    this.closeSocket();
    this.state = "offline";
    this.authenticated = false;
    this.lastErrorCode = null;
    this.model = { loaded: false, id: null, name: null, vtsModelName: null };
    this.hotkeys = [];
    return this.status();
  }

  async refresh(): Promise<VTubeStudioStatus> {
    this.assertAuthenticated();
    await this.refreshModelAndHotkeys();
    return this.status();
  }

  async triggerHotkey(hotkeyId: unknown): Promise<VTubeStudioStatus> {
    this.assertAuthenticated();
    if (
      typeof hotkeyId !== "string"
      || !this.hotkeys.some((hotkey) => hotkey.id === hotkeyId)
    ) {
      throw new Error(
        "E_VTS_HOTKEY: hotkey must come from the current model allowlist",
      );
    }
    await this.request("HotkeyTriggerRequest", { hotkeyID: hotkeyId });
    return this.status();
  }

  async moveModel(preset: unknown): Promise<VTubeStudioStatus> {
    this.assertAuthenticated();
    if (
      typeof preset !== "string"
      || !Object.hasOwn(MOVE_PRESETS, preset)
    ) {
      throw new Error("E_VTS_MOVE: model position preset is invalid");
    }
    await this.request(
      "MoveModelRequest",
      MOVE_PRESETS[preset as VTubeStudioPreset],
    );
    return this.status();
  }

  private async connectInternal(
    requestPermission: boolean,
  ): Promise<VTubeStudioStatus> {
    if (this.isSocketOpen() && this.authenticated) {
      await this.refreshModelAndHotkeys();
      return this.status();
    }
    this.closeSocket();
    this.state = "connecting";
    this.lastErrorCode = null;
    try {
      await this.openSocket();
      let token = await this.tokenStore.load();
      this.authorizationStored = token !== null;
      if (token === null) {
        if (!requestPermission) {
          this.state = "needs_authorization";
          this.closeSocket({ preserveState: true });
          return this.status();
        }
        const tokenResponse = await this.request(
          "AuthenticationTokenRequest",
          {
            pluginName: "Hina AI Local Companion",
            pluginDeveloper: "Hina AI",
          },
        );
        token = validateAuthenticationToken(tokenResponse.authenticationToken);
        await this.tokenStore.save(token);
        this.authorizationStored = true;
      }
      const authentication = await this.request("AuthenticationRequest", {
        pluginName: "Hina AI Local Companion",
        pluginDeveloper: "Hina AI",
        authenticationToken: token,
      });
      if (authentication.authenticated !== true) {
        await this.tokenStore.clear();
        this.authorizationStored = false;
        this.state = "needs_authorization";
        this.lastErrorCode = "E_VTS_AUTH_REJECTED";
        this.closeSocket({ preserveState: true });
        return this.status();
      }
      this.authenticated = true;
      this.state = "connected";
      await this.refreshModelAndHotkeys();
      return this.status();
    } catch (error) {
      const code = errorCode(error);
      this.lastErrorCode = code;
      this.state = code === "E_VTS_OFFLINE" ? "offline" : "error";
      this.authenticated = false;
      this.closeSocket({ preserveState: true });
      throw error;
    }
  }

  private async openSocket(): Promise<void> {
    let socket: WebSocketLike;
    try {
      socket = this.webSocketFactory(VTS_ENDPOINT);
    } catch {
      throw new Error(
        "E_VTS_OFFLINE: VTube Studio is not listening on 127.0.0.1:8001",
      );
    }
    this.socket = socket;
    socket.addEventListener("message", (event) => {
      this.handleMessage(event.data);
    });
    socket.addEventListener("close", () => {
      if (this.socket !== socket) return;
      this.rejectPending("E_VTS_OFFLINE: VTube Studio disconnected");
      this.socket = null;
      this.authenticated = false;
      if (this.state === "connected" || this.state === "connecting") {
        this.state = "offline";
        this.lastErrorCode = "E_VTS_OFFLINE";
      }
    });
    await new Promise<void>((resolve, reject) => {
      const timer = setTimeout(() => {
        reject(
          new Error(
            "E_VTS_OFFLINE: timed out connecting to VTube Studio on loopback",
          ),
        );
      }, REQUEST_TIMEOUT_MILLISECONDS);
      const settle = (callback: () => void): void => {
        clearTimeout(timer);
        callback();
      };
      socket.addEventListener("open", () => settle(resolve));
      socket.addEventListener("error", () => settle(() => reject(
        new Error(
          "E_VTS_OFFLINE: VTube Studio is not listening on 127.0.0.1:8001",
        ),
      )));
    });
  }

  private async refreshModelAndHotkeys(): Promise<void> {
    const current = await this.request("CurrentModelRequest", {});
    this.model = {
      loaded: current.modelLoaded === true,
      id: boundedNullableString(current.modelID, 256),
      name: boundedNullableString(current.modelName, 256),
      vtsModelName: boundedNullableString(current.vtsModelName, 256),
    };
    if (!this.model.loaded) {
      this.hotkeys = [];
      return;
    }
    const response = await this.request("HotkeysInCurrentModelRequest", {
      modelID: this.model.id ?? "",
      live2DItemFileName: "",
    });
    const rawHotkeys = Array.isArray(response.availableHotkeys)
      ? response.availableHotkeys
      : [];
    this.hotkeys = rawHotkeys.slice(0, 128).flatMap((item) => {
      if (!isRecord(item)) return [];
      const id = boundedNullableString(item.hotkeyID, 256);
      const name = boundedNullableString(item.name, 256);
      const type = boundedNullableString(item.type, 128);
      return id && name ? [{ id, name, type: type ?? "unknown" }] : [];
    });
  }

  private request(
    messageType: string,
    data: Record<string, unknown>,
  ): Promise<Record<string, unknown>> {
    if (!this.isSocketOpen() || this.socket === null) {
      return Promise.reject(
        new Error("E_VTS_OFFLINE: VTube Studio connection is unavailable"),
      );
    }
    const requestID = crypto.randomUUID();
    const envelope: RequestEnvelope = {
      apiName: API_NAME,
      apiVersion: API_VERSION,
      requestID,
      messageType,
      data,
    };
    const encoded = JSON.stringify(envelope);
    if (new TextEncoder().encode(encoded).byteLength > MAX_MESSAGE_BYTES) {
      return Promise.reject(
        new Error("E_VTS_PROTOCOL: request exceeds the desktop limit"),
      );
    }
    return new Promise<Record<string, unknown>>((resolve, reject) => {
      const timer = setTimeout(() => {
        this.pending.delete(requestID);
        reject(new Error(`E_VTS_TIMEOUT: ${messageType} timed out`));
      }, REQUEST_TIMEOUT_MILLISECONDS);
      this.pending.set(requestID, { resolve, reject, timer });
      try {
        this.socket?.send(encoded);
      } catch {
        clearTimeout(timer);
        this.pending.delete(requestID);
        reject(new Error("E_VTS_OFFLINE: VTube Studio send failed"));
      }
    });
  }

  private handleMessage(raw: unknown): void {
    if (typeof raw !== "string") {
      this.rejectPending("E_VTS_PROTOCOL: binary messages are unsupported");
      return;
    }
    if (new TextEncoder().encode(raw).byteLength > MAX_MESSAGE_BYTES) {
      this.rejectPending("E_VTS_PROTOCOL: response exceeds the desktop limit");
      return;
    }
    let parsed: unknown;
    try {
      parsed = JSON.parse(raw);
    } catch {
      this.rejectPending("E_VTS_PROTOCOL: response is invalid JSON");
      return;
    }
    if (!isRecord(parsed) || typeof parsed.requestID !== "string") return;
    const pending = this.pending.get(parsed.requestID);
    if (!pending) return;
    clearTimeout(pending.timer);
    this.pending.delete(parsed.requestID);
    if (parsed.messageType === "APIError") {
      const data = isRecord(parsed.data) ? parsed.data : {};
      const errorId = typeof data.errorID === "number" ? data.errorID : "unknown";
      const message = boundedNullableString(data.message, 192) ?? "VTube Studio API error";
      pending.reject(new Error(`E_VTS_API_${errorId}: ${message}`));
      return;
    }
    if (!isRecord(parsed.data)) {
      pending.reject(new Error("E_VTS_PROTOCOL: response data is invalid"));
      return;
    }
    pending.resolve(parsed.data);
  }

  private assertAuthenticated(): void {
    if (!this.isSocketOpen() || !this.authenticated) {
      throw new Error(
        "E_VTS_AUTH_REQUIRED: connect and authorize VTube Studio first",
      );
    }
  }

  private isSocketOpen(): boolean {
    return this.socket?.readyState === 1;
  }

  private closeSocket(options: { preserveState?: boolean } = {}): void {
    const socket = this.socket;
    this.socket = null;
    this.rejectPending("E_VTS_OFFLINE: VTube Studio connection closed");
    if (socket) {
      try {
        socket.close(1000, "Hina desktop disconnect");
      } catch {
        // A closing/closed WebSocket needs no further action.
      }
    }
    this.authenticated = false;
    if (!options.preserveState) this.state = "offline";
  }

  private rejectPending(message: string): void {
    for (const pending of this.pending.values()) {
      clearTimeout(pending.timer);
      pending.reject(new Error(message));
    }
    this.pending.clear();
  }
}

export function parseVTubeStudioTokenState(raw: string): string | null {
  if (
    typeof raw !== "string"
    || new TextEncoder().encode(raw).byteLength > VTS_TOKEN_STATE_MAX_BYTES
  ) {
    return null;
  }
  try {
    const parsed: unknown = JSON.parse(raw);
    if (
      !isRecord(parsed)
      || Object.keys(parsed).length !== 2
      || parsed.schemaVersion !== "1.0"
    ) {
      return null;
    }
    return validateAuthenticationToken(parsed.authenticationToken);
  } catch {
    return null;
  }
}

export function serializeVTubeStudioTokenState(token: string): string {
  const validated = validateAuthenticationToken(token);
  return JSON.stringify({
    schemaVersion: "1.0",
    authenticationToken: validated,
  });
}

function validateAuthenticationToken(value: unknown): string {
  if (
    typeof value !== "string"
    || value.length < 1
    || value.length > MAX_TOKEN_CHARACTERS
    || [...value].some((char) => char.charCodeAt(0) < 0x20)
  ) {
    throw new Error("E_VTS_AUTH_TOKEN: VTube Studio returned an invalid token");
  }
  return value;
}

function boundedNullableString(value: unknown, maximum: number): string | null {
  if (typeof value !== "string") return null;
  const cleaned = [...value]
    .filter((char) => char.charCodeAt(0) >= 0x20 && char.charCodeAt(0) !== 0x7F)
    .join("")
    .trim();
  return cleaned ? cleaned.slice(0, maximum) : null;
}

function errorCode(error: unknown): string {
  if (!(error instanceof Error)) return "E_VTS_OPERATION";
  const match = /^([A-Z0-9_]+)(?::|$)/.exec(error.message);
  return match?.[1] ?? "E_VTS_OPERATION";
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
