#!/usr/bin/env python3
"""Write the launcher-managed cvars into diablo3.toml.

Linux/Windows counterpart of apply_config.ps1: rewrites only the managed keys
and preserves everything else (F4 keybind remaps, user cvars, comments on
preserved lines). D3D12-only keys are omitted on Linux by default.

The config file lives next to the diablo3 executable (ReXApp resolves it as
<exe dir>/diablo3.toml, e.g.
port/out/build/linux-amd64-relwithdebinfo/diablo3.toml).

Usage:
  python3 apply_config.py --toml path/to/diablo3.toml --game-data-root game \
      --fps 60 --rtp rtv --present-effect fsr

  # Linux defaults (no D3D12 keys):
  python3 apply_config.py --game-data-root "$PWD/game"
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

BUILD_PRESETS = [
    "linux-amd64-relwithdebinfo",
    "linux-amd64-debug",
    "linux-amd64-release",
    "win-amd64-relwithdebinfo",
    "win-amd64-debug",
    "win-amd64-release",
]


def find_default_toml() -> Path:
    repo = Path(__file__).resolve().parent
    for preset in BUILD_PRESETS:
        candidate = repo / "port" / "out" / "build" / preset / "diablo3.toml"
        if candidate.parent.is_dir():
            return candidate
    return repo / "port" / "out" / "build" / "linux-amd64-relwithdebinfo" / "diablo3.toml"


def parse_bool(value: str) -> str:
    lowered = value.strip().lower()
    if lowered in {"1", "true", "yes", "on"}:
        return "true"
    if lowered in {"0", "false", "no", "off"}:
        return "false"
    raise argparse.ArgumentTypeError(f"expected true/false, got {value!r}")


def quote(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--toml", type=Path, default=find_default_toml(), help="diablo3.toml to update")
    parser.add_argument("--game-data-root", help="directory containing the extracted game data (CPKs, default.xex)")
    parser.add_argument("--fps", type=int, default=60)
    parser.add_argument("--vsync", type=parse_bool, default="true")
    parser.add_argument("--rtp", choices=["rov", "rtv"], default="rov", help="D3D12 render target path")
    parser.add_argument("--mnk-mode", type=parse_bool, default="true")
    parser.add_argument("--mnk-mouse", type=parse_bool, default="false")
    parser.add_argument("--cursor-visible", type=parse_bool, default="true")
    parser.add_argument("--fullscreen", type=parse_bool, default="false")
    parser.add_argument(
        "--borderless",
        type=parse_bool,
        default="false",
        help="remove window decorations and place the window at the top-left",
    )
    parser.add_argument("--depth-fix", type=parse_bool, default="false", help="obsolete, accepted for compatibility")
    parser.add_argument("--present-effect", choices=["bilinear", "cas", "fsr"], default="fsr")
    parser.add_argument(
        "--resolution",
        default=None,
        help="Guest video mode and startup window: 720p, 1080p, 1440p, 4k, or WIDTHxHEIGHT "
        "(for example 1920x1080). Omit to keep the existing value.",
    )
    parser.add_argument("--res-scale", type=int, choices=[1, 2, 3], default=1)
    parser.add_argument(
        "--dynamic-resolution",
        type=parse_bool,
        default="false",
        help="adapt the draw resolution scale to the target frame rate",
    )
    parser.add_argument(
        "--dynamic-target-fps",
        type=int,
        default=None,
        help="target FPS for dynamic resolution (defaults to --fps, or 60 when --fps is 0)",
    )
    parser.add_argument(
        "--dynamic-min-scale",
        type=int,
        choices=[1, 2, 3],
        default=1,
        help="lowest draw resolution scale used by dynamic resolution",
    )
    parser.add_argument("--user-language", type=int, default=1)
    parser.add_argument("--user-country", type=int, default=103)
    parser.add_argument(
        "--platform",
        choices=["auto", "linux", "windows"],
        default="auto",
        help="windows also writes the D3D12-only render target cvars",
    )
    args = parser.parse_args()

    platform = args.platform
    if platform == "auto":
        platform = "windows" if sys.platform == "win32" else "linux"

    managed: dict[str, str] = {}
    if platform == "windows":
        managed["render_target_path_d3d12"] = quote(args.rtp)
    else:
        # Vulkan host render targets (the non-interlock path) still need the
        # same ownership tricks as D3D12 RTV.
        managed["render_target_path_vulkan"] = quote("host")
    # Cross-map clear-like ownership inheritance (RTV/Vulkan ground lighting).
    managed["rtv_color_depth_ownership_mode"] = "8"
    # Run unclipped draw vertex shaders on the CPU for exact EDRAM area.
    managed["execute_unclipped_draw_vs_on_cpu"] = "true"

    dynamic_target_fps = args.dynamic_target_fps
    if dynamic_target_fps is None:
        dynamic_target_fps = args.fps if args.fps > 0 else 60
    managed.update(
        {
            "draw_resolution_scale_x": str(args.res_scale),
            "draw_resolution_scale_y": str(args.res_scale),
            "d3_frame_limit": str(args.fps),
            "d3_dynamic_resolution": args.dynamic_resolution,
            "d3_dynamic_resolution_target_fps": str(dynamic_target_fps),
            "d3_dynamic_resolution_min_scale": str(args.dynamic_min_scale),
            "vsync": args.vsync,
            "mnk_mode": args.mnk_mode,
            "mnk_mouse": args.mnk_mouse,
            "mnk_cursor_visible": args.cursor_visible,
            "fullscreen": args.fullscreen,
            "borderless": args.borderless,
            "present_effect": quote(args.present_effect),
            "user_language": str(args.user_language),
            "user_country": str(args.user_country),
        }
    )
    if args.resolution:
        managed["resolution"] = quote(args.resolution)
    if args.game_data_root:
        managed["game_data_root"] = quote(str(Path(args.game_data_root).expanduser().resolve()))

    depth_keys = {"depth_float24_convert_in_pixel_shader", "depth_float24_round"}
    # Delete stale keys that belong to the other platform / backend.
    backend_keys = {"render_target_path_d3d12", "render_target_path_vulkan"}
    owned = set(managed) | depth_keys | backend_keys | {"game_data_root"}

    preserved: list[str] = []
    toml: Path = args.toml
    if toml.exists():
        for line in toml.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            key = stripped.split("=", 1)[0].strip()
            if key in owned:
                continue
            preserved.append(line)

    out = ["# Managed by SoulsOfTheReaper. Your F4 overlay remaps are preserved below."]
    out.extend(f"{key} = {value}" for key, value in managed.items())
    if preserved:
        out.append("")
        out.append("# --- User remaps / cvars (F4 overlay) ---")
        out.extend(preserved)

    toml.parent.mkdir(parents=True, exist_ok=True)
    toml.write_text("\n".join(out) + "\n", encoding="utf-8")

    print(f"Config: {args.fps}fps vsync={args.vsync} present={args.present_effect} "
          f"resolution={args.resolution or 'existing'} borderless={args.borderless} "
          f"res_scale={args.res_scale}x dynamic={args.dynamic_resolution} "
          f"target={dynamic_target_fps}fps lang={args.user_language} country={args.user_country}")
    if platform == "windows":
        print(f"D3D12: render={args.rtp} ownership_mode=8 execute_unclipped_draw_vs_on_cpu=true")
    else:
        print("Vulkan: render=host ownership_mode=8 execute_unclipped_draw_vs_on_cpu=true")
    print(f"Wrote {toml}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
