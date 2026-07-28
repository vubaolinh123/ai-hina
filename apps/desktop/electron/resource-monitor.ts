type JsonObject = Record<string, unknown>;

export type ModelTransition = {
  sequence: number;
  modelId: string;
  role: string;
  name: string | null;
  fromState: string | null;
  toState: string;
  action: "loaded" | "unloaded" | "state-changed" | "observed";
  occurredAtUnixMilliseconds: number;
};

const MODEL_STATES = new Set([
  "loaded",
  "loading",
  "unloaded",
  "unavailable",
  "unconfigured",
  "cloud-ready",
]);
const LOADED_STATES = new Set(["loaded", "loading", "cloud-ready"]);

export class ModelTransitionTracker {
  readonly limit: number;
  #previous = new Map<string, { state: string; role: string; name: string | null }>();
  #transitions: ModelTransition[] = [];
  #sequence = 0;

  constructor(limit = 100) {
    if (!Number.isInteger(limit) || limit < 1 || limit > 1_000) {
      throw new Error("E_DESKTOP_RESOURCE_HISTORY: transition limit is invalid");
    }
    this.limit = limit;
  }

  observe(rawModels: unknown, now = Date.now()): ModelTransition[] {
    const models = parseModels(rawModels);
    const next = new Map<string, { state: string; role: string; name: string | null }>();
    for (const model of models) {
      next.set(model.id, {
        state: model.state,
        role: model.role,
        name: model.name,
      });
      const previous = this.#previous.get(model.id);
      if (previous?.state === model.state) continue;
      const action = transitionAction(previous?.state ?? null, model.state);
      this.#sequence += 1;
      this.#transitions.push({
        sequence: this.#sequence,
        modelId: model.id,
        role: model.role,
        name: model.name,
        fromState: previous?.state ?? null,
        toState: model.state,
        action,
        occurredAtUnixMilliseconds: normalizeTimestamp(now),
      });
    }
    this.#previous = next;
    if (this.#transitions.length > this.limit) {
      this.#transitions.splice(0, this.#transitions.length - this.limit);
    }
    return this.snapshot();
  }

  snapshot(): ModelTransition[] {
    return this.#transitions.map((transition) => ({ ...transition }));
  }
}

export function augmentResourceStatus(
  raw: unknown,
  tracker: ModelTransitionTracker,
  memory = process.memoryUsage(),
): JsonObject {
  if (!isObject(raw) || raw.schemaVersion !== "1.0" || !Array.isArray(raw.models)) {
    throw new Error("E_DESKTOP_RESOURCE_RESPONSE: resource status is invalid");
  }
  const transitions = tracker.observe(raw.models);
  const processes = isObject(raw.processes) ? raw.processes : {};
  return {
    ...raw,
    processes: {
      ...processes,
      desktopMain: {
        label: "Electron desktop main process",
        rssMiB: bytesToMiB(memory.rss),
        heapUsedMiB: bytesToMiB(memory.heapUsed),
        externalMiB: bytesToMiB(memory.external),
      },
    },
    modelTransitions: transitions,
    transitionHistory: {
      persistence: false,
      limit: tracker.limit,
      count: transitions.length,
    },
  };
}

function parseModels(
  value: unknown,
): Array<{ id: string; role: string; name: string | null; state: string }> {
  if (!Array.isArray(value) || value.length > 64) {
    throw new Error("E_DESKTOP_RESOURCE_RESPONSE: model list is invalid");
  }
  return value.map((item) => {
    if (!isObject(item)) {
      throw new Error("E_DESKTOP_RESOURCE_RESPONSE: model record is invalid");
    }
    const id = boundedText(item.id, 64);
    const role = boundedText(item.role, 96);
    const name = item.name === null ? null : boundedText(item.name, 160);
    const state = boundedText(item.state, 32);
    if (!MODEL_STATES.has(state)) {
      throw new Error("E_DESKTOP_RESOURCE_RESPONSE: model state is invalid");
    }
    return { id, role, name, state };
  });
}

function transitionAction(
  fromState: string | null,
  toState: string,
): ModelTransition["action"] {
  if (fromState === null) return "observed";
  if (!LOADED_STATES.has(fromState) && LOADED_STATES.has(toState)) return "loaded";
  if (LOADED_STATES.has(fromState) && !LOADED_STATES.has(toState)) return "unloaded";
  return "state-changed";
}

function boundedText(value: unknown, maximum: number): string {
  if (
    typeof value !== "string"
    || value.length < 1
    || value.length > maximum
    || /[\u0000-\u001f\u007f]/u.test(value)
  ) {
    throw new Error("E_DESKTOP_RESOURCE_RESPONSE: text field is invalid");
  }
  return value;
}

function normalizeTimestamp(value: number): number {
  return Number.isFinite(value) && value >= 0 ? Math.round(value) : Date.now();
}

function bytesToMiB(value: number): number {
  return Math.round((value / (1024 * 1024)) * 10) / 10;
}

function isObject(value: unknown): value is JsonObject {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
