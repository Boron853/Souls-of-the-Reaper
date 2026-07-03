#Requires -Version 5.1
<#
.SYNOPSIS
  First-run setup for Souls of the Reaper (Diablo III ReXGlue port).
  Asks the user for their Xbox 360 Diablo III ISO, extracts the game data,
  and writes the initial config. After this, just run launch.bat to play.
#>

Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

$ROOT    = $PSScriptRoot
$TOOLS   = Join-Path $ROOT "tools"
$EXTRACT = Join-Path $TOOLS "extract-xiso.exe"
$GAMEOUT = Join-Path $ROOT "game"
$DONE    = Join-Path $ROOT ".setup_done"

# Detect layout: release (exe in root) vs dev build
if (Test-Path (Join-Path $ROOT "diablo3.exe")) {
    $EXE  = Join-Path $ROOT "diablo3.exe"
    $TOML = Join-Path $ROOT "diablo3.toml"
} else {
    $EXEDIR = Join-Path $ROOT "port\out\build\win-amd64-relwithdebinfo"
    $EXE    = Join-Path $EXEDIR "diablo3.exe"
    $TOML   = Join-Path $EXEDIR "diablo3.toml"
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

function Write-Header {
    Clear-Host
    Write-Host "============================================================" -ForegroundColor Cyan
    Write-Host "   Souls of the Reaper  -  First-Run Setup" -ForegroundColor Cyan
    Write-Host "============================================================" -ForegroundColor Cyan
    Write-Host ""
}

function Fail([string]$msg) {
    Write-Host ""
    Write-Host "ERROR: $msg" -ForegroundColor Red
    Write-Host ""
    Write-Host "Press any key to exit..."
    $null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")
    exit 1
}

function Write-Step([string]$msg) {
    Write-Host "  >> $msg" -ForegroundColor Yellow
}

# ---------------------------------------------------------------------------
# Check prerequisites
# ---------------------------------------------------------------------------

Write-Header
Write-Host "  This wizard will extract the game data from your Xbox 360 ISO."
Write-Host "  You only need to do this once."
Write-Host ""

if (-not (Test-Path $EXTRACT)) {
    Fail "extract-xiso.exe not found in tools\. Make sure you extracted the full release zip."
}

if (-not (Test-Path $EXE)) {
    Fail "diablo3.exe not found. Make sure you extracted the full release zip."
}

# ---------------------------------------------------------------------------
# Pick ISO
# ---------------------------------------------------------------------------

Write-Host "  Select your Diablo III Xbox 360 ISO file." -ForegroundColor White
Write-Host "  (A Windows file picker will open now...)" -ForegroundColor Gray
Write-Host ""

$dialog = New-Object System.Windows.Forms.OpenFileDialog
$dialog.Title            = "Select Diablo III Xbox 360 ISO"
$dialog.Filter           = "Xbox 360 ISO (*.iso;*.xiso)|*.iso;*.xiso|All files (*.*)|*.*"
$dialog.InitialDirectory = [Environment]::GetFolderPath("Desktop")

if ($dialog.ShowDialog() -ne [System.Windows.Forms.DialogResult]::OK) {
    Write-Host "  Setup cancelled." -ForegroundColor Gray
    exit 0
}

$iso = $dialog.FileName
if (-not (Test-Path $iso)) { Fail "ISO not found: $iso" }

$isoSizeMB = [int]((Get-Item $iso).Length / 1MB)
Write-Header
Write-Host "  ISO selected: $iso"
Write-Host "  Size: ${isoSizeMB} MB"
Write-Host ""

# ---------------------------------------------------------------------------
# Extract
# ---------------------------------------------------------------------------

Write-Host "  Extracting game data from ISO..." -ForegroundColor White
Write-Host "  (This may take several minutes - the game is ~7.4 GB)"
Write-Host ""

$tempDir = Join-Path $ROOT "game_extract_temp"
if (Test-Path $tempDir) { Remove-Item $tempDir -Recurse -Force }
New-Item -ItemType Directory -Path $tempDir | Out-Null

# extract-xiso creates a folder named after the ISO in its working directory.
# Clean up any leftover from a previous run (same name, anywhere it might have been created).
$isoName = [System.IO.Path]::GetFileNameWithoutExtension($iso)
$isoParent = [System.IO.Path]::GetDirectoryName($iso)
foreach ($searchDir in @($tempDir, $isoParent, $ROOT)) {
    $old = Join-Path $searchDir $isoName
    if (Test-Path $old) { Remove-Item $old -Recurse -Force -ErrorAction SilentlyContinue }
}

Write-Step "Running extract-xiso..."
# Run with WorkingDirectory=$tempDir so the extracted folder lands inside it.
$proc = Start-Process -FilePath $EXTRACT `
    -ArgumentList "-x", "`"$iso`"" `
    -WorkingDirectory $tempDir `
    -NoNewWindow -Wait -PassThru
if ($proc.ExitCode -ne 0) {
    Remove-Item $tempDir -Recurse -Force -ErrorAction SilentlyContinue
    Fail "extract-xiso failed (exit code $($proc.ExitCode)). Make sure the ISO is a valid Xbox 360 Diablo III disc dump."
}

# ---------------------------------------------------------------------------
# Locate CPKs
# ---------------------------------------------------------------------------

Write-Step "Locating game files..."

# CPKs may be at root or inside a subdirectory (title folder on some dumps).
$cpkSearch = Get-ChildItem $tempDir -Filter "Common.cpk" -Recurse -ErrorAction SilentlyContinue |
    Select-Object -First 1
if (-not $cpkSearch) {
    Remove-Item $tempDir -Recurse -Force -ErrorAction SilentlyContinue
    Fail "Common.cpk not found in the extracted ISO. Make sure this is the Xbox 360 version of Diablo III."
}

$extractedRoot = $cpkSearch.DirectoryName

# ---------------------------------------------------------------------------
# Copy to game\
# ---------------------------------------------------------------------------

Write-Step "Setting up game directory..."

if (Test-Path $GAMEOUT) { Remove-Item $GAMEOUT -Recurse -Force }
New-Item -ItemType Directory -Path $GAMEOUT | Out-Null
$cpkOut = Join-Path $GAMEOUT "CPKs"
New-Item -ItemType Directory -Path $cpkOut | Out-Null

$copied = 0
# Copy CPKs from the directory that contains Common.cpk
foreach ($f in (Get-ChildItem $extractedRoot -Filter "*.cpk" -ErrorAction SilentlyContinue)) {
    Write-Step "  Copying $($f.Name)..."
    Copy-Item $f.FullName (Join-Path $cpkOut $f.Name) -Force
    $copied++
}

# XEX and CommonTOC may be in a parent directory (disc root), so search the whole tempDir
foreach ($pattern in @("Default.xex", "CommonTOC.dat", "Default_decrypted.exe")) {
    $found = Get-ChildItem $tempDir -Filter $pattern -Recurse -ErrorAction SilentlyContinue |
             Select-Object -First 1
    if ($found) {
        Write-Step "  Copying $($found.Name)..."
        Copy-Item $found.FullName (Join-Path $GAMEOUT $found.Name) -Force
    }
}

if ($copied -eq 0) {
    Remove-Item $tempDir -Recurse -Force -ErrorAction SilentlyContinue
    Fail "No CPK files were found in the ISO. Is this the correct game?"
}

# ---------------------------------------------------------------------------
# Cleanup temp
# ---------------------------------------------------------------------------

Write-Step "Cleaning up temporary files..."
Remove-Item $tempDir -Recurse -Force -ErrorAction SilentlyContinue

# ---------------------------------------------------------------------------
# Write config
# ---------------------------------------------------------------------------

Write-Step "Writing configuration..."

New-Item -ItemType Directory -Path (Split-Path $TOML -Parent) -Force | Out-Null

$gameRoot = $GAMEOUT -replace '\\', '\\\\'
$tomlContent = @"
# Souls of the Reaper - runtime config
# Managed by setup.ps1 / launch.bat. Your F4 keybind remaps are preserved.
game_data_root = "$gameRoot"
render_target_path_d3d12 = "rov"
d3_frame_limit = 60
vsync = true
mnk_mode = false
mnk_mouse = false
mnk_cursor_visible = true
"@
Set-Content -LiteralPath $TOML -Value $tomlContent -Encoding utf8

Set-Content -LiteralPath $DONE -Value (Get-Date -Format "yyyy-MM-dd HH:mm:ss") -Encoding utf8

# ---------------------------------------------------------------------------
# Install the bundled starter save (optional convenience so players can begin
# with characters ready to go). The port can now also create new heroes from
# scratch, so this is not required. Copy it into Documents\diablo3 only if the
# user does not already have one there - never overwrite existing saves.
# ---------------------------------------------------------------------------

$saveMsg = ""
$saveSrc = Join-Path $ROOT "Savegame (copy to Documents)\diablo3"   # contains B13EBABEBABEBABE
if (Test-Path (Join-Path $saveSrc "B13EBABEBABEBABE")) {
    $docsDiablo = Join-Path ([Environment]::GetFolderPath("MyDocuments")) "diablo3"
    $targetXuid = Join-Path $docsDiablo "B13EBABEBABEBABE"
    if (Test-Path $targetXuid) {
        $saveMsg = "Existing save found in Documents\diablo3 - kept as-is."
    } else {
        Write-Step "Installing starter save game..."
        New-Item -ItemType Directory -Path $docsDiablo -Force | Out-Null
        Copy-Item (Join-Path $saveSrc "B13EBABEBABEBABE") $docsDiablo -Recurse -Force
        $saveMsg = "Starter save installed to Documents\diablo3."
    }
}

# ---------------------------------------------------------------------------
# Done
# ---------------------------------------------------------------------------

Write-Header
Write-Host "  Setup complete!" -ForegroundColor Green
Write-Host ""
Write-Host "  Game data: $GAMEOUT"
Write-Host "  CPK files: $copied found"
if ($saveMsg) { Write-Host "  $saveMsg" }
Write-Host ""
Write-Host "  The game will now launch. Next time just run launch.bat directly."
Write-Host ""
Write-Host "  Press any key to continue to the launcher..."
$null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")

& "$ROOT\launch.bat"
