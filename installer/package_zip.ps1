# Builds the release zip that RecompLauncher (and anyone extracting by hand) uses:
#   SoulsOfTheReaper-<Version>-Windows-x64.zip
# It holds the same files as installer\SoulsOfTheReaper.iss, plus setup.ps1 and
# prepare.cmd for the ISO step, and recomplauncher.json. Keep the two lists in step.
#
#   installer\package_zip.ps1 -Version beta-1.4

param([Parameter(Mandatory)][string]$Version)

$ErrorActionPreference = 'Stop'
$RepoRoot = Split-Path $PSScriptRoot -Parent
$GameExeDir = Join-Path $RepoRoot "port\out\build\win-amd64-relwithdebinfo"
$DistDir = Join-Path $PSScriptRoot "dist"

# Source path -> path inside the zip.
$files = [ordered]@{
    (Join-Path $GameExeDir "diablo3.exe")                       = "diablo3.exe"
    (Join-Path $GameExeDir "rexruntimerd.dll")                  = "rexruntimerd.dll"
    (Join-Path $RepoRoot "launcher\dist\SoulsOfTheReaper.exe")  = "SoulsOfTheReaper.exe"
    (Join-Path $RepoRoot "apply_config.ps1")                    = "apply_config.ps1"
    (Join-Path $RepoRoot "setup.ps1")                           = "setup.ps1"
    (Join-Path $RepoRoot "prepare.cmd")                         = "prepare.cmd"
    (Join-Path $RepoRoot "recomplauncher.json")                 = "recomplauncher.json"
    (Join-Path $RepoRoot "tools\extract-xiso.exe")              = "tools\extract-xiso.exe"
}

foreach ($source in $files.Keys) {
    if (-not (Test-Path -LiteralPath $source)) { throw "Missing file for the zip: $source" }
}

$zip = Join-Path $DistDir "SoulsOfTheReaper-$Version-Windows-x64.zip"
New-Item -ItemType Directory -Path $DistDir -Force | Out-Null
if (Test-Path $zip) { Remove-Item $zip -Force }

# Entries are added one by one so their names use "/": both Compress-Archive and
# CreateFromDirectory on Windows PowerShell 5.1 write "\", which other extractors dislike.
Add-Type -AssemblyName System.IO.Compression.FileSystem
$archive = [IO.Compression.ZipFile]::Open($zip, 'Create')
try {
    foreach ($source in $files.Keys) {
        $entryName = $files[$source].Replace('\', '/')
        [void][IO.Compression.ZipFileExtensions]::CreateEntryFromFile($archive, $source, $entryName)
    }
} finally {
    $archive.Dispose()
}
Write-Host "Wrote $zip"