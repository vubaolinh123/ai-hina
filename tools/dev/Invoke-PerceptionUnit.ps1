$ErrorActionPreference = "Stop"

$repoRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\.."))
$perceptionRoot = Join-Path $repoRoot "workers\perception\src"
$localPythonPath = "$perceptionRoot"
$env:PYTHONPATH = if ($env:PYTHONPATH) { "$localPythonPath;$env:PYTHONPATH" } else { $localPythonPath }
$env:PYTHONPYCACHEPREFIX = Join-Path $repoRoot ".cache\pycache"
$env:UV_CACHE_DIR = Join-Path $repoRoot ".cache\uv"

& uv run --frozen python -m unittest discover -s workers/perception/tests -p "test_*.py"
if ($LASTEXITCODE -ne 0) {
    throw "Perception unit tests failed with exit code $LASTEXITCODE"
}
