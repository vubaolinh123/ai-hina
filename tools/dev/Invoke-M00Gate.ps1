$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
Set-Location -LiteralPath $repoRoot

uv lock --check
pnpm install --lockfile-only --frozen-lockfile
uv run --frozen python tools/dev/validate_m00.py
uv run --frozen python -m unittest discover -s tests -p "test_*.py"
node tools/dev/check-node-workspace.mjs
uv run --frozen python tools/license/check_provenance.py
uv run --frozen python tools/dev/hardware_inventory.py --output artifacts/verification/M00/hardware-inventory.json
uv run --frozen python tools/sbom/generate_sbom.py
uv run --frozen python tools/dev/generate_artifact_manifest.py

Write-Output "M00 gate passed"
