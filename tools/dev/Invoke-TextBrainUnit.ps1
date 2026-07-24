$ErrorActionPreference = "Stop"

$repoRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\.."))
$textBrainRoot = Join-Path $repoRoot "packages\text-brain\src"
$env:PYTHONPATH = if ($env:PYTHONPATH) { "$textBrainRoot;$env:PYTHONPATH" } else { $textBrainRoot }
$env:PYTHONPYCACHEPREFIX = Join-Path $repoRoot ".cache\pycache"
$env:UV_CACHE_DIR = Join-Path $repoRoot ".cache\uv"

& uv run --frozen python -m unittest discover -s packages/text-brain/tests -p "test_*.py"
if ($LASTEXITCODE -ne 0) {
    throw "Text brain unit tests failed with exit code $LASTEXITCODE"
}
