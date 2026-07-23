import { readFileSync } from "node:fs";
import process from "node:process";

import { validateEnvelopeBytes } from "../dist/index.js";

const input = readFileSync(0);
const result = validateEnvelopeBytes(input);
process.stdout.write(`${JSON.stringify(result)}\n`);
process.exit(result.ok ? 0 : 1);
