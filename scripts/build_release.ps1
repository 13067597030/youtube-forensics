#Requires -Version 5.1
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot\..

Write-Host "== YouTubeForensics Windows 绿色包构建 ==" -ForegroundColor Cyan

$venvPython = Join-Path $PWD ".venv\Scripts\python.exe"
if (Test-Path $venvPython) {
    $python = $venvPython
} elseif ($env:PYTHON) {
    $python = $env:PYTHON
} else {
    $python = "python"
}

& $python -m pip install -q -e ".[pack,browser]"

Write-Host "PyInstaller 打包中..."
$prevEap = $ErrorActionPreference
$ErrorActionPreference = "Continue"
& $python -m PyInstaller packaging/yt_forensics.spec --noconfirm --clean 2>&1 | Out-Host
$pyiExit = $LASTEXITCODE
$ErrorActionPreference = $prevEap
if ($pyiExit -ne 0) {
    Write-Error "PyInstaller 失败，exit code $pyiExit"
}

$distDir = Join-Path $PWD "dist\YouTubeForensics"
if (-not (Test-Path $distDir)) {
    Write-Error "构建失败：未找到 dist\YouTubeForensics"
}

# 绿色包根目录资源
$configDest = Join-Path $distDir "config"
New-Item -ItemType Directory -Force -Path $configDest | Out-Null
Copy-Item -Force "config\settings.yaml" (Join-Path $configDest "settings.yaml")
Copy-Item -Force "packaging\release_templates\README-windows.txt" (Join-Path $distDir "README.txt")

New-Item -ItemType Directory -Force -Path (Join-Path $distDir "data") | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $distDir "Evidence") | Out-Null

$version = & $python -c "from yt_forensics import __version__; print(__version__)"
$zipName = Join-Path $PWD "dist\YouTubeForensics-$version-win64.zip"
& $python packaging/zip_release.py $distDir $zipName

Write-Host "完成: $zipName" -ForegroundColor Green
