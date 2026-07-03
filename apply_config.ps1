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
  [string]$DepthFix = "false"   # obsoleto (s19): sin efecto, se acepta por compat
)

# Keys managed by the launcher (everything else in the toml is preserved as-is).
$managed = [ordered]@{
  'render_target_path_d3d12' = '"' + $Rtp + '"'
  # s19: ownership mode 8 = herencia cross-map clear-like (arregla la iluminacion
  # del suelo en RTV). Solo lo lee el path RTV; inofensivo en ROV.
  'rtv_color_depth_ownership_mode' = '8'
  # s21: VS de draws sin clipping ejecutado en CPU para estimar el area REAL
  # escrita (default original de Xenia). Sin esto, los quads screen-space claman
  # TODO el EDRAM y la escena hace round-trips lossy por otros buffers cada
  # frame -> paneles negros/desplazados en el humo (BUG B) y fugas del buffer
  # de siluetas (lineas rojas/azules, BUG A) en RTV. Inofensivo en ROV.
  'execute_unclipped_draw_vs_on_cpu' = 'true'
  'd3_frame_limit'           = "$Fps"
  'vsync'                    = $Vsync
  'mnk_mode'                 = $MnkMode
  'mnk_mouse'                = $MnkMouse
  'mnk_cursor_visible'       = $CursorVisible
}
# depth_float24_*: probados SIN efecto (s18/s19) - se limpian del toml si quedaron.
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
