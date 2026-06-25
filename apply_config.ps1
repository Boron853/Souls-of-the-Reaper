<#
.SYNOPSIS
  Merge launcher-managed cvars into diablo3.toml WITHOUT clobbering user keybind
  remaps (which the in-game F4 settings overlay persists to the same file).
  Re-writes only the managed keys; preserves every other line (e.g. keybind_*).
#>
param(
  [Parameter(Mandatory)][string]$Toml,
  [int]$Fps = 60,
  [string]$Vsync = "true",
  [string]$Rtp = "rov",
  [string]$MnkMode = "false",
  [string]$MnkMouse = "false",
  [string]$CursorVisible = "true",
  [string]$DepthFix = "false"
)

# Keys managed by the launcher (everything else in the toml is preserved as-is).
$managed = [ordered]@{
  'render_target_path_d3d12' = '"' + $Rtp + '"'
  'd3_frame_limit'           = "$Fps"
  'vsync'                    = $Vsync
  'mnk_mode'                 = $MnkMode
  'mnk_mouse'                = $MnkMouse
  'mnk_cursor_visible'       = $CursorVisible
}
# Depth-conversion fix only matters on the experimental RTV path.
$depthKeys = @('depth_float24_convert_in_pixel_shader', 'depth_float24_round')
if ($DepthFix -eq 'true') {
  $managed['depth_float24_convert_in_pixel_shader'] = 'true'
  $managed['depth_float24_round'] = 'true'
}

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

$out = @('# Managed by launcher (launch.bat). Your F4 overlay remaps are preserved below.')
foreach ($k in $managed.Keys) { $out += "$k = $($managed[$k])" }
if ($preserved.Count -gt 0) {
  $out += ''
  $out += '# --- User remaps / cvars (F4 overlay) ---'
  $out += $preserved
}

Set-Content -LiteralPath $Toml -Value $out -Encoding utf8
Write-Host ("Config: {0}fps vsync={1} render={2} mnk_mode={3} mouse={4} cursor_visible={5}" -f `
  $Fps, $Vsync, $Rtp, $MnkMode, $MnkMouse, $CursorVisible)
