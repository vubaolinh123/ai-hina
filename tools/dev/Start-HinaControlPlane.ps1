$ErrorActionPreference = "Stop"

$repoRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\.."))
$sourceRoot = Join-Path $repoRoot "apps\core-runtime\src"
$contractsRoot = Join-Path $repoRoot "packages\contracts\src"
$safetyRoot = Join-Path $repoRoot "packages\safety-policy\src"
$textBrainRoot = Join-Path $repoRoot "packages\text-brain\src"
$memoryRoot = Join-Path $repoRoot "packages\memory\src"
$speechRoot = Join-Path $repoRoot "workers\speech\src"
$localPythonPath = "$sourceRoot;$contractsRoot;$safetyRoot;$textBrainRoot;$memoryRoot;$speechRoot"
$env:PYTHONPATH = if ($env:PYTHONPATH) { "$localPythonPath;$env:PYTHONPATH" } else { $localPythonPath }
$env:PYTHONPYCACHEPREFIX = Join-Path $repoRoot ".cache\pycache"
$env:UV_CACHE_DIR = Join-Path $repoRoot ".cache\uv"
if (-not $env:HINA_BUILD_COMMIT) {
    $buildCommit = & git -C $repoRoot rev-parse HEAD
    if ($LASTEXITCODE -eq 0) {
        $env:HINA_BUILD_COMMIT = $buildCommit.Trim()
    }
}

& uv run --frozen python -m hina_core.runtime.transport_cli @args
if ($LASTEXITCODE -ne 0) {
    throw "Hina control plane failed with exit code $LASTEXITCODE"
}
