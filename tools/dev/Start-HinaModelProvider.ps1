param(
    [switch]$PullMissingModel,
    [switch]$StartupCheck
)

$ErrorActionPreference = "Stop"

$repoRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\.."))
$logDirectory = [System.IO.Path]::GetFullPath((Join-Path $repoRoot "var\logs"))
$provider = if ($env:HINA_MODEL_PROVIDER) { $env:HINA_MODEL_PROVIDER.Trim().ToLowerInvariant() } else { "ollama" }
$baseUrl = if ($env:HINA_MODEL_BASE_URL) { $env:HINA_MODEL_BASE_URL.TrimEnd("/") } else { "http://127.0.0.1:11434" }
$model = if ($env:HINA_MODEL_NAME) { $env:HINA_MODEL_NAME.Trim() } else { "qwen3-vl:8b-thinking-q4_K_M" }

if ($provider -ne "ollama") {
    Write-Host "[hina-model] Skipping Ollama bootstrap because provider is '$provider'."
    exit 0
}

$parsedBase = [Uri]$baseUrl
if (
    $parsedBase.Scheme -ne "http" -or
    $parsedBase.Host -ne "127.0.0.1" -or
    $parsedBase.UserInfo -or
    $parsedBase.Query -or
    $parsedBase.Fragment
) {
    throw "HINA_MODEL_BASE_URL must use numeric loopback HTTP, for example http://127.0.0.1:11434"
}

if (-not $logDirectory.StartsWith($repoRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "Model-provider log directory escaped the repository"
}
[System.IO.Directory]::CreateDirectory($logDirectory) | Out-Null

function Test-HinaOllama {
    try {
        $response = Invoke-RestMethod -Method Get -Uri "$baseUrl/api/tags" -TimeoutSec 2
        return $null -ne $response.models
    }
    catch {
        return $false
    }
}

function Find-HinaOllama {
    $command = Get-Command "ollama" -ErrorAction SilentlyContinue
    if ($command) {
        return $command.Source
    }
    $candidates = @(
        (Join-Path $env:LOCALAPPDATA "Programs\Ollama\ollama.exe"),
        (Join-Path $env:ProgramFiles "Ollama\ollama.exe")
    )
    foreach ($candidate in $candidates) {
        if (Test-Path -LiteralPath $candidate -PathType Leaf) {
            return [System.IO.Path]::GetFullPath($candidate)
        }
    }
    throw "Ollama was not found. Install Ollama.Ollama and run pnpm start:desktop again."
}

$ollama = Find-HinaOllama
if (-not (Test-HinaOllama)) {
    Write-Host "[hina-model] Ollama is offline; starting the local provider..."
    $stdoutPath = Join-Path $logDirectory "ollama.stdout.log"
    $stderrPath = Join-Path $logDirectory "ollama.stderr.log"
    Start-Process `
        -FilePath $ollama `
        -ArgumentList @("serve") `
        -WorkingDirectory $repoRoot `
        -WindowStyle Hidden `
        -RedirectStandardOutput $stdoutPath `
        -RedirectStandardError $stderrPath | Out-Null
    $deadline = [DateTimeOffset]::UtcNow.AddSeconds(30)
    while (-not (Test-HinaOllama)) {
        if ([DateTimeOffset]::UtcNow -ge $deadline) {
            throw "Ollama did not become ready in 30 seconds. See var/logs/ollama.stderr.log"
        }
        Start-Sleep -Milliseconds 300
    }
}

$tags = Invoke-RestMethod -Method Get -Uri "$baseUrl/api/tags" -TimeoutSec 10
$installed = @($tags.models | ForEach-Object { $_.name })
if ($installed -notcontains $model) {
    if (-not $PullMissingModel) {
        throw "Model '$model' is not installed. Run: ollama pull $model"
    }
    Write-Host "[hina-model] Pulling '$model' for first use; this can take a few minutes..."
    & $ollama pull $model
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to pull model '$model' (exit code $LASTEXITCODE)."
    }
    $tags = Invoke-RestMethod -Method Get -Uri "$baseUrl/api/tags" -TimeoutSec 10
    $installed = @($tags.models | ForEach-Object { $_.name })
    if ($installed -notcontains $model) {
        throw "Ollama pull completed but '$model' is still absent from /api/tags."
    }
}

Write-Host "[hina-model] Ready: $provider / $model at $baseUrl"

if ($StartupCheck) {
    $body = @{
        model = $model
        stream = $false
        raw = $true
        keep_alive = 0
        prompt = "<|im_start|>user`nReply with exactly one word: OK<|im_end|>`n<|im_start|>assistant`n<think>`n`n</think>`n`n"
        options = @{
            num_predict = 8
            temperature = 0
            num_ctx = 8192
            num_gpu = 999
            stop = @("<|im_end|>", "<think>")
        }
    } | ConvertTo-Json -Depth 5
    $stopwatch = [Diagnostics.Stopwatch]::StartNew()
    $response = Invoke-RestMethod `
        -Method Post `
        -Uri "$baseUrl/api/generate" `
        -ContentType "application/json" `
        -Body $body `
        -TimeoutSec 10
    $stopwatch.Stop()
    if (-not $response.response) {
        throw "Ollama same-weight fast-path smoke returned no content."
    }
    if ($stopwatch.Elapsed.TotalSeconds -ge 10) {
        throw "Ollama startup smoke exceeded the 10-second model deadline."
    }
    Write-Host (
        "[hina-model] Fast-path smoke PASS in {0:N2}s (Qwen3-VL Thinking, GPU-only request)." `
            -f $stopwatch.Elapsed.TotalSeconds
    )
}
