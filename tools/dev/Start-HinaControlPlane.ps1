$ErrorActionPreference = "Stop"

$repoRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\.."))
$sourceRoot = Join-Path $repoRoot "apps\core-runtime\src"
$contractsRoot = Join-Path $repoRoot "packages\contracts\src"
$safetyRoot = Join-Path $repoRoot "packages\safety-policy\src"
$textBrainRoot = Join-Path $repoRoot "packages\text-brain\src"
$memoryRoot = Join-Path $repoRoot "packages\memory\src"
$avatarRoot = Join-Path $repoRoot "packages\avatar\src"
$speechRoot = Join-Path $repoRoot "workers\speech\src"
$localPythonPath = "$sourceRoot;$contractsRoot;$safetyRoot;$textBrainRoot;$memoryRoot;$avatarRoot;$speechRoot"
$env:PYTHONPATH = if ($env:PYTHONPATH) { "$localPythonPath;$env:PYTHONPATH" } else { $localPythonPath }
$env:PYTHONPYCACHEPREFIX = Join-Path $repoRoot ".cache\pycache"
$env:UV_CACHE_DIR = Join-Path $repoRoot ".cache\uv"
# The desktop profile is GPU-only. An unavailable CUDA dependency must fail
# loudly in the control-plane logs instead of silently falling back to CPU.
if (-not $env:HINA_STT_PROVIDER) { $env:HINA_STT_PROVIDER = "faster-whisper" }
if (-not $env:HINA_STT_MODEL) { $env:HINA_STT_MODEL = "Systran/faster-whisper-large-v3" }
if (-not $env:HINA_STT_MODEL_REVISION) { $env:HINA_STT_MODEL_REVISION = "edaa852ec7e145841d8ffdb056a99866b5f0a478" }
if (-not $env:HINA_STT_DEVICE) { $env:HINA_STT_DEVICE = "cuda" }
if (-not $env:HINA_STT_COMPUTE_TYPE) { $env:HINA_STT_COMPUTE_TYPE = "float16" }
if (-not $env:HINA_STT_CPU_FALLBACK) { $env:HINA_STT_CPU_FALLBACK = "false" }
if (-not $env:HINA_STT_LANGUAGE) { $env:HINA_STT_LANGUAGE = "auto" }
if (-not $env:HINA_TTS_DEVICE) { $env:HINA_TTS_DEVICE = "cuda" }
if (-not $env:HINA_TTS_PRECISION) { $env:HINA_TTS_PRECISION = "bfloat16" }
if (-not $env:HINA_TTS_CODEC) { $env:HINA_TTS_CODEC = "OpenMOSS-Team/MOSS-Audio-Tokenizer-Nano" }
if (-not $env:HINA_TTS_CODEC_REVISION) { $env:HINA_TTS_CODEC_REVISION = "6aa02b01e445cc585582cf0ba480bc3ea6c8dd68" }
# If the owner has prepared the local voice profile, use its deterministic
# <=8-second anchor and bind it to its SHA-256. Otherwise keep the checked-in
# consent-bound reference WAV as the safe default.
$profileAnchor = Join-Path $repoRoot "var\cache\voices\hina\hina-profile-anchor.wav"
if (-not $env:HINA_TTS_REFERENCE_AUDIO -and (Test-Path -LiteralPath $profileAnchor)) {
    $env:HINA_TTS_REFERENCE_AUDIO = $profileAnchor
    $env:HINA_TTS_REFERENCE_SHA256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $profileAnchor).Hash.ToLowerInvariant()
}
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
