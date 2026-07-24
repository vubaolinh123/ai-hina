param(
    [string]$HostAddress = "127.0.0.1",
    [int]$Port = 8765,
    [switch]$NoBrowser,
    [switch]$StartupCheck
)

$ErrorActionPreference = "Stop"

$repoRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\.."))
$sourceRoot = Join-Path $repoRoot "apps\core-runtime\src"
$contractsRoot = Join-Path $repoRoot "packages\contracts\src"
$localPythonPath = "$sourceRoot;$contractsRoot"
$env:PYTHONPATH = if ($env:PYTHONPATH) { "$localPythonPath;$env:PYTHONPATH" } else { $localPythonPath }
$env:PYTHONPYCACHEPREFIX = Join-Path $repoRoot ".cache\pycache"
$env:UV_CACHE_DIR = Join-Path $repoRoot ".cache\uv"
if (-not $env:HINA_BUILD_COMMIT) {
    $buildCommit = & git -C $repoRoot rev-parse HEAD
    if ($LASTEXITCODE -eq 0) {
        $env:HINA_BUILD_COMMIT = $buildCommit.Trim()
    }
}

$arguments = @(
    "run",
    "--frozen",
    "python",
    "-m",
    "hina_core.runtime.dev_console_cli",
    "--host",
    $HostAddress,
    "--port",
    $Port
)
if (-not $NoBrowser) {
    $arguments += "--open-browser"
}
if ($StartupCheck) {
    $arguments += "--startup-check"
}

& uv @arguments
if ($LASTEXITCODE -ne 0) {
    throw "Hina Dev Console failed with exit code $LASTEXITCODE"
}
