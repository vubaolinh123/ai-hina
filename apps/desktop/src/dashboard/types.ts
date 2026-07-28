export type DashboardPage =
  | "overview"
  | "chat"
  | "speech"
  | "perception"
  | "resources"
  | "avatar"
  | "live2d"
  | "runtime";

export type ChatMessage = {
  role: "user" | "assistant" | "system";
  text: string;
};

export type ChatContextUsage = {
  contextWindowTokens: number;
  budgetBytes: number;
  estimatedInputTokens: number | null;
  estimatedUsagePercent: number | null;
  messageCount: number | null;
  includedMemoryTurns: number | null;
  includedLongTermMemories: number | null;
  includedFreshObservations: number | null;
  measurement: "utf8-byte-estimate";
  estimateBytesPerToken: 4;
  source: "configured" | "last-turn";
};
