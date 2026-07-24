$ErrorActionPreference = "Stop"

$repoRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\.."))
$sourceRoot = Join-Path $repoRoot "apps\core-runtime\src"
$contractsRoot = Join-Path $repoRoot "packages\contracts\src"
$testkitRoot = Join-Path $repoRoot "packages\testkit\src"
$safetyRoot = Join-Path $repoRoot "packages\safety-policy\src"
$textBrainRoot = Join-Path $repoRoot "packages\text-brain\src"
$localPythonPath = "$sourceRoot;$contractsRoot;$testkitRoot;$safetyRoot;$textBrainRoot"
$env:PYTHONPATH = if ($env:PYTHONPATH) { "$localPythonPath;$env:PYTHONPATH" } else { $localPythonPath }
$env:PYTHONPYCACHEPREFIX = Join-Path $repoRoot ".cache\pycache"
$env:UV_CACHE_DIR = Join-Path $repoRoot ".cache\uv"

& uv run --frozen python -m unittest discover -s packages/safety-policy/tests -p "test_*.py"
if ($LASTEXITCODE -ne 0) {
    throw "Safety policy unit tests failed with exit code $LASTEXITCODE"
}

& uv run --frozen python -m unittest discover -s packages/text-brain/tests -p "test_*.py"
if ($LASTEXITCODE -ne 0) {
    throw "Text brain unit tests failed with exit code $LASTEXITCODE"
}

& uv run --frozen python -m unittest discover -s apps/core-runtime/tests -p "test_*.py"
if ($LASTEXITCODE -ne 0) {
    throw "Fast unit tests failed with exit code $LASTEXITCODE"
}

& node --check (Join-Path $repoRoot "apps\dev-console\public\app.js")
if ($LASTEXITCODE -ne 0) {
    throw "Dev Console JavaScript syntax check failed with exit code $LASTEXITCODE"
}
