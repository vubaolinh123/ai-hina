export const WIDGET_STATE_SCHEMA_VERSION = "1.0";
export const WIDGET_STATE_MAX_BYTES = 1_024;

const MAX_SCREEN_COORDINATE = 1_000_000;

export type Point = Readonly<{
  x: number;
  y: number;
}>;

export type Size = Readonly<{
  width: number;
  height: number;
}>;

export type WorkArea = Readonly<{
  x: number;
  y: number;
  width: number;
  height: number;
}>;

function validCoordinate(value: unknown): value is number {
  return (
    Number.isSafeInteger(value)
    && Math.abs(value as number) <= MAX_SCREEN_COORDINATE
  );
}

function validDimension(value: number): boolean {
  return Number.isSafeInteger(value) && value > 0 && value <= 100_000;
}

function validWorkArea(area: WorkArea): boolean {
  return (
    validCoordinate(area.x)
    && validCoordinate(area.y)
    && validDimension(area.width)
    && validDimension(area.height)
  );
}

export function parseWidgetPosition(raw: string): Point | null {
  if (
    typeof raw !== "string"
    || Buffer.byteLength(raw, "utf8") > WIDGET_STATE_MAX_BYTES
  ) {
    return null;
  }
  try {
    const value: unknown = JSON.parse(raw);
    if (!value || typeof value !== "object" || Array.isArray(value)) {
      return null;
    }
    const record = value as Record<string, unknown>;
    if (
      Object.keys(record).sort().join(",") !== "schemaVersion,x,y"
      || record.schemaVersion !== WIDGET_STATE_SCHEMA_VERSION
      || !validCoordinate(record.x)
      || !validCoordinate(record.y)
    ) {
      return null;
    }
    return { x: record.x, y: record.y };
  } catch {
    return null;
  }
}

export function serializeWidgetPosition(position: Point): string {
  if (!validCoordinate(position.x) || !validCoordinate(position.y)) {
    throw new Error("E_DESKTOP_WIDGET_POSITION: invalid screen coordinates");
  }
  return JSON.stringify({
    schemaVersion: WIDGET_STATE_SCHEMA_VERSION,
    x: position.x,
    y: position.y,
  });
}

export function defaultWidgetPosition(
  workArea: WorkArea,
  size: Size,
  margin = 24,
): Point {
  if (
    !validWorkArea(workArea)
    || !validDimension(size.width)
    || !validDimension(size.height)
    || !Number.isSafeInteger(margin)
    || margin < 0
    || margin > 1_000
  ) {
    throw new Error("E_DESKTOP_WIDGET_BOUNDS: invalid work area or widget size");
  }
  return {
    x: Math.max(
      workArea.x,
      workArea.x + workArea.width - size.width - margin,
    ),
    y: Math.max(
      workArea.y,
      workArea.y + workArea.height - size.height - margin,
    ),
  };
}

function intersectionArea(position: Point, size: Size, area: WorkArea): number {
  const left = Math.max(position.x, area.x);
  const top = Math.max(position.y, area.y);
  const right = Math.min(position.x + size.width, area.x + area.width);
  const bottom = Math.min(position.y + size.height, area.y + area.height);
  return Math.max(0, right - left) * Math.max(0, bottom - top);
}

function distanceSquared(position: Point, size: Size, area: WorkArea): number {
  const centerX = position.x + size.width / 2;
  const centerY = position.y + size.height / 2;
  const nearestX = Math.max(area.x, Math.min(centerX, area.x + area.width));
  const nearestY = Math.max(area.y, Math.min(centerY, area.y + area.height));
  return (centerX - nearestX) ** 2 + (centerY - nearestY) ** 2;
}

function selectWorkArea(
  position: Point,
  size: Size,
  workAreas: readonly WorkArea[],
): WorkArea {
  let selected = workAreas[0];
  if (!selected) {
    throw new Error("E_DESKTOP_WIDGET_BOUNDS: no display work area");
  }
  let selectedIntersection = intersectionArea(position, size, selected);
  let selectedDistance = distanceSquared(position, size, selected);
  for (const candidate of workAreas.slice(1)) {
    const candidateIntersection = intersectionArea(position, size, candidate);
    const candidateDistance = distanceSquared(position, size, candidate);
    if (
      candidateIntersection > selectedIntersection
      || (
        candidateIntersection === selectedIntersection
        && candidateDistance < selectedDistance
      )
    ) {
      selected = candidate;
      selectedIntersection = candidateIntersection;
      selectedDistance = candidateDistance;
    }
  }
  return selected;
}

export function clampWidgetPosition(
  position: Point,
  size: Size,
  workAreas: readonly WorkArea[],
): Point {
  if (
    !validCoordinate(position.x)
    || !validCoordinate(position.y)
    || !validDimension(size.width)
    || !validDimension(size.height)
    || workAreas.length === 0
    || workAreas.some((area) => !validWorkArea(area))
  ) {
    throw new Error("E_DESKTOP_WIDGET_BOUNDS: invalid position or display list");
  }
  const area = selectWorkArea(position, size, workAreas);
  const maxX = Math.max(area.x, area.x + area.width - size.width);
  const maxY = Math.max(area.y, area.y + area.height - size.height);
  return {
    x: Math.max(area.x, Math.min(position.x, maxX)),
    y: Math.max(area.y, Math.min(position.y, maxY)),
  };
}
