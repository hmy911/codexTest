param(
    [string]$PythonExe = ".\venv\Scripts\python.exe",
    [switch]$OneDir
)

$ErrorActionPreference = "Stop"

$appEntry = Join-Path $PSScriptRoot "msl_qc_viewer\main.py"

$pyArgs = @(
    "-m",
    "PyInstaller",
    "--noconfirm",
    "--clean",
    "--windowed",
    "--name",
    "MSL_Render_QC_Viewer",
    "--distpath",
    "dist",
    "--workpath",
    "build\pyinstaller_qc_viewer",
    "--specpath",
    "build"
)

if (-not $OneDir) {
    $pyArgs += "--onefile"
}

$pyArgs += $appEntry

& $PythonExe @pyArgs

if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}

if ($OneDir) {
    $outputPath = Join-Path $PSScriptRoot "dist\MSL_Render_QC_Viewer\MSL_Render_QC_Viewer.exe"
} else {
    $outputPath = Join-Path $PSScriptRoot "dist\MSL_Render_QC_Viewer.exe"
}

Write-Host "Build complete:" $outputPath
