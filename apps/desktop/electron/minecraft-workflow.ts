export const MINECRAFT_WORKFLOW_TRACE_MAX_ENTRIES = 8;

export type MinecraftGoalProgress = {
  schemaVersion: 1;
  workflowId: string;
  sequence: number;
  occurredAt: string;
  stage:
    | "request.received"
    | "planner.started"
    | "planner.completed"
    | "controller.started"
    | "controller.completed"
    | "postcondition.completed"
    | "workflow.failed";
  status: "running" | "succeeded" | "failed" | "unsupported";
  title: string;
  detail: string;
  elapsedMs: number;
};

const STAGES = new Set<MinecraftGoalProgress["stage"]>([
  "request.received",
  "planner.started",
  "planner.completed",
  "controller.started",
  "controller.completed",
  "postcondition.completed",
  "workflow.failed",
]);

const STATUSES = new Set<MinecraftGoalProgress["status"]>([
  "running",
  "succeeded",
  "failed",
  "unsupported",
]);

export function parseMinecraftGoalProgress(
  value: unknown,
): MinecraftGoalProgress | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  const raw = value as Record<string, unknown>;
  if (
    Object.keys(raw).length !== 9
    || raw.schemaVersion !== 1
    || typeof raw.workflowId !== "string"
    || !/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/iu.test(raw.workflowId)
    || typeof raw.sequence !== "number"
    || !Number.isInteger(raw.sequence)
    || raw.sequence < 1
    || raw.sequence > MINECRAFT_WORKFLOW_TRACE_MAX_ENTRIES
    || typeof raw.occurredAt !== "string"
    || raw.occurredAt.length > 40
    || !Number.isFinite(Date.parse(raw.occurredAt))
    || typeof raw.stage !== "string"
    || !STAGES.has(raw.stage as MinecraftGoalProgress["stage"])
    || typeof raw.status !== "string"
    || !STATUSES.has(raw.status as MinecraftGoalProgress["status"])
    || typeof raw.title !== "string"
    || raw.title.length < 1
    || raw.title.length > 96
    || typeof raw.detail !== "string"
    || raw.detail.length > 384
    || typeof raw.elapsedMs !== "number"
    || !Number.isFinite(raw.elapsedMs)
    || raw.elapsedMs < 0
    || raw.elapsedMs > 120_000
  ) {
    return null;
  }
  return {
    schemaVersion: 1,
    workflowId: raw.workflowId,
    sequence: raw.sequence,
    occurredAt: raw.occurredAt,
    stage: raw.stage as MinecraftGoalProgress["stage"],
    status: raw.status as MinecraftGoalProgress["status"],
    title: raw.title,
    detail: raw.detail,
    elapsedMs: raw.elapsedMs,
  };
}
