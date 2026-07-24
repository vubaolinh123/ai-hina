$ErrorActionPreference = "Stop"

$repoRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\.."))
$sourceRoot = Join-Path $repoRoot "apps\core-runtime\src"
$contractsRoot = Join-Path $repoRoot "packages\contracts\src"
$localPythonPath = "$sourceRoot;$contractsRoot"
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

$forwardArgs = @($args)
if ($forwardArgs.Count -gt 0 -and $forwardArgs[0] -eq "--") {
    $forwardArgs = @($forwardArgs | Select-Object -Skip 1)
}

& uv run --frozen python -m hina_core.runtime.error_report @forwardArgs
if ($LASTEXITCODE -ne 0) {
    throw "Hina error report collection failed with exit code $LASTEXITCODE"
}
