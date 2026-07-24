$ErrorActionPreference = "Stop"

$repoRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\.."))
$avatarRoot = Join-Path $repoRoot "packages\avatar\src"
$env:PYTHONPATH = if ($env:PYTHONPATH) { "$avatarRoot;$env:PYTHONPATH" } else { $avatarRoot }
$env:PYTHONPYCACHEPREFIX = Join-Path $repoRoot ".cache\pycache"
$env:UV_CACHE_DIR = Join-Path $repoRoot ".cache\uv"

& uv run --frozen python -m unittest discover -s packages/avatar/tests -p "test_*.py"
if ($LASTEXITCODE -ne 0) {
    throw "Avatar unit tests failed with exit code $LASTEXITCODE"
}
