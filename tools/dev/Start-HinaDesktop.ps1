$ErrorActionPreference = "Stop"

$repoRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\.."))
$controlScript = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot "Start-HinaControlPlane.ps1"))
$modelScript = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot "Start-HinaModelProvider.ps1"))
$healthUrl = "http://127.0.0.1:8765/v1/health"
$versionUrl = "http://127.0.0.1:8765/v1/version"
$minecraftHealthUrl = "http://127.0.0.1:8766/health"
$minecraftEntrypoint = [System.IO.Path]::GetFullPath((Join-Path $repoRoot "adapters\minecraft\dist\service-cli.js"))
$logDirectory = [System.IO.Path]::GetFullPath((Join-Path $repoRoot "var\logs"))
if (-not $controlScript.StartsWith($repoRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "Control-plane launcher escaped the repository"
}
if (-not $logDirectory.StartsWith($repoRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "Desktop log directory escaped the repository"
}
if (-not $minecraftEntrypoint.StartsWith($repoRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "Minecraft service entrypoint escaped the repository"
}
[System.IO.Directory]::CreateDirectory($logDirectory) | Out-Null

$uvCommand = Get-Command uv -ErrorAction SilentlyContinue
if ($null -eq $uvCommand) {
    Write-Host "[hina-desktop] uv không có trong PATH; Spout2 bridge sẽ fallback về VRM local."
}
else {
    Write-Host "[hina-desktop] Spout2 bridge tùy chọn sẽ nhận sender VTubeStudioSpout trên loopback."
}

function Test-HinaControlPlane {
    try {
        $response = Invoke-WebRequest -UseBasicParsing -Uri $healthUrl -TimeoutSec 2
        return $response.StatusCode -eq 200
    }
    catch {
        return $false
    }
}

function Test-HinaMinecraftService {
    try {
        $response = Invoke-RestMethod -Uri $minecraftHealthUrl -TimeoutSec 2
        return (
            $response.status -eq "ok" -and
            $response.controlEnabled -eq $true
        )
    }
    catch {
        return $false
    }
}

function New-HinaEphemeralToken {
    $bytes = [byte[]]::new(32)
    [System.Security.Cryptography.RandomNumberGenerator]::Fill($bytes)
    return [Convert]::ToBase64String($bytes).TrimEnd("=").Replace("+", "-").Replace("/", "_")
}

function Get-HinaControlVersion {
    try {
        $response = Invoke-RestMethod -Uri $versionUrl -TimeoutSec 2
        if ($response -and $response.buildCommit) {
            return [string]$response.buildCommit
        }
    }
    catch {
        return $null
    }
    return $null
}

function Stop-StaleHinaControlPlane {
    $expectedCommit = (& git -C $repoRoot rev-parse HEAD).Trim()
    if (-not (Test-HinaControlPlane)) {
        return $false
    }
    $runningCommit = Get-HinaControlVersion
    if ($runningCommit -eq $expectedCommit) {
        return $false
    }

    $connections = @(Get-NetTCPConnection -LocalPort 8765 -State Listen -ErrorAction SilentlyContinue)
    foreach ($connection in $connections) {
        $process = Get-CimInstance Win32_Process -Filter "ProcessId=$($connection.OwningProcess)" -ErrorAction SilentlyContinue
        $commandLine = [string]$process.CommandLine
        if (
            $process -and
            $commandLine -match "hina_core\.runtime\.transport_cli"
        ) {
            Write-Host "[hina-desktop] Phat hien control plane cu ($runningCommit); dang dung PID $($process.ProcessId) de nap build $expectedCommit."
            Stop-Process -Id $process.ProcessId
            try {
                Wait-Process -Id $process.ProcessId -Timeout 8 -ErrorAction Stop
            }
            catch {
                # The process may have exited between Stop-Process and Wait-Process.
            }
            return $true
        }
    }
    throw "Control plane dang chay build $runningCommit, khong the tu dong dung vi khong xac minh duoc process thuoc repo nay."
}

function Write-HinaRuntimeErrors {
    $runtimePath = Join-Path $logDirectory "hina-runtime.jsonl"
    if (Test-Path -LiteralPath $runtimePath) {
        Get-Content -LiteralPath $runtimePath -Tail 80 |
            Where-Object { $_ -match '"level"\s*:\s*"error"' } |
            Select-Object -Last 20 |
            ForEach-Object { Write-Host "[hina-error] $_" }
    }
    foreach ($name in @("desktop-control.stderr.log", "desktop-control.stdout.log")) {
        $path = Join-Path $logDirectory $name
        if (Test-Path -LiteralPath $path) {
            Get-Content -LiteralPath $path -Tail 20 |
                Where-Object { $_.Trim() } |
                ForEach-Object { Write-Host "[hina-$name] $_" }
        }
    }
    foreach ($name in @("desktop-minecraft.stderr.log", "desktop-minecraft.stdout.log")) {
        $path = Join-Path $logDirectory $name
        if (Test-Path -LiteralPath $path) {
            Get-Content -LiteralPath $path -Tail 20 |
                Where-Object { $_.Trim() } |
                ForEach-Object { Write-Host "[hina-$name] $_" }
        }
    }
}

$controlProcess = $null
$startedControlPlane = $false
$minecraftProcess = $null
$startedMinecraftService = $false
$previousMinecraftToken = $env:HINA_MINECRAFT_CONTROL_TOKEN
try {
    & $modelScript -PullMissingModel -StartupCheck
    if (-not $?) {
        throw "Local model provider bootstrap failed."
    }
    $null = Stop-StaleHinaControlPlane
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

    if (Test-HinaMinecraftService) {
        throw "Minecraft control service is already running on 127.0.0.1:8766. Stop it before starting this Desktop session."
    }
    & pnpm --filter @hina/minecraft-adapter build
    if ($LASTEXITCODE -ne 0) {
        throw "Minecraft adapter build failed with exit code $LASTEXITCODE"
    }
    $env:HINA_MINECRAFT_CONTROL_TOKEN = New-HinaEphemeralToken
    $minecraftStdoutPath = Join-Path $logDirectory "desktop-minecraft.stdout.log"
    $minecraftStderrPath = Join-Path $logDirectory "desktop-minecraft.stderr.log"
    $nodeCommand = (Get-Command node -ErrorAction Stop).Source
    $minecraftProcess = Start-Process `
        -FilePath $nodeCommand `
        -ArgumentList @($minecraftEntrypoint) `
        -WorkingDirectory $repoRoot `
        -WindowStyle Hidden `
        -RedirectStandardOutput $minecraftStdoutPath `
        -RedirectStandardError $minecraftStderrPath `
        -PassThru
    $startedMinecraftService = $true
    $minecraftDeadline = [DateTimeOffset]::UtcNow.AddSeconds(15)
    while (-not (Test-HinaMinecraftService)) {
        if ($minecraftProcess.HasExited) {
            throw "Minecraft control service exited before becoming ready. See var/logs/desktop-minecraft.stderr.log"
        }
        if ([DateTimeOffset]::UtcNow -ge $minecraftDeadline) {
            throw "Minecraft control service was not ready after 15 seconds. See var/logs/desktop-minecraft.stderr.log"
        }
        Start-Sleep -Milliseconds 200
    }
    Write-Host "[hina-desktop] Minecraft control service is ready and disconnected."

    & pnpm --filter @hina/desktop build
    if ($LASTEXITCODE -ne 0) {
        throw "Desktop build failed with exit code $LASTEXITCODE"
    }
    & pnpm --filter @hina/desktop start
    if ($LASTEXITCODE -ne 0) {
        throw "Desktop exited with code $LASTEXITCODE"
    }
}
catch {
    Write-Host "[hina-desktop] ERROR: $($_.Exception.Message)"
    Write-HinaRuntimeErrors
    throw
}
finally {
    if ($startedMinecraftService -and $null -ne $minecraftProcess -and -not $minecraftProcess.HasExited) {
        Stop-Process -Id $minecraftProcess.Id
        $minecraftProcess.WaitForExit()
    }
    if ($null -eq $previousMinecraftToken) {
        Remove-Item Env:HINA_MINECRAFT_CONTROL_TOKEN -ErrorAction SilentlyContinue
    }
    else {
        $env:HINA_MINECRAFT_CONTROL_TOKEN = $previousMinecraftToken
    }
    if ($startedControlPlane -and $null -ne $controlProcess -and -not $controlProcess.HasExited) {
        Stop-Process -Id $controlProcess.Id
        $controlProcess.WaitForExit()
    }
    Write-HinaRuntimeErrors
}
