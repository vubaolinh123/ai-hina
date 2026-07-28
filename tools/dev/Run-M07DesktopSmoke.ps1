$ErrorActionPreference = "Stop"

$repoRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\.."))
$desktopScript = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot "Start-HinaDesktop.ps1"))
$previousSmoke = $env:HINA_DESKTOP_SMOKE
$previousWarnings = $env:ELECTRON_ENABLE_SECURITY_WARNINGS
$env:HINA_DESKTOP_SMOKE = "1"
$env:ELECTRON_ENABLE_SECURITY_WARNINGS = "true"

if (-not $desktopScript.StartsWith($repoRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "Desktop launcher escaped the repository"
}

try {
    # The Electron renderer uses typed IPC against the loopback control plane.
    # Run the same launcher as pnpm start:desktop so smoke cannot falsely test
    # an offline renderer without first starting and waiting for that plane.
    & $desktopScript
    if ($LASTEXITCODE -ne 0) {
        throw "Desktop smoke failed with exit code $LASTEXITCODE"
    }
}
finally {
    if ($null -eq $previousSmoke) {
        Remove-Item Env:HINA_DESKTOP_SMOKE -ErrorAction SilentlyContinue
    }
    else {
        $env:HINA_DESKTOP_SMOKE = $previousSmoke
    }
    if ($null -eq $previousWarnings) {
        Remove-Item Env:ELECTRON_ENABLE_SECURITY_WARNINGS -ErrorAction SilentlyContinue
    }
    else {
        $env:ELECTRON_ENABLE_SECURITY_WARNINGS = $previousWarnings
    }
}
