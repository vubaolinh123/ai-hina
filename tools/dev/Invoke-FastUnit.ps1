$ErrorActionPreference = "Stop"

$repoRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\.."))
$sourceRoot = Join-Path $repoRoot "apps\core-runtime\src"
$env:PYTHONPATH = if ($env:PYTHONPATH) { "$sourceRoot;$env:PYTHONPATH" } else { $sourceRoot }
$env:PYTHONPYCACHEPREFIX = Join-Path $repoRoot ".cache\pycache"
$env:UV_CACHE_DIR = Join-Path $repoRoot ".cache\uv"

& uv run --frozen python -m unittest discover -s apps/core-runtime/tests -p "test_*.py"
if ($LASTEXITCODE -ne 0) {
    throw "Fast unit tests failed with exit code $LASTEXITCODE"
}

