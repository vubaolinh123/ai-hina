import fs from "node:fs";
import path from "node:path";
import process from "node:process";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(here, "..", "..");

function fail(message) {
  process.stderr.write(`M00 Node workspace check failed: ${message}\n`);
  process.exitCode = 1;
}

const packagePath = path.join(root, "package.json");
const lockPath = path.join(root, "pnpm-lock.yaml");
const workspacePath = path.join(root, "pnpm-workspace.yaml");

const pkg = JSON.parse(fs.readFileSync(packagePath, "utf8"));
if (pkg.name !== "hina-ai" || pkg.private !== true) {
  fail("package.json must define the private hina-ai workspace");
}
if (pkg.packageManager !== "pnpm@11.9.0") {
  fail("packageManager must pin pnpm@11.9.0");
}
if (!pkg.scripts?.["check:m00"] || !pkg.scripts?.sbom) {
  fail("required M00 scripts are missing");
}
if (!fs.existsSync(lockPath)) {
  fail("pnpm-lock.yaml is missing");
}
const workspace = fs.readFileSync(workspacePath, "utf8");
for (const member of ["apps/*", "adapters/*", "packages/typescript/*"]) {
  if (!workspace.includes(member)) {
    fail(`pnpm workspace is missing ${member}`);
  }
}

if (!process.exitCode) {
  process.stdout.write("M00 Node workspace check passed\n");
}
