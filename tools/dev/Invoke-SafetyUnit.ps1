$ErrorActionPreference = "Stop"

$repoRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\.."))
$safetyRoot = Join-Path $repoRoot "packages\safety-policy\src"
$env:PYTHONPATH = if ($env:PYTHONPATH) { "$safetyRoot;$env:PYTHONPATH" } else { $safetyRoot }
$env:PYTHONPYCACHEPREFIX = Join-Path $repoRoot ".cache\pycache"
$env:UV_CACHE_DIR = Join-Path $repoRoot ".cache\uv"

& uv run --frozen python -m unittest discover -s packages/safety-policy/tests -p "test_*.py"
if ($LASTEXITCODE -ne 0) {
    throw "Safety policy unit tests failed with exit code $LASTEXITCODE"
}
