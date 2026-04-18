param(
    [string]$PythonExe = "python",
    [switch]$OneDir
)

$ErrorActionPreference = "Stop"

$appEntry = Join-Path $PSScriptRoot "app.py"

$pyArgs = @(
    "-m",
    "PyInstaller",
    "--noconfirm",
    "--clean",
    "--name",
    "ArenaApp",
    "--distpath",
    "dist",
    "--workpath",
    "build\\pyinstaller",
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
    $outputPath = Join-Path $PSScriptRoot "dist\\ArenaApp\\ArenaApp.exe"
} else {
    $outputPath = Join-Path $PSScriptRoot "dist\\ArenaApp.exe"
}

Write-Host "Build complete:" $outputPath
