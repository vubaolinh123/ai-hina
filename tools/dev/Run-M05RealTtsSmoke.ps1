param(
    [string]$Text = ""
)

$ErrorActionPreference = "Stop"

$repoRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\.."))
$speechRoot = Join-Path $repoRoot "workers\speech\src"
$safetyRoot = Join-Path $repoRoot "packages\safety-policy\src"
$localPythonPath = "$speechRoot;$safetyRoot"
$env:PYTHONPATH = if ($env:PYTHONPATH) { "$localPythonPath;$env:PYTHONPATH" } else { $localPythonPath }
$env:PYTHONPYCACHEPREFIX = Join-Path $repoRoot ".cache\pycache"
$env:UV_CACHE_DIR = Join-Path $repoRoot ".cache\uv"
$env:HINA_TTS_DEVICE = "cpu"
$env:HINA_TTS_PRECISION = "int8"
$env:HINA_TTS_ALLOW_DOWNLOAD = "true"

$arguments = @(
    "run",
    "--frozen",
    "python",
    "tools/dev/m05_real_tts_smoke.py"
)
if ($Text) {
    $arguments += @("--text", $Text)
}

& uv @arguments
if ($LASTEXITCODE -ne 0) {
    throw "M05 real TTS smoke failed with exit code $LASTEXITCODE"
}
