$ErrorActionPreference = "Stop"

$repoRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\.."))
$smokeDirectory = [System.IO.Path]::GetFullPath((Join-Path $repoRoot "var\tmp\m04-real-stt"))
if (-not $smokeDirectory.StartsWith($repoRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "M04 smoke directory escaped the repository"
}
[System.IO.Directory]::CreateDirectory($smokeDirectory) | Out-Null
$wavPath = [System.IO.Path]::GetFullPath((Join-Path $smokeDirectory "synthetic-owner-phrase.wav"))
if (-not $wavPath.StartsWith($smokeDirectory, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "M04 smoke WAV escaped its bounded directory"
}

Add-Type -AssemblyName System.Speech
$synthesizer = New-Object System.Speech.Synthesis.SpeechSynthesizer
try {
    $synthesizer.SelectVoice("Microsoft Zira Desktop")
    $synthesizer.SetOutputToWaveFile($wavPath)
    $synthesizer.Speak("Xin chao Hina. Day la bai kiem tra giong noi.")
}
finally {
    $synthesizer.Dispose()
}

$sourceRoot = Join-Path $repoRoot "workers\speech\src"
$textBrainRoot = Join-Path $repoRoot "packages\text-brain\src"
$localPythonPath = "$sourceRoot;$textBrainRoot"
$env:PYTHONPATH = if ($env:PYTHONPATH) { "$localPythonPath;$env:PYTHONPATH" } else { $localPythonPath }
$env:PYTHONPYCACHEPREFIX = Join-Path $repoRoot ".cache\pycache"
$env:UV_CACHE_DIR = Join-Path $repoRoot ".cache\uv"
$env:HINA_STT_DEVICE = "cpu"
$env:HINA_STT_COMPUTE_TYPE = "int8"
$env:HINA_STT_ALLOW_DOWNLOAD = "true"

try {
    & uv run --frozen python tools/dev/m04_real_stt_smoke.py $wavPath
    if ($LASTEXITCODE -ne 0) {
        throw "M04 real STT smoke failed with exit code $LASTEXITCODE"
    }
}
finally {
    if ([System.IO.File]::Exists($wavPath)) {
        [System.IO.File]::Delete($wavPath)
    }
}
