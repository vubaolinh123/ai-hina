$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
Set-Location -LiteralPath $repoRoot

uv lock --check
pnpm install --lockfile-only --frozen-lockfile
python tools/dev/validate_m00.py
python -m unittest discover -s tests -p "test_*.py"
node tools/dev/check-node-workspace.mjs
python tools/license/check_provenance.py
python tools/dev/hardware_inventory.py --output artifacts/verification/M00/hardware-inventory.json
python tools/sbom/generate_sbom.py
python tools/dev/generate_artifact_manifest.py

Write-Output "M00 gate passed"
