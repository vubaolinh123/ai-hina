param(
    [string]$Text = "",
    [string]$Output = "",
    [ValidateSet("voxcpm2", "vieneu", "f5-tts")]
    [string]$Provider = "voxcpm2"
)

$ErrorActionPreference = "Stop"

$repoRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\.."))
$speechRoot = Join-Path $repoRoot "workers\speech\src"
$safetyRoot = Join-Path $repoRoot "packages\safety-policy\src"
$localPythonPath = "$speechRoot;$safetyRoot"
$env:PYTHONPATH = if ($env:PYTHONPATH) { "$localPythonPath;$env:PYTHONPATH" } else { $localPythonPath }
$env:PYTHONPYCACHEPREFIX = Join-Path $repoRoot ".cache\pycache"
$env:UV_CACHE_DIR = Join-Path $repoRoot ".cache\uv"
$env:PYTHONIOENCODING = "utf-8"
$env:HINA_TTS_PROVIDER = $Provider
$env:HINA_TTS_DEVICE = "cuda"
$env:HINA_TTS_PRECISION = if ($Provider -eq "voxcpm2") { "bfloat16" } else { "float16" }
$env:HINA_TTS_ALLOW_DOWNLOAD = "true"
if ($Provider -eq "voxcpm2") {
    $env:HINA_TTS_MODEL = "openbmb/VoxCPM2"
    $env:HINA_TTS_MODEL_REVISION = "bffb3df5a29440629464e5e839f4d214c8714c3d"
    $env:HINA_TTS_MODEL_CACHE = Join-Path $repoRoot "var\cache\models\voxcpm2"
    $env:HINA_TTS_INFERENCE_STEPS = "10"
    $env:HINA_TTS_GUIDANCE_SCALE = "2.0"
    $env:HINA_TTS_MAX_CHUNK_CHARACTERS = "180"
    $profileAnchor = Join-Path $repoRoot "var\cache\voices\hina\hina-profile-anchor.wav"
}
elseif ($Provider -eq "vieneu") {
    $env:HINA_TTS_MODEL = "pnnbao-ump/VieNeu-TTS-v3-Turbo"
    $env:HINA_TTS_MODEL_REVISION = "75ff82a72f54d55ed389e1eeb12041d3c4bac7d4"
    $env:HINA_TTS_MODEL_CACHE = Join-Path $repoRoot "var\cache\models\vieneu"
    $env:HINA_TTS_CODEC = "OpenMOSS-Team/MOSS-Audio-Tokenizer-Nano"
    $env:HINA_TTS_CODEC_REVISION = "6aa02b01e445cc585582cf0ba480bc3ea6c8dd68"
    $profileAnchor = Join-Path $repoRoot "var\cache\voices\hina\hina-profile-anchor.wav"
}
else {
    $env:HINA_TTS_MODEL = "zalopay/vietnamese-tts"
    $env:HINA_TTS_MODEL_REVISION = "1dc4967edb4549e40d820429e487eeeacee8bc08"
    $env:HINA_TTS_MODEL_FILE = "model_1290000.pt"
    $env:HINA_TTS_MODEL_CACHE = Join-Path $repoRoot "var\cache\models\f5-tts"
    $env:HINA_TTS_VOCODER = "charactr/vocos-mel-24khz"
    $env:HINA_TTS_VOCODER_REVISION = "0feb3fdd929bcd6649e0e7c5a688cf7dd012ef21"
    $profileAnchor = Join-Path $repoRoot "var\cache\voices\hina\f5-reference.wav"
}
if (Test-Path -LiteralPath $profileAnchor) {
    $env:HINA_TTS_REFERENCE_AUDIO = $profileAnchor
    $env:HINA_TTS_REFERENCE_SHA256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $profileAnchor).Hash.ToLowerInvariant()
}
if ($Provider -eq "f5-tts") {
    $referenceText = Join-Path $repoRoot "var\cache\voices\hina\f5-reference.txt"
    if (Test-Path -LiteralPath $referenceText) {
        $env:HINA_TTS_REFERENCE_TEXT = (Get-Content -Raw -LiteralPath $referenceText).Trim()
    }
}

$arguments = @(
    "run",
    "--frozen",
    "python",
    "tools/dev/m05_real_tts_smoke.py"
)
if ($Text) {
    $arguments += @("--text", $Text)
}
if ($Output) {
    $arguments += @("--output", $Output)
}

& uv @arguments
if ($LASTEXITCODE -ne 0) {
    throw "M05 real TTS smoke failed with exit code $LASTEXITCODE"
}
