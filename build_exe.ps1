# Build a single-file Windows exe for SAP2000 Joint Axes.
$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

$python = if (Test-Path ".venv\Scripts\python.exe") {
    Join-Path $root ".venv\Scripts\python.exe"
} else {
    "python"
}

$icon = Join-Path $root "joint_axes\assets\app.ico"
$tiger = Join-Path $root "joint_axes\assets\tiger.png"
$versionFile = Join-Path $root "build_assets\version_info.txt"
if (-not (Test-Path $icon)) {
    throw "Icon not found: $icon"
}
if (-not (Test-Path $tiger)) {
    throw "Window icon not found: $tiger"
}
if (-not (Test-Path $versionFile)) {
    throw "Version info not found: $versionFile"
}

$buildDir = Join-Path $root "build"
if (Test-Path $buildDir) {
    Remove-Item $buildDir -Recurse -Force
}

& $python -m PyInstaller `
    --noconfirm `
    --clean `
    --onefile `
    --windowed `
    --name "SAP2000JointAxes" `
    --icon $icon `
    --version-file $versionFile `
    --add-data "$icon;joint_axes\assets" `
    --add-data "$tiger;joint_axes\assets" `
    --collect-submodules comtypes `
    --distpath (Join-Path $root "dist") `
    --workpath (Join-Path $buildDir "pyinstaller") `
    --specpath $root `
    "run.py"

if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller build failed (exit $LASTEXITCODE)."
}

$exe = Join-Path $root "dist\SAP2000JointAxes.exe"
if (-not (Test-Path $exe)) {
    throw "Expected exe was not created: $exe"
}

Write-Host ""
Write-Host "Ready: $exe"
Write-Host ("Size: {0:N1} MB" -f ((Get-Item $exe).Length / 1MB))
