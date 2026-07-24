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
    $temporaryBase = [System.IO.Path]::GetFullPath([System.IO.Path]::GetTempPath())
    $startupRoot = Join-Path $temporaryBase ("hina-startup-" + [guid]::NewGuid().ToString("N"))
    $startupRoot = [System.IO.Path]::GetFullPath($startupRoot)
    if (
        -not $startupRoot.StartsWith($temporaryBase, [System.StringComparison]::OrdinalIgnoreCase) -or
        -not ([System.IO.Path]::GetFileName($startupRoot)).StartsWith("hina-startup-")
    ) {
        throw "Refusing to create startup-check data outside the verified temporary directory"
    }
    New-Item -ItemType Directory -Path $startupRoot | Out-Null
    $arguments += @(
        "--database",
        (Join-Path $startupRoot "runtime.sqlite3"),
        "--log",
        (Join-Path $startupRoot "runtime.jsonl"),
        "--audit-log",
        (Join-Path $startupRoot "safety-audit.jsonl"),
        "--memory-database",
        (Join-Path $startupRoot "memory.sqlite3"),
        "--memory-index",
        (Join-Path $startupRoot "memory-qdrant")
    )
}

try {
    & uv @arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Hina Dev Console failed with exit code $LASTEXITCODE"
    }
}
finally {
    if ($StartupCheck -and (Test-Path -LiteralPath $startupRoot)) {
        $resolvedStartupRoot = [System.IO.Path]::GetFullPath(
            (Resolve-Path -LiteralPath $startupRoot).Path
        )
        if (
            $resolvedStartupRoot.StartsWith($temporaryBase, [System.StringComparison]::OrdinalIgnoreCase) -and
            ([System.IO.Path]::GetFileName($resolvedStartupRoot)).StartsWith("hina-startup-")
        ) {
            Remove-Item -LiteralPath $resolvedStartupRoot -Recurse -Force
        }
    }
}
