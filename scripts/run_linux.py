#!/usr/bin/env python3
"""Launch the Linux base-disc port or its asset-free Vulkan diagnostics."""
import argparse
import hashlib
import json
import os
import pathlib
import subprocess

from title_updates import DISC_SHA256, USA_UPDATE_SHA256, update_layout

ROOT = pathlib.Path(__file__).resolve().parents[1]


def prepare_ps3_import(source, state):
    from import_ps3_save import DEFAULT_XUID, SaveError, import_save

    source, state = source.resolve(), state.resolve()
    if source == state or source in state.parents or state in source.parents:
        raise SaveError("Imported state must be separate from the PS3 source")
    if not state.exists():
        import_save(source, state, DEFAULT_XUID)
        return "Imported PS3 save"
    try:
        report = json.loads((state / "import-report.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise SaveError("Existing state has no valid PS3 import report; choose a new --state-dir") from error
    if (not isinstance(report, dict) or report.get("format") != "souls-ps3-import-v1"
            or report.get("source") != str(source) or report.get("xuid") != DEFAULT_XUID):
        raise SaveError("Existing state belongs to a different import; choose a new --state-dir")
    package = state / DEFAULT_XUID / "394F07D4/00000001/d3save"
    if not (package / "account.dat").is_file() or not (package / "profile.dat").is_file() or not (package / "heroes").is_dir():
        raise SaveError("Imported state is incomplete; choose a new --state-dir")
    # Subsequent game saves belong to the player. Never re-copy source payloads.
    return "Reusing imported PS3 save"


def option_value(extra, name, default):
    for index, arg in enumerate(extra):
        if arg.startswith(name + "="):
            return arg.split("=", 1)[1]
        if arg == name and index + 1 < len(extra):
            return extra[index + 1]
    return default


def saved_render_scale(state):
    """Scale from pc-settings.ini, or from the bare-number file earlier builds wrote."""
    text = None
    try:
        for line in (state / "pc-settings.ini").read_text(encoding="utf-8").splitlines():
            key, _, value = line.partition("=")
            if key == "render_scale":
                text = value
    except OSError:
        pass
    try:
        if text is None:
            text = (state / "pc-render-scale.txt").read_text(encoding="utf-8")
        value = int(text.strip())
        return value if 1 <= value <= 3 else None
    except (OSError, ValueError):
        return None


def launch_command(args, extra):
    if args.probe or args.render_smoke:
        name = "d3-gpu-probe" if args.probe else "d3-render-smoke"
        return [str(ROOT / "port/out/build/linux-probe" / name), *extra]
    state = pathlib.Path(option_value(extra, "--user_data_root", str(args.state_dir.resolve())))
    if not state.is_absolute():
        state = ROOT / state
    state = state.resolve()
    defaults = {
        "--game_data_root": args.game_dir.resolve(),
        "--user_data_root": state,
        "--cache_root": state / "cache",
        "--log_file": state / "diablo3.log",
        "--render_target_path_vulkan": "fsi",
        "--mnk_mode": "true",
    }
    overrides = {arg.split("=", 1)[0] for arg in extra if arg.startswith("--")}
    extras = getattr(args, "extra_features", False)
    plain = getattr(args, "plain", False)
    if extras:
        defaults["--extra_features"] = "true"
    if extras and "--fullscreen" in overrides:
        defaults["--pc_use_saved_window_mode"] = "false"
    use_saved = option_value(extra, "--pc_use_saved_render_scale", "true").lower() not in {"false", "0"}
    if extras and overrides.intersection({"--resolution_scale", "--draw_resolution_scale_x", "--draw_resolution_scale_y"}):
        defaults["--pc_use_saved_render_scale"] = "false"
    if extras and use_saved and not overrides.intersection({"--resolution_scale", "--draw_resolution_scale_x", "--draw_resolution_scale_y"}):
        scale = saved_render_scale(state)
        if scale is not None:
            defaults["--resolution_scale"] = scale
    name = "linux-amd64" + ("-update" if getattr(args, "title_update", None) else "") + ("-plain" if plain else "") + "-relwithdebinfo"
    if getattr(args, "title_update", None):
        # The title update reads patch assets through update:\ even with a prepatched XEX.
        game_root = pathlib.Path(option_value(extra, "--game_data_root", str(args.game_dir.resolve())))
        defaults["--update_data_root"] = update_layout(game_root)[1]
    return [str(ROOT / "port/out/build" / name / "diablo3"),
            *(f"{key}={value}" for key, value in defaults.items() if key not in overrides), *extra]


def main():
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--probe", action="store_true")
    mode.add_argument("--render-smoke", action="store_true")
    mode.add_argument("--extra-features", action="store_true",
                      help="Switch on the optional PC menu settings and read the saved render scale")
    mode.add_argument("--plain", action="store_true",
                      help="Run the build compiled without the optional PC features")
    parser.add_argument("--title-update", choices=["usa"], help="Run the separate verified update build")
    parser.add_argument("--username", help="In-game player name (max 15 characters)")
    parser.add_argument("--game-dir", type=pathlib.Path, default=ROOT / "game")
    parser.add_argument("--state-dir", type=pathlib.Path,
                        help="Override the user data directory (the update build uses a separate default)")
    parser.add_argument("--import-ps3-save", type=pathlib.Path,
                        help="Import a PS3 save once into a separate update state, then reuse it")
    args, extra = parser.parse_known_args()
    if args.import_ps3_save and (args.title_update != "usa" or args.probe or args.render_smoke):
        parser.error("--import-ps3-save requires --title-update usa and a game launch")
    if args.title_update:
        if args.probe or args.render_smoke:
            parser.error("--title-update cannot be combined with diagnostic modes")

    if args.state_dir is None:
        data_home = pathlib.Path(os.environ.get("XDG_DATA_HOME") or pathlib.Path.home() / ".local/share")
        name = "souls-of-the-reaper-update" if args.title_update else "souls-of-the-reaper"
        if args.title_update and not (data_home / name).exists() and (data_home / "souls-of-the-reaper-tu2").exists():
            name = "souls-of-the-reaper-tu2"  # saves created before the folder was renamed
        if args.import_ps3_save:
            name += "-ps3-import"
        args.state_dir = data_home / name
    command = launch_command(args, extra)
    if not pathlib.Path(command[0]).is_file():
        flag = " --probe" if args.probe or args.render_smoke else ((" --title-update usa" if args.title_update else "") + (" --no-extra-features" if args.plain else ""))
        parser.error("Executable missing; run scripts/build_linux.py" + flag)
    if not (args.probe or args.render_smoke):
        game = pathlib.Path(option_value(extra, "--game_data_root", str(args.game_dir.resolve())))
        if not game.is_absolute():
            game = ROOT / game
        xex = update_layout(game)[2] if args.title_update else game / "Default.xex"
        if not xex.is_file():
            parser.error("Game directory must contain Default.xex (Linux filenames are case-sensitive)"
                         + ("; for update run build_client.py or stage_title_update.py first" if args.title_update else ""))
        expected = USA_UPDATE_SHA256 if args.title_update else DISC_SHA256
        if hashlib.sha256(xex.read_bytes()).hexdigest() != expected:
            if args.title_update and xex.parent == game:
                parser.error(f"The title update is not installed in {game} (there is no update/Default.xex). Add it with: "
                             f"python3 scripts/build_client.py --title-update <Title Update package> --game-dir {game} --variants update")
            parser.error(f"Executable SHA-256 does not match the {args.title_update or 'base-disc'} build; select the matching --title-update and --game-dir")
        state = pathlib.Path(option_value(extra, "--user_data_root", str(args.state_dir.resolve())))
        if not state.is_absolute():
            state = ROOT / state
        try:
            if args.import_ps3_save:
                from import_ps3_save import SaveError
                try:
                    result = prepare_ps3_import(args.import_ps3_save, state)
                except (OSError, SaveError) as error:
                    parser.exit(1, f"PS3 import failed: {error}\n")
                print(f"{result}: {state.resolve()}", flush=True)
            state.mkdir(parents=True, exist_ok=True)
        except OSError as error:
            parser.exit(1, f"Cannot create user data directory: {error}\n")
    try:
        env = {**os.environ, "SOTR_USERNAME": args.username} if args.username else None
        raise SystemExit(subprocess.run(command, cwd=ROOT, env=env).returncode)
    except KeyboardInterrupt:
        raise SystemExit(130) from None
    except OSError as error:
        parser.exit(1, f"Linux launch failed: {error}\n")


if __name__ == "__main__":
    main()
