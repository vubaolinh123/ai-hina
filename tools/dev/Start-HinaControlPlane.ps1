$ErrorActionPreference = "Stop"

$repoRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\.."))
$sourceRoot = Join-Path $repoRoot "apps\core-runtime\src"
$contractsRoot = Join-Path $repoRoot "packages\contracts\src"
$safetyRoot = Join-Path $repoRoot "packages\safety-policy\src"
$textBrainRoot = Join-Path $repoRoot "packages\text-brain\src"
$memoryRoot = Join-Path $repoRoot "packages\memory\src"
$avatarRoot = Join-Path $repoRoot "packages\avatar\src"
$speechRoot = Join-Path $repoRoot "workers\speech\src"
$perceptionRoot = Join-Path $repoRoot "workers\perception\src"
$localPythonPath = "$sourceRoot;$contractsRoot;$safetyRoot;$textBrainRoot;$memoryRoot;$avatarRoot;$speechRoot;$perceptionRoot"
$env:PYTHONPATH = if ($env:PYTHONPATH) { "$localPythonPath;$env:PYTHONPATH" } else { $localPythonPath }
$env:PYTHONPYCACHEPREFIX = Join-Path $repoRoot ".cache\pycache"
$env:UV_CACHE_DIR = Join-Path $repoRoot ".cache\uv"
$env:PYTHONIOENCODING = "utf-8"
# The desktop profile is GPU-only. An unavailable CUDA dependency must fail
# loudly in the control-plane logs instead of silently falling back to CPU.
if (-not $env:HINA_STT_PROVIDER) { $env:HINA_STT_PROVIDER = "faster-whisper" }
if (-not $env:HINA_STT_MODEL) { $env:HINA_STT_MODEL = "Systran/faster-whisper-large-v3" }
if (-not $env:HINA_STT_MODEL_REVISION) { $env:HINA_STT_MODEL_REVISION = "edaa852ec7e145841d8ffdb056a99866b5f0a478" }
if (-not $env:HINA_STT_DEVICE) { $env:HINA_STT_DEVICE = "cuda" }
if (-not $env:HINA_STT_COMPUTE_TYPE) { $env:HINA_STT_COMPUTE_TYPE = "float16" }
if (-not $env:HINA_STT_CPU_FALLBACK) { $env:HINA_STT_CPU_FALLBACK = "false" }
if (-not $env:HINA_STT_LANGUAGE) { $env:HINA_STT_LANGUAGE = "auto" }
if ($env:HINA_TTS_PROVIDER -eq "voxcpm2") {
    Write-Warning "VoxCPM2 has been retired; switching this launch to OmniVoice."
    $env:HINA_TTS_PROVIDER = "omnivoice"
    Remove-Item Env:HINA_TTS_MODEL -ErrorAction SilentlyContinue
    Remove-Item Env:HINA_TTS_MODEL_REVISION -ErrorAction SilentlyContinue
    Remove-Item Env:HINA_TTS_MODEL_CACHE -ErrorAction SilentlyContinue
    Remove-Item Env:HINA_TTS_PRECISION -ErrorAction SilentlyContinue
    Remove-Item Env:HINA_TTS_MAX_CHUNK_CHARACTERS -ErrorAction SilentlyContinue
    Remove-Item Env:HINA_TTS_MODEL_VRAM_MIB -ErrorAction SilentlyContinue
}
if (-not $env:HINA_TTS_PROVIDER) { $env:HINA_TTS_PROVIDER = "omnivoice" }
if ($env:HINA_TTS_PROVIDER -eq "f5-tts") {
    if (-not $env:HINA_TTS_MODEL) { $env:HINA_TTS_MODEL = "zalopay/vietnamese-tts" }
    if (-not $env:HINA_TTS_MODEL_REVISION) { $env:HINA_TTS_MODEL_REVISION = "1dc4967edb4549e40d820429e487eeeacee8bc08" }
    if (-not $env:HINA_TTS_MODEL_FILE) { $env:HINA_TTS_MODEL_FILE = "model_1290000.pt" }
    if (-not $env:HINA_TTS_VOCODER) { $env:HINA_TTS_VOCODER = "charactr/vocos-mel-24khz" }
    if (-not $env:HINA_TTS_VOCODER_REVISION) { $env:HINA_TTS_VOCODER_REVISION = "0feb3fdd929bcd6649e0e7c5a688cf7dd012ef21" }
    if (-not $env:HINA_TTS_MODEL_CACHE) { $env:HINA_TTS_MODEL_CACHE = (Join-Path $repoRoot "var\cache\models\f5-tts") }
}
elseif ($env:HINA_TTS_PROVIDER -eq "vieneu") {
    if (-not $env:HINA_TTS_MODEL) { $env:HINA_TTS_MODEL = "pnnbao-ump/VieNeu-TTS-v3-Turbo" }
    if (-not $env:HINA_TTS_MODEL_REVISION) { $env:HINA_TTS_MODEL_REVISION = "75ff82a72f54d55ed389e1eeb12041d3c4bac7d4" }
    if (-not $env:HINA_TTS_MODEL_CACHE) { $env:HINA_TTS_MODEL_CACHE = (Join-Path $repoRoot "var\cache\models\vieneu") }
}
elseif ($env:HINA_TTS_PROVIDER -eq "omnivoice") {
    if (-not $env:HINA_TTS_MODEL) { $env:HINA_TTS_MODEL = "k2-fsa/OmniVoice" }
    if (-not $env:HINA_TTS_MODEL_REVISION) { $env:HINA_TTS_MODEL_REVISION = "c5fdb5ccb189668d56333f77ba2629f4cd7535f4" }
    if (-not $env:HINA_TTS_MODEL_CACHE) { $env:HINA_TTS_MODEL_CACHE = (Join-Path $repoRoot "var\cache\models\omnivoice") }
    if (-not $env:HINA_TTS_INFERENCE_STEPS) { $env:HINA_TTS_INFERENCE_STEPS = "32" }
    if (-not $env:HINA_TTS_GUIDANCE_SCALE) { $env:HINA_TTS_GUIDANCE_SCALE = "2.0" }
    if (-not $env:HINA_TTS_MAX_CHUNK_CHARACTERS) { $env:HINA_TTS_MAX_CHUNK_CHARACTERS = "110" }
    if (-not $env:HINA_TTS_AUDIO_CHUNK_SECONDS) { $env:HINA_TTS_AUDIO_CHUNK_SECONDS = "8" }
    if (-not $env:HINA_TTS_AUDIO_CHUNK_THRESHOLD_SECONDS) { $env:HINA_TTS_AUDIO_CHUNK_THRESHOLD_SECONDS = "12" }
    if (-not $env:HINA_TTS_OMNIVOICE_MAX_SPEAKING_RATE) { $env:HINA_TTS_OMNIVOICE_MAX_SPEAKING_RATE = "1.0" }
}
else {
    throw "Unsupported HINA_TTS_PROVIDER '$env:HINA_TTS_PROVIDER'"
}
if (-not $env:HINA_TTS_DEVICE) { $env:HINA_TTS_DEVICE = "cuda" }
if (-not $env:HINA_TTS_PRECISION) { $env:HINA_TTS_PRECISION = "float16" }
if (-not $env:HINA_TTS_MODEL_VRAM_MIB) {
    $env:HINA_TTS_MODEL_VRAM_MIB = if ($env:HINA_TTS_PROVIDER -eq "omnivoice") { "3072" } elseif ($env:HINA_TTS_PROVIDER -eq "vieneu") { "6144" } else { "8192" }
}
if (-not $env:HINA_TTS_MODEL_RAM_MIB) { $env:HINA_TTS_MODEL_RAM_MIB = "6144" }
if (-not $env:HINA_TTS_WARMUP_ON_START) { $env:HINA_TTS_WARMUP_ON_START = "false" }
if (-not $env:HINA_TTS_CODEC) { $env:HINA_TTS_CODEC = "OpenMOSS-Team/MOSS-Audio-Tokenizer-Nano" }
if (-not $env:HINA_TTS_CODEC_REVISION) { $env:HINA_TTS_CODEC_REVISION = "6aa02b01e445cc585582cf0ba480bc3ea6c8dd68" }
# If the owner has prepared the local voice profile, use its deterministic
# <=8-second anchor and bind it to its SHA-256. Otherwise keep the checked-in
# consent-bound reference WAV as the safe default.
$profileAnchor = if ($env:HINA_TTS_PROVIDER -eq "omnivoice") {
    Join-Path $repoRoot "assets\voices\hina-anime-elevenlabs-reference.wav"
} elseif ($env:HINA_TTS_PROVIDER -eq "f5-tts") {
    Join-Path $repoRoot "var\cache\voices\hina\f5-reference.wav"
} else {
    Join-Path $repoRoot "var\cache\voices\hina\hina-profile-anchor.wav"
}
if (-not $env:HINA_TTS_REFERENCE_AUDIO -and (Test-Path -LiteralPath $profileAnchor)) {
    $env:HINA_TTS_REFERENCE_AUDIO = $profileAnchor
    $env:HINA_TTS_REFERENCE_SHA256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $profileAnchor).Hash.ToLowerInvariant()
}
if ($env:HINA_TTS_PROVIDER -eq "omnivoice" -and -not $env:HINA_TTS_REFERENCE_TEXT) {
    $env:HINA_TTS_REFERENCE_TEXT = "Thôi nào, đừng tự tạo áp lực cho bản thân quá. [sigh] Công việc code dự án hay gỡ lỗi có những ngày bế tắc là chuyện bình thường mà."
}
if ($env:HINA_TTS_PROVIDER -eq "f5-tts" -and -not $env:HINA_TTS_REFERENCE_TEXT) {
    $referenceTextFile = Join-Path $repoRoot "var\cache\voices\hina\f5-reference.txt"
    if (Test-Path -LiteralPath $referenceTextFile) {
        $env:HINA_TTS_REFERENCE_TEXT = (Get-Content -Raw -LiteralPath $referenceTextFile).Trim()
    }
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
