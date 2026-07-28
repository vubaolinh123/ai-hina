export const CAPTURE_GRANT_TTL_MILLISECONDS = 60_000;
export const MAX_CAPTURE_SOURCES = 48;
export const MAX_CAPTURE_PREVIEW_DATA_URL_CHARS = 384_000;
export const CAPTURE_MAX_SIDES = Object.freeze([640, 960, 1_280] as const);

export type CaptureMaxSide = (typeof CAPTURE_MAX_SIDES)[number];
export type CaptureSourceKind = "screen" | "window";

export type CaptureSourceCandidate = {
  sourceId: string;
  name: string;
  kind: CaptureSourceKind;
  previewDataUrl: string;
  previewWidth: number;
  previewHeight: number;
};

export type PublicCaptureSource = Omit<CaptureSourceCandidate, "sourceId"> & {
  sourceToken: string;
};

export type CaptureSourceListing = {
  grantSessionId: string;
  expiresAtUnixMilliseconds: number;
  sourceCount: number;
  sources: PublicCaptureSource[];
  persistence: false;
};

export type FullFrameCaptureRequest = {
  sessionId: string;
  grantSessionId: string;
  sourceToken: string;
  maxSide: CaptureMaxSide;
  label: string | null;
  analyzeVision: boolean;
  visionQuestion: string | null;
};

type CaptureGrantSession = {
  expiresAtUnixMilliseconds: number;
  sources: Map<string, CaptureSourceCandidate>;
};

type Clock = () => number;
type UuidFactory = () => string;

const UUID_PATTERN =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[4-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/iu;

export class CaptureGrantStore {
  readonly #sessions = new Map<string, CaptureGrantSession>();
  readonly #clock: Clock;
  readonly #uuid: UuidFactory;
  readonly #ttlMilliseconds: number;
  readonly #maximumSources: number;

  constructor(options: {
    clock?: Clock;
    uuid?: UuidFactory;
    ttlMilliseconds?: number;
    maximumSources?: number;
  } = {}) {
    this.#clock = options.clock ?? Date.now;
    this.#uuid = options.uuid ?? (() => crypto.randomUUID());
    this.#ttlMilliseconds = options.ttlMilliseconds ?? CAPTURE_GRANT_TTL_MILLISECONDS;
    this.#maximumSources = options.maximumSources ?? MAX_CAPTURE_SOURCES;
    if (
      !Number.isInteger(this.#ttlMilliseconds)
      || this.#ttlMilliseconds < 1_000
      || this.#ttlMilliseconds > CAPTURE_GRANT_TTL_MILLISECONDS
      || !Number.isInteger(this.#maximumSources)
      || this.#maximumSources < 1
      || this.#maximumSources > MAX_CAPTURE_SOURCES
    ) {
      throw new Error("E_DESKTOP_CAPTURE_CONFIG: capture grant bounds are invalid");
    }
  }

  issue(candidates: readonly CaptureSourceCandidate[]): CaptureSourceListing {
    this.#deleteExpired();
    // The operator only needs the latest picker result. Replacing the previous
    // grant keeps transient preview pixels and secret source IDs strictly bounded.
    this.#sessions.clear();
    if (!Array.isArray(candidates) || candidates.length < 1) {
      throw new Error("E_DESKTOP_CAPTURE_SOURCES: no capturable source is available");
    }
    const bounded = candidates.slice(0, this.#maximumSources);
    const grantSessionId = this.#uuid();
    assertUuid(grantSessionId, "grant session");
    const expiresAtUnixMilliseconds = this.#clock() + this.#ttlMilliseconds;
    const stored = new Map<string, CaptureSourceCandidate>();
    const sources = bounded.map((candidate) => {
      const validated = validateCandidate(candidate);
      const sourceToken = this.#uuid();
      assertUuid(sourceToken, "source token");
      stored.set(sourceToken, validated);
      return {
        sourceToken,
        name: validated.name,
        kind: validated.kind,
        previewDataUrl: validated.previewDataUrl,
        previewWidth: validated.previewWidth,
        previewHeight: validated.previewHeight,
      };
    });
    this.#sessions.set(grantSessionId, {
      expiresAtUnixMilliseconds,
      sources: stored,
    });
    return {
      grantSessionId,
      expiresAtUnixMilliseconds,
      sourceCount: sources.length,
      sources,
      persistence: false,
    };
  }

  consume(grantSessionId: unknown, sourceToken: unknown): CaptureSourceCandidate {
    assertUuid(grantSessionId, "grant session");
    assertUuid(sourceToken, "source token");
    this.#deleteExpired();
    const session = this.#sessions.get(grantSessionId);
    if (!session) {
      throw new Error("E_DESKTOP_CAPTURE_GRANT: capture grant is missing or expired");
    }
    const source = session.sources.get(sourceToken);
    if (!source) {
      throw new Error("E_DESKTOP_CAPTURE_SOURCE: source token is not allowlisted");
    }
    this.#sessions.delete(grantSessionId);
    return source;
  }

  clear(): void {
    this.#sessions.clear();
  }

  #deleteExpired(): void {
    const now = this.#clock();
    for (const [sessionId, session] of this.#sessions) {
      if (session.expiresAtUnixMilliseconds <= now) {
        this.#sessions.delete(sessionId);
      }
    }
  }
}

export function validateFullFrameCaptureRequest(
  raw: unknown,
): FullFrameCaptureRequest {
  if (!isRecord(raw)) {
    throw new Error("E_DESKTOP_CAPTURE_REQUEST: capture request must be an object");
  }
  const allowed = new Set([
    "sessionId",
    "grantSessionId",
    "sourceToken",
    "maxSide",
    "label",
    "analyzeVision",
    "visionQuestion",
  ]);
  if (
    Object.keys(raw).length !== allowed.size
    || Object.keys(raw).some((key) => !allowed.has(key))
  ) {
    throw new Error("E_DESKTOP_CAPTURE_REQUEST: capture request fields are invalid");
  }
  assertUuid(raw.sessionId, "chat session");
  assertUuid(raw.grantSessionId, "grant session");
  assertUuid(raw.sourceToken, "source token");
  if (
    typeof raw.maxSide !== "number"
    || !CAPTURE_MAX_SIDES.includes(raw.maxSide as CaptureMaxSide)
  ) {
    throw new Error("E_DESKTOP_CAPTURE_REQUEST: maxSide must be 640, 960 or 1280");
  }
  if (typeof raw.analyzeVision !== "boolean") {
    throw new Error("E_DESKTOP_CAPTURE_REQUEST: vision analysis flag must be boolean");
  }
  const label = validateOptionalText(raw.label, 120, "label");
  const visionQuestion = validateOptionalText(
    raw.visionQuestion,
    500,
    "vision question",
  );
  if (!raw.analyzeVision && visionQuestion !== null) {
    throw new Error(
      "E_DESKTOP_CAPTURE_REQUEST: vision question requires vision analysis",
    );
  }
  return {
    sessionId: raw.sessionId,
    grantSessionId: raw.grantSessionId,
    sourceToken: raw.sourceToken,
    maxSide: raw.maxSide as CaptureMaxSide,
    label,
    analyzeVision: raw.analyzeVision,
    visionQuestion,
  };
}

export function fitWithinLongEdge(
  width: number,
  height: number,
  maxSide: CaptureMaxSide,
): { width: number; height: number } {
  if (
    !Number.isInteger(width)
    || !Number.isInteger(height)
    || width < 1
    || height < 1
    || !CAPTURE_MAX_SIDES.includes(maxSide)
  ) {
    throw new Error("E_DESKTOP_CAPTURE_IMAGE: image dimensions are invalid");
  }
  const scale = Math.min(1, maxSide / Math.max(width, height));
  return {
    width: Math.max(1, Math.round(width * scale)),
    height: Math.max(1, Math.round(height * scale)),
  };
}

function validateCandidate(candidate: CaptureSourceCandidate): CaptureSourceCandidate {
  if (!isRecord(candidate)) {
    throw new Error("E_DESKTOP_CAPTURE_SOURCES: source is invalid");
  }
  const sourceId = validateRequiredText(candidate.sourceId, 512, "source ID");
  const name = validateRequiredText(candidate.name, 160, "source name");
  if (candidate.kind !== "screen" && candidate.kind !== "window") {
    throw new Error("E_DESKTOP_CAPTURE_SOURCES: source kind is invalid");
  }
  if (
    typeof candidate.previewDataUrl !== "string"
    || !candidate.previewDataUrl.startsWith("data:image/png;base64,")
    || candidate.previewDataUrl.length > MAX_CAPTURE_PREVIEW_DATA_URL_CHARS
  ) {
    throw new Error("E_DESKTOP_CAPTURE_SOURCES: preview is invalid or oversized");
  }
  if (
    !Number.isInteger(candidate.previewWidth)
    || !Number.isInteger(candidate.previewHeight)
    || candidate.previewWidth < 1
    || candidate.previewHeight < 1
    || candidate.previewWidth > 640
    || candidate.previewHeight > 640
  ) {
    throw new Error("E_DESKTOP_CAPTURE_SOURCES: preview dimensions are invalid");
  }
  return {
    sourceId,
    name,
    kind: candidate.kind,
    previewDataUrl: candidate.previewDataUrl,
    previewWidth: candidate.previewWidth,
    previewHeight: candidate.previewHeight,
  };
}

function validateRequiredText(
  raw: unknown,
  maximumCharacters: number,
  label: string,
): string {
  if (typeof raw !== "string" || raw !== raw.trim()) {
    throw new Error(`E_DESKTOP_CAPTURE_REQUEST: ${label} is invalid`);
  }
  const cleaned = raw.replace(/[\u0000-\u001f\u007f]/gu, "").trim();
  if (cleaned.length < 1 || cleaned.length > maximumCharacters) {
    throw new Error(`E_DESKTOP_CAPTURE_REQUEST: ${label} is invalid`);
  }
  return cleaned;
}

function validateOptionalText(
  raw: unknown,
  maximumCharacters: number,
  label: string,
): string | null {
  if (raw === null) return null;
  return validateRequiredText(raw, maximumCharacters, label);
}

function assertUuid(raw: unknown, label: string): asserts raw is string {
  if (typeof raw !== "string" || !UUID_PATTERN.test(raw)) {
    throw new Error(`E_DESKTOP_CAPTURE_REQUEST: ${label} is invalid`);
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
