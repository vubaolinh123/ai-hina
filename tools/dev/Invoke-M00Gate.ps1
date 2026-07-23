$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
Set-Location -LiteralPath $repoRoot

function Invoke-Checked {
    param(
        [Parameter(Mandatory = $true)]
        [scriptblock]$Command,
        [Parameter(Mandatory = $true)]
        [string]$Description
    )

    & $Command
    if ($LASTEXITCODE -ne 0) {
        throw "$Description failed with exit code $LASTEXITCODE"
    }
}

$env:UV_CACHE_DIR = Join-Path $repoRoot ".cache\uv"

Invoke-Checked { uv lock --check } "uv lock check"
Invoke-Checked { pnpm install --lockfile-only --frozen-lockfile } "pnpm lock check"
Invoke-Checked { uv run --frozen python tools/dev/validate_m00.py } "M00 validator"
Invoke-Checked { uv run --frozen python -m unittest discover -s tests -p "test_*.py" } "Python tests"
Invoke-Checked { node tools/dev/check-node-workspace.mjs } "Node workspace check"
Invoke-Checked { uv run --frozen python tools/license/check_provenance.py } "provenance check"
Invoke-Checked { uv run --frozen python tools/dev/hardware_inventory.py --output artifacts/verification/M00/hardware-inventory.json } "hardware inventory"
Invoke-Checked { uv run --frozen python tools/sbom/generate_sbom.py } "SBOM generation"
Invoke-Checked { uv run --frozen python tools/dev/generate_artifact_manifest.py } "artifact manifest generation"

Write-Output "M00 gate passed"
