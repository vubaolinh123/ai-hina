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

test("exact harvest lookup never reads coordinates from a palette probe", async () => {
  const implementation = await readFile(
    new URL("../dist/mineflayer-client.js", import.meta.url),
    "utf8",
  );
  const exactLookup = implementation.match(
    /#findExactHarvestableLog\(target\) \{[\s\S]*?\n    #initializeBoundedPathfinder/,
  )?.[0];
  assert.ok(exactLookup);
  const extraInfoBoundary = exactLookup.indexOf("useExtraInfo:");
  assert.notEqual(extraInfoBoundary, -1);
  assert.doesNotMatch(
    exactLookup.slice(0, extraInfoBoundary),
    /candidate\.position/,
  );
  assert.match(
    exactLookup.slice(extraInfoBoundary),
    /hasFinitePosition\(candidate\.position\)/,
  );
  assert.match(implementation, /\[hina-minecraft:path:ERROR\]/);
});
