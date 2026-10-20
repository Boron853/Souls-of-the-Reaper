<#
.SYNOPSIS
  Souls of the Reaper - graphical launcher. Hosts the v6 HTML/CSS/JS design
  (launcher_design/v6_borderless_final.html) inside a small native window via
  WebView2, and on "Play" merges the chosen options into diablo3.toml
  in-process (see Merge-LauncherConfig below) and starts diablo3.exe.
#>

$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

# ---------------------------------------------------------------------------
# Resolve paths. Two situations:
#   dev:      running the raw .ps1 from launcher\ inside the repo checkout.
#   compiled: running the ps2exe-produced .exe, meant to sit at the install
#             root next to game\ / diablo3.exe / diablo3.toml. $PSScriptRoot
#             is empty once compiled (no real .ps1 on disk) - see CLAUDE.md
#             gotcha #7.
# ---------------------------------------------------------------------------
if ($PSScriptRoot) {
    $RootDir = Split-Path -Parent $PSScriptRoot
    $UiDir   = $PSScriptRoot
} else {
    $RootDir = Split-Path -Parent ([System.Reflection.Assembly]::GetEntryAssembly().Location)
    $UiDir   = Join-Path $env:TEMP "SotR_Launcher"
}

$HtmlPath  = Join-Path $UiDir "v6_borderless_final.html"
$Wv2LibDir = Join-Path $UiDir "lib"
if (-not (Test-Path -LiteralPath $HtmlPath)) {
    throw "Launcher UI payload missing: $HtmlPath"
}

# Release layout (exe copied to root) vs dev build layout - mirrors launch.bat.
if (Test-Path -LiteralPath (Join-Path $RootDir "diablo3.exe")) {
    $Exe  = Join-Path $RootDir "diablo3.exe"
    $Toml = Join-Path $RootDir "diablo3.toml"
} else {
    $Exe  = Join-Path $RootDir "port\out\build\win-amd64-relwithdebinfo\diablo3.exe"
    $Toml = Join-Path $RootDir "port\out\build\win-amd64-relwithdebinfo\diablo3.toml"
}
$Game  = Join-Path $RootDir "game"

# The player name isn't a cvar (the game reads it from SOTR_USERNAME), so it
# can't live in diablo3.toml; it gets its own small file instead.
$NameFile = Join-Path $env:LOCALAPPDATA "SoulsOfTheReaper\player_name.txt"

# ---------------------------------------------------------------------------
# Game language options. D3 picks its language from user_language / user_country
# (XCONFIG_USER_LANGUAGE) and loads the matching <locale>_*.cpk; if that
# locale's CPKs aren't actually installed it falls back cleanly to English (by
# the engine's own design - see xam_locale.cpp). Fixed list of exactly 5,
# always offered regardless of which CPKs happen to be on disk (picking one
# without matching assets just means English text/voice in-game until those
# CPKs are added) - this is a deliberate product choice, not a CPK scan.
#
# Each row: code (2-letter, shown on the launcher's language button) -> game
# langId + countryId (the cvars) and uiIdx (which of the launcher's 7 built-in
# UI translations to display, 0=En 1=Es 2=Fr 3=De 4=It 5=Pt 6=Ru). "name" is
# the language's own native spelling, shown in the picker popup.
# ---------------------------------------------------------------------------
$LangTable = @(
    @{ code = 'EN'; langId = 1;  countryId = 103; name = 'English';  uiIdx = 0 }
    @{ code = 'DE'; langId = 3;  countryId = 24;  name = 'Deutsch';  uiIdx = 3 }
    @{ code = 'ES'; langId = 5;  countryId = 31;  name = 'Español';  uiIdx = 1 }
    @{ code = 'IT'; langId = 6;  countryId = 50;  name = 'Italiano'; uiIdx = 4 }
    @{ code = 'PT'; langId = 9;  countryId = 84;  name = 'Português'; uiIdx = 5 }
    @{ code = 'RU'; langId = 12; countryId = 88;  name = 'Русский';  uiIdx = 6 }
)

function Get-InstalledLangs {
    $LangTable | ForEach-Object {
        [pscustomobject]@{ code = $_.code; name = $_.name; langId = $_.langId; countryId = $_.countryId; uiIdx = $_.uiIdx }
    }
}

$InstalledLangs = Get-InstalledLangs
# JSON for injection into the page (ConvertTo-Json collapses a 1-element array
# to a bare object, so force an array shape the JS side can always index).
$InstalledLangsJson = '[' + (($InstalledLangs | ForEach-Object { $_ | ConvertTo-Json -Compress }) -join ',') + ']'

# ---------------------------------------------------------------------------
# Restore the last-used options. There is NO separate settings file: the toml
# apply_config.ps1 writes on every "Play" IS the saved config. We read it back
# and map each managed key to the UI's option index so the launcher opens on
# whatever you last launched with. Missing toml / missing keys fall back to the
# defaults below (RTV @ 120fps, FSR, 1x, fullscreen, gamepad).
# FPS index tables must mirror the HTML's  FPS=[[30,60,120,144],[60,120,144,240]].
# ---------------------------------------------------------------------------
function Get-SavedState {
    param([array]$Langs)
    $fpsByPath = @(@(30,60,120,144), @(60,120,144,240))
    # Defaults (used when the toml is absent or a key is missing).
    $s = @{ lang = 0; path = 1; fps = 1; scale = 0; res = 0; display = 0; mouse = 0; username = '' }
    if (Test-Path -LiteralPath $NameFile) {
        $s.username = "$(Get-Content -LiteralPath $NameFile -Raw -Encoding utf8)".Trim()
    }

    if (Test-Path -LiteralPath $Toml) {
        $kv = @{}
        foreach ($line in Get-Content -LiteralPath $Toml) {
            $t = $line.Trim()
            if ($t -eq '' -or $t.StartsWith('#')) { continue }
            $parts = $t -split '=', 2
            if ($parts.Count -ne 2) { continue }
            $kv[$parts[0].Trim()] = $parts[1].Trim().Trim('"')
        }

        if ($kv.ContainsKey('render_target_path_d3d12')) {
            $s.path = if ($kv['render_target_path_d3d12'] -eq 'rtv') { 1 } else { 0 }
        }
        if ($kv.ContainsKey('d3_frame_limit')) {
            $limit = 0; [void][int]::TryParse($kv['d3_frame_limit'], [ref]$limit)
            $idx = [array]::IndexOf($fpsByPath[$s.path], $limit)
            if ($idx -ge 0) { $s.fps = $idx }
        }
        if ($kv.ContainsKey('present_effect')) {
            switch ($kv['present_effect']) { 'fsr' { $s.scale = 0 } 'cas' { $s.scale = 1 } 'bilinear' { $s.scale = 2 } }
        }
        if ($kv.ContainsKey('draw_resolution_scale_x')) {
            $rs = 1; [void][int]::TryParse($kv['draw_resolution_scale_x'], [ref]$rs)
            if ($rs -ge 1 -and $rs -le 3) { $s.res = $rs - 1 }
        }
        if ($kv.ContainsKey('fullscreen')) {
            $s.display = if ($kv['fullscreen'] -eq 'true') { 0 } else { 1 }
        }
        # [s39] mnk_mode is always on now (keyboard always races for a slot alongside
        # gamepads) - only whether the mouse also drives the camera is a saved choice.
        $s.mouse = if ($kv['mnk_mouse'] -eq 'true') { 1 } else { 0 }
        # Language: match saved user_language+user_country back to an installed entry.
        if ($kv.ContainsKey('user_language')) {
            $ul = 1; [void][int]::TryParse($kv['user_language'], [ref]$ul)
            $uc = 103; if ($kv.ContainsKey('user_country')) { [void][int]::TryParse($kv['user_country'], [ref]$uc) }
            for ($i = 0; $i -lt $Langs.Count; $i++) {
                if ($Langs[$i].langId -eq $ul -and $Langs[$i].countryId -eq $uc) { $s.lang = $i; break }
            }
        }
    }
    return $s
}
$SavedStateJson = (Get-SavedState -Langs $InstalledLangs) | ConvertTo-Json -Compress

# ---------------------------------------------------------------------------
# Load WebView2 managed assemblies + point the native loader search path at
# our lib\ folder (WebView2Loader.dll is a native DllImport target; it must
# be resolvable from the process's DLL search path).
# ---------------------------------------------------------------------------
Add-Type -TypeDefinition @"
using System;
using System.Runtime.InteropServices;
public static class SotRNative {
    [DllImport("kernel32.dll", SetLastError = true, CharSet = CharSet.Unicode)]
    public static extern bool SetDllDirectory(string lpPathName);

    // Borderless-window drag: the classic "tell Windows this click is on the
    // title bar" trick, needed because FormBorderStyle=None removes the real
    // title bar (and its drag handling) entirely - the HTML draws its own
    // header instead, and JS forwards a mousedown on it here.
    [DllImport("user32.dll")]
    public static extern bool ReleaseCapture();
    [DllImport("user32.dll")]
    public static extern bool PostMessage(IntPtr hWnd, uint Msg, IntPtr wParam, IntPtr lParam);
    public const uint WM_NCLBUTTONDOWN = 0xA1;
    public const int HTCAPTION = 2;

    // Taskbar/Alt-Tab icon: WebView2 hosts a Chromium child process that can
    // otherwise get grouped under a generic icon by Windows shell heuristics.
    // Giving the process an explicit AppUserModelID + forcing WM_SETICON for
    // both the small (taskbar) and big (Alt-Tab) icon makes the icon shown
    // match Form.Icon reliably instead of falling back to a generic one.
    [DllImport("shell32.dll", SetLastError = true)]
    public static extern int SetCurrentProcessExplicitAppUserModelID(string AppID);
    [DllImport("user32.dll")]
    public static extern IntPtr SendMessage(IntPtr hWnd, uint Msg, IntPtr wParam, IntPtr lParam);
    public const uint WM_SETICON = 0x80;
    public const int ICON_SMALL = 0;
    public const int ICON_BIG = 1;

    // Focus handoff to diablo3.exe on Play: Windows' foreground-lock
    // heuristic normally leaves a newly-spawned process's window opening
    // behind whatever currently has focus (this launcher, mid-close) -
    // AllowSetForegroundWindow grants the just-spawned process the right to
    // steal focus itself, and the SetForegroundWindow/ShowWindow poll below
    // actively brings its window forward once it exists, since the game can
    // take a few seconds to create its window and the grant alone isn't
    // always enough by then.
    [DllImport("user32.dll", SetLastError = true)]
    public static extern bool AllowSetForegroundWindow(int dwProcessId);
    [DllImport("user32.dll")]
    public static extern bool SetForegroundWindow(IntPtr hWnd);
    [DllImport("user32.dll")]
    public static extern bool ShowWindow(IntPtr hWnd, int nCmdShow);
    public const int SW_RESTORE = 9;
}
"@
[void][SotRNative]::SetCurrentProcessExplicitAppUserModelID("D3ReXPort.SoulsOfTheReaper")
[void][SotRNative]::SetDllDirectory($Wv2LibDir)

Add-Type -Path (Join-Path $Wv2LibDir "Microsoft.Web.WebView2.Core.dll")
Add-Type -Path (Join-Path $Wv2LibDir "Microsoft.Web.WebView2.WinForms.dll")

# ---------------------------------------------------------------------------
# Build the window. Sized to EXACTLY match the v6 design's native 500px-wide
# stage (aspect-ratio 1088/1445, no body padding) - the poster fills the whole
# window edge to edge, no black margin/letterboxing around it. Small window,
# NOT fullscreen; the game itself opens big/fullscreen per whatever Display
# option was chosen, once Play launches diablo3.exe.
# ---------------------------------------------------------------------------
$form = New-Object System.Windows.Forms.Form
$form.Text = "Souls of the Reaper"
$form.ClientSize = New-Object System.Drawing.Size(500, 664)
$form.FormBorderStyle = [System.Windows.Forms.FormBorderStyle]::None
$form.StartPosition = [System.Windows.Forms.FormStartPosition]::CenterScreen
$form.ShowInTaskbar = $true
$iconPath = Join-Path $UiDir "ico_launcher.ico"
if (Test-Path -LiteralPath $iconPath) {
    $form.Icon = New-Object System.Drawing.Icon($iconPath)
    # Belt-and-suspenders for the taskbar/Alt-Tab icon (see SetCurrentProcess-
    # ExplicitAppUserModelID above): explicitly load and apply the small/big
    # icon sizes rather than relying on Form.Icon alone to propagate to the
    # native window before WebView2's child window/process shows up.
    $smallIcon = New-Object System.Drawing.Icon($iconPath, 16, 16)
    $bigIcon   = New-Object System.Drawing.Icon($iconPath, 32, 32)
    $form.add_HandleCreated({
        [void][SotRNative]::SendMessage($form.Handle, [SotRNative]::WM_SETICON, [IntPtr][SotRNative]::ICON_SMALL, $smallIcon.Handle)
        [void][SotRNative]::SendMessage($form.Handle, [SotRNative]::WM_SETICON, [IntPtr][SotRNative]::ICON_BIG, $bigIcon.Handle)
    })
}

$webView = New-Object Microsoft.Web.WebView2.WinForms.WebView2
$webView.Dock = [System.Windows.Forms.DockStyle]::Fill

$creationProps = New-Object Microsoft.Web.WebView2.WinForms.CoreWebView2CreationProperties
$creationProps.UserDataFolder = Join-Path $env:LOCALAPPDATA "SoulsOfTheReaper\WebView2"
$webView.CreationProperties = $creationProps

# ---------------------------------------------------------------------------
# apply_config.ps1 expects lowercase "true"/"false" strings (they land in the
# toml verbatim) - PowerShell booleans stringify as "True"/"False", so convert.
# ---------------------------------------------------------------------------
function B([bool]$v) { if ($v) { 'true' } else { 'false' } }

# ---------------------------------------------------------------------------
# Merges launcher-managed cvars into diablo3.toml, preserving keybind_* and
# other user/F4-overlay-owned lines - the same logic as apply_config.ps1 (kept
# in sync by hand; see that file for the authoritative comments on each key).
#
# This used to shell out to apply_config.ps1 as a separate powershell.exe
# process. That is now inlined here instead: a compiled single-exe launcher
# should not depend on a loose companion .ps1 sitting next to it at runtime -
# if that file is ever missing (antivirus quarantine, a packaging miss, a
# stale/partial install), Start-Process silently fails with a useless exit
# code (-196608 = "the -File script does not exist") instead of launching the
# game. Doing the merge in-process removes that whole failure class. The
# original reason it was a separate process (Write-Host, in a ps2exe
# -noConsole build, gets redirected into a blocking MessageBox) is avoided
# simply by not calling Write-Host here.
# ---------------------------------------------------------------------------
function Merge-LauncherConfig {
    param(
        [string]$Toml, [int]$Fps, [string]$Vsync, [string]$Rtp,
        [string]$MnkMode, [string]$MnkMouse, [string]$CursorVisible, [string]$Fullscreen,
        [ValidateSet('bilinear','cas','fsr')][string]$PresentEffect,
        [ValidateSet(1,2,3)][int]$ResScale,
        [int]$UserLanguage, [int]$UserCountry
    )
    $managed = [ordered]@{
        'render_target_path_d3d12'        = '"' + $Rtp + '"'
        'rtv_color_depth_ownership_mode'  = '8'
        'execute_unclipped_draw_vs_on_cpu' = 'true'
        'draw_resolution_scale_x'         = "$ResScale"
        'draw_resolution_scale_y'         = "$ResScale"
        'd3_frame_limit'                  = "$Fps"
        'vsync'                           = $Vsync
        'mnk_mode'                        = $MnkMode
        'mnk_mouse'                       = $MnkMouse
        'mnk_cursor_visible'              = $CursorVisible
        'fullscreen'                      = $Fullscreen
        'present_effect'                  = '"' + $PresentEffect + '"'
        'user_language'                   = "$UserLanguage"
        'user_country'                    = "$UserCountry"
    }
    $depthKeys = @('depth_float24_convert_in_pixel_shader', 'depth_float24_round')
    $ownedKeys = @($managed.Keys) + $depthKeys
    $preserved = @()
    if (Test-Path -LiteralPath $Toml) {
        foreach ($line in Get-Content -LiteralPath $Toml) {
            $t = $line.Trim()
            if ($t -eq '') { continue }
            if ($t.StartsWith('#')) { continue }
            $k = (($t -split '=', 2)[0]).Trim()
            if ($ownedKeys -contains $k) { continue }
            $preserved += $line
        }
    }
    $out = @('# Managed by SoulsOfTheReaper.exe. Your F4 overlay remaps are preserved below.')
    foreach ($k in $managed.Keys) { $out += "$k = $($managed[$k])" }
    if ($preserved.Count -gt 0) {
        $out += ''
        $out += '# --- User remaps / cvars (F4 overlay) ---'
        $out += $preserved
    }
    Set-Content -LiteralPath $Toml -Value $out -Encoding utf8
}

function Start-Game([PSCustomObject]$cfg) {
    if (-not (Test-Path -LiteralPath $Exe)) {
        [System.Windows.Forms.MessageBox]::Show(
            "diablo3.exe not found at:`n$Exe",
            "Souls of the Reaper", 'OK', 'Error') | Out-Null
        return
    }
    Merge-LauncherConfig -Toml $Toml `
        -Fps ([int]$cfg.fps) -Vsync (B $cfg.vsync) -Rtp $cfg.rtp `
        -MnkMode (B $cfg.mnkMode) -MnkMouse (B $cfg.mnkMouse) -CursorVisible 'false' `
        -Fullscreen (B $cfg.fullscreen) `
        -PresentEffect $cfg.present -ResScale ([int]$cfg.resScale) `
        -UserLanguage ([int]$cfg.langId) -UserCountry ([int]$cfg.countryId)

    # Player name: XAM name buffers hold 16 bytes including the terminator, so
    # keep at most 15 characters. diablo3.exe inherits this environment; an
    # empty value removes the variable and the game falls back to "User".
    $name = "$($cfg.username)".Trim()
    if ($name.Length -gt 15) { $name = $name.Substring(0, 15) }
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $NameFile) | Out-Null
    Set-Content -LiteralPath $NameFile -Value $name -Encoding utf8
    $env:SOTR_USERNAME = $name

    # Start-Process's -ArgumentList does NOT quote array elements that contain
    # spaces (verified: it just joins them with a space) - an unquoted
    # $Game here gets split at every space by the child process's argv
    # parser, so any install path under a user profile with a space in the
    # name (e.g. "C:\Users\Alexander Valliere\...") truncates game_data_root
    # at the first space and diablo3.exe looks for the XEX in the wrong
    # directory ("Entrypoint XEX not found: C:\Users\Alexander\default.xex").
    # Quoting the value manually fixes it.
    $gameProc = Start-Process -FilePath $Exe -ArgumentList @('--game_data_root', ('"' + $Game + '"')) -PassThru
    [void][SotRNative]::AllowSetForegroundWindow($gameProc.Id)
    $form.Close()

    # Bring the game window to the front once it exists. Without this it
    # opens BEHIND the launcher (Windows' anti-focus-stealing heuristic keeps
    # whatever had focus in front of a newly spawned process by default) and
    # needs a manual click on the taskbar icon or the game window itself to
    # come forward - AllowSetForegroundWindow above grants the right, this
    # loop actively uses it as soon as diablo3.exe's window is ready (engine
    # startup can take a few seconds, so the grant alone isn't always enough
    # by the time the window appears).
    $deadline = (Get-Date).AddSeconds(30)
    while ((Get-Date) -lt $deadline) {
        $gameProc.Refresh()
        if ($gameProc.HasExited) { break }
        if ($gameProc.MainWindowHandle -ne [IntPtr]::Zero) {
            [void][SotRNative]::ShowWindow($gameProc.MainWindowHandle, [SotRNative]::SW_RESTORE)
            [void][SotRNative]::SetForegroundWindow($gameProc.MainWindowHandle)
            break
        }
        Start-Sleep -Milliseconds 200
    }
}

$webView.add_CoreWebView2InitializationCompleted({
    param($sender, $e)
    if (-not $e.IsSuccess) {
        [System.Windows.Forms.MessageBox]::Show(
            "WebView2 failed to initialize:`n$($e.InitializationException.Message)`n`n" +
            "Make sure the WebView2 Runtime is installed (it ships with Edge on Windows 10/11).",
            "Souls of the Reaper", 'OK', 'Error') | Out-Null
        return
    }
    $sender.CoreWebView2.add_WebMessageReceived({
        param($s2, $e2)
        try {
            $msg = $e2.TryGetWebMessageAsString() | ConvertFrom-Json
            switch ($msg.type) {
                'play'      { Start-Game $msg.config }
                'minimize'  { $form.WindowState = [System.Windows.Forms.FormWindowState]::Minimized }
                'close'     { $form.Close() }
                'dragStart' {
                    [void][SotRNative]::ReleaseCapture()
                    [void][SotRNative]::PostMessage($form.Handle, [SotRNative]::WM_NCLBUTTONDOWN, [IntPtr][SotRNative]::HTCAPTION, [IntPtr]::Zero)
                }
            }
        } catch {
            [System.Windows.Forms.MessageBox]::Show("Launch failed: $_", "Souls of the Reaper", 'OK', 'Error') | Out-Null
        }
    })
    # Hand the page the list of installed game languages BEFORE its own scripts
    # run (AddScriptToExecuteOnDocumentCreatedAsync registers a script injected
    # ahead of the document's inline <script> on every navigation). The Language
    # row is built from window.INSTALLED_LANGS, so only installed locales appear.
    # Fire-and-forget (do NOT block the UI thread with .GetResult() - the
    # WebView2 completion is posted to this same thread and would deadlock).
    # WebView2 serializes calls to the browser process in order, so the script
    # is registered before the Navigate below is processed.
    $injectJs = "window.INSTALLED_LANGS = $InstalledLangsJson; window.SAVED_STATE = $SavedStateJson;"
    $sender.CoreWebView2.AddScriptToExecuteOnDocumentCreatedAsync($injectJs) | Out-Null

    # Cache-bust: WebView2's persisted UserDataFolder can serve a stale cached
    # copy of this same file:// URL across runs even after the html changes.
    $cacheBust = (Get-Item -LiteralPath $HtmlPath).LastWriteTimeUtc.Ticks
    $sender.CoreWebView2.Navigate((([uri]$HtmlPath).AbsoluteUri) + "?v=$cacheBust")
})

$form.Controls.Add($webView)
$form.Add_Shown({ $webView.EnsureCoreWebView2Async($null) | Out-Null })
[System.Windows.Forms.Application]::Run($form)
