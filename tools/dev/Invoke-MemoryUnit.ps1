$ErrorActionPreference = "Stop"

$repoRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\.."))
$memoryRoot = Join-Path $repoRoot "packages\memory\src"
$safetyRoot = Join-Path $repoRoot "packages\safety-policy\src"
$localPythonPath = "$memoryRoot;$safetyRoot"
$env:PYTHONPATH = if ($env:PYTHONPATH) { "$localPythonPath;$env:PYTHONPATH" } else { $localPythonPath }
$env:PYTHONPYCACHEPREFIX = Join-Path $repoRoot ".cache\pycache"
$env:UV_CACHE_DIR = Join-Path $repoRoot ".cache\uv"

& uv run --frozen python -m unittest discover -s packages/memory/tests -p "test_*.py"
if ($LASTEXITCODE -ne 0) {
    throw "Memory unit tests failed with exit code $LASTEXITCODE"
}
