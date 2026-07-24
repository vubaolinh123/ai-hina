export type HinaPresentationState =
  | "idle"
  | "listening"
  | "thinking"
  | "speaking"
  | "interrupted"
  | "error";

export type HinaBoneRotation = {
  x: number;
  y: number;
  z: number;
};

export const HINA_PRESENTATION: Readonly<{
  id: "hina-kawaii-v0.1";
  displayName: string;
  description: string;
}>;

export const HINA_MATERIAL_TINTS: Readonly<Record<string, string>>;

export function createHinaPoseFrame(
  state: HinaPresentationState,
  seconds: number,
): Record<string, HinaBoneRotation>;

export function blinkWeightAt(
  seconds: number,
  state: HinaPresentationState,
): number;

export function listHinaPoseBones(): string[];
