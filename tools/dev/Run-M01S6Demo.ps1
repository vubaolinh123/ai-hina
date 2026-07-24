$ErrorActionPreference = "Stop"

$repoRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\.."))
$sourceRoot = Join-Path $repoRoot "apps\core-runtime\src"
$contractsRoot = Join-Path $repoRoot "packages\contracts\src"
$testkitRoot = Join-Path $repoRoot "packages\testkit\src"
$localPythonPath = "$sourceRoot;$contractsRoot;$testkitRoot"
$env:PYTHONPATH = if ($env:PYTHONPATH) { "$localPythonPath;$env:PYTHONPATH" } else { $localPythonPath }
$env:PYTHONPYCACHEPREFIX = Join-Path $repoRoot ".cache\pycache"
$env:UV_CACHE_DIR = Join-Path $repoRoot ".cache\uv"
$env:PYTHONUTF8 = "1"
if (-not $env:HINA_BUILD_COMMIT) {
    $buildCommit = & git -C $repoRoot rev-parse HEAD
    if ($LASTEXITCODE -eq 0) {
        $env:HINA_BUILD_COMMIT = $buildCommit.Trim()
    }
}

& uv run --frozen python -m hina_core.runtime.observability_demo @args
if ($LASTEXITCODE -ne 0) {
    throw "M01-S6 demo failed with exit code $LASTEXITCODE"
}
