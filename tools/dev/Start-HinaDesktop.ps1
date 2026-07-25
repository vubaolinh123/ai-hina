$ErrorActionPreference = "Stop"

$repoRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\.."))
$controlScript = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot "Start-HinaControlPlane.ps1"))
$healthUrl = "http://127.0.0.1:8765/v1/health"
$logDirectory = [System.IO.Path]::GetFullPath((Join-Path $repoRoot "var\logs"))
if (-not $controlScript.StartsWith($repoRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "Control-plane launcher escaped the repository"
}
if (-not $logDirectory.StartsWith($repoRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "Desktop log directory escaped the repository"
}
[System.IO.Directory]::CreateDirectory($logDirectory) | Out-Null

function Test-HinaControlPlane {
    try {
        $response = Invoke-WebRequest -UseBasicParsing -Uri $healthUrl -TimeoutSec 2
        return $response.StatusCode -eq 200
    }
    catch {
        return $false
    }
}

$controlProcess = $null
$startedControlPlane = $false
try {
    if (-not (Test-HinaControlPlane)) {
        Write-Host "[hina-desktop] Control plane chưa chạy; đang tự khởi động..."
        $stdoutPath = Join-Path $logDirectory "desktop-control.stdout.log"
        $stderrPath = Join-Path $logDirectory "desktop-control.stderr.log"
        $controlProcess = Start-Process `
            -FilePath "powershell.exe" `
            -ArgumentList @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $controlScript) `
            -WorkingDirectory $repoRoot `
            -WindowStyle Hidden `
            -RedirectStandardOutput $stdoutPath `
            -RedirectStandardError $stderrPath `
            -PassThru
        $startedControlPlane = $true
        $deadline = [DateTimeOffset]::UtcNow.AddSeconds(45)
        while (-not (Test-HinaControlPlane)) {
            if ($controlProcess.HasExited) {
                throw "Control plane dừng trước khi sẵn sàng. Xem var/logs/desktop-control.stderr.log"
            }
            if ([DateTimeOffset]::UtcNow -ge $deadline) {
                throw "Control plane không sẵn sàng sau 45 giây. Xem var/logs/desktop-control.stderr.log"
            }
            Start-Sleep -Milliseconds 350
        }
        Write-Host "[hina-desktop] Control plane đã sẵn sàng."
    }

    & pnpm --filter @hina/desktop build
    if ($LASTEXITCODE -ne 0) {
        throw "Desktop build failed with exit code $LASTEXITCODE"
    }
    & pnpm --filter @hina/desktop start
    if ($LASTEXITCODE -ne 0) {
        throw "Desktop exited with code $LASTEXITCODE"
    }
}
finally {
    if ($startedControlPlane -and $null -ne $controlProcess -and -not $controlProcess.HasExited) {
        Stop-Process -Id $controlProcess.Id
        $controlProcess.WaitForExit()
    }
}
