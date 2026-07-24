$ErrorActionPreference = "Stop"

$repoRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\.."))
$sourceRoot = Join-Path $repoRoot "apps\core-runtime\src"
$env:PYTHONPATH = if ($env:PYTHONPATH) { "$sourceRoot;$env:PYTHONPATH" } else { $sourceRoot }
$env:PYTHONPYCACHEPREFIX = Join-Path $repoRoot ".cache\pycache"
$env:UV_CACHE_DIR = Join-Path $repoRoot ".cache\uv"
if (-not $env:HINA_BUILD_COMMIT) {
    $buildCommit = & git -C $repoRoot rev-parse HEAD
    if ($LASTEXITCODE -eq 0) {
        $env:HINA_BUILD_COMMIT = $buildCommit.Trim()
    }
}

& uv run --frozen python -m hina_core.runtime.demo @args
if ($LASTEXITCODE -ne 0) {
    throw "M01-S2 demo failed with exit code $LASTEXITCODE"
}
