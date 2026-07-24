$ErrorActionPreference = "Stop"

$repoRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\.."))
$previousSmoke = $env:HINA_DESKTOP_SMOKE
$previousWarnings = $env:ELECTRON_ENABLE_SECURITY_WARNINGS
$env:HINA_DESKTOP_SMOKE = "1"
$env:ELECTRON_ENABLE_SECURITY_WARNINGS = "true"

try {
    & pnpm --filter @hina/desktop build
    if ($LASTEXITCODE -ne 0) {
        throw "Desktop build failed with exit code $LASTEXITCODE"
    }
    & pnpm --filter @hina/desktop start
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
