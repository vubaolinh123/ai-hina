$ErrorActionPreference = "Stop"

$repoRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\.."))
$speechRoot = Join-Path $repoRoot "workers\speech\src"
$textBrainRoot = Join-Path $repoRoot "packages\text-brain\src"
$localPythonPath = "$speechRoot;$textBrainRoot"
$env:PYTHONPATH = if ($env:PYTHONPATH) { "$localPythonPath;$env:PYTHONPATH" } else { $localPythonPath }
$env:PYTHONPYCACHEPREFIX = Join-Path $repoRoot ".cache\pycache"
$env:UV_CACHE_DIR = Join-Path $repoRoot ".cache\uv"

& uv run --frozen python -m unittest discover -s workers/speech/tests -p "test_*.py"
if ($LASTEXITCODE -ne 0) {
    throw "Speech unit tests failed with exit code $LASTEXITCODE"
}
