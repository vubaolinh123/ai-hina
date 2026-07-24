$ErrorActionPreference = "Stop"

$repoRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\.."))
$coreRoot = Join-Path $repoRoot "apps\core-runtime\src"
$contractsRoot = Join-Path $repoRoot "packages\contracts\src"
$testkitRoot = Join-Path $repoRoot "packages\testkit\src"
$safetyRoot = Join-Path $repoRoot "packages\safety-policy\src"
$textBrainRoot = Join-Path $repoRoot "packages\text-brain\src"
$memoryRoot = Join-Path $repoRoot "packages\memory\src"
$avatarRoot = Join-Path $repoRoot "packages\avatar\src"
$speechRoot = Join-Path $repoRoot "workers\speech\src"
$localPythonPath = (
    $coreRoot,
    $contractsRoot,
    $testkitRoot,
    $safetyRoot,
    $textBrainRoot,
    $memoryRoot,
    $avatarRoot,
    $speechRoot
) -join ";"
$env:PYTHONPATH = if ($env:PYTHONPATH) {
    "$localPythonPath;$env:PYTHONPATH"
} else {
    $localPythonPath
}
$env:PYTHONPYCACHEPREFIX = Join-Path $repoRoot ".cache\pycache"
$env:UV_CACHE_DIR = Join-Path $repoRoot ".cache\uv"

& uv run --frozen python -m unittest discover -s packages/avatar/tests -p "test_*.py"
if ($LASTEXITCODE -ne 0) {
    throw "Avatar unit tests failed with exit code $LASTEXITCODE"
}

& uv run --frozen python -m unittest discover -s apps/core-runtime/tests -p "test_dev_console.py"
if ($LASTEXITCODE -ne 0) {
    throw "Avatar integration tests failed with exit code $LASTEXITCODE"
}

& node --check apps/dev-console/public/audio-viseme.js
if ($LASTEXITCODE -ne 0) {
    throw "Audio viseme syntax check failed with exit code $LASTEXITCODE"
}

& node --check apps/dev-console/public/app.js
if ($LASTEXITCODE -ne 0) {
    throw "Dev Console syntax check failed with exit code $LASTEXITCODE"
}

& pnpm --filter @hina/dev-console test:avatar
if ($LASTEXITCODE -ne 0) {
    throw "Audio viseme unit tests failed with exit code $LASTEXITCODE"
}
