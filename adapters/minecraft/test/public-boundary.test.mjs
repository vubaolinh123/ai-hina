import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

test("public declaration boundary contains no Mineflayer or Prismarine types", async () => {
  const declaration = await readFile(
    new URL("../dist/index.d.ts", import.meta.url),
    "utf8",
  );
  assert.equal(/\bmineflayer\b/i.test(declaration), false);
  assert.equal(/\bprismarine\b/i.test(declaration), false);
  assert.equal(/\bBotOptions\b/.test(declaration), false);
});
