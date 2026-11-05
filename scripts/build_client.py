#!/usr/bin/env python3
"""Build playable clients from a Diablo III disc image and, optionally, the USA update package.

Each step is skipped when its output already exists and verifies, so an
interrupted build can be resumed with the same command. Progress lines of the
form ``::step::<n>/<total>::<title>`` are printed for the launcher.
"""
import argparse
import hashlib
import json
import os
import pathlib
import platform
import re
import shutil
import subprocess
import sys

import build_windows
import codegen_title_update
import extract_disc
import extract_update
import sdk_patches
from stage_title_update import USA_UPDATE_PACKAGE_SHA256, stage, stage_overlay
from title_updates import DISC_SHA256, USA_UPDATE_SHA256, update_layout

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
UPDATE_CPKS = ("Patch.cpk", "Patch2.cpk", "enUS_Patch.cpk", "enUS_Patch2.cpk")
# Variant id -> (title update, plain). Normal builds carry the optional PC features and
# switch them on at launch with --extra_features; "plain" omits them from the executable.
VARIANTS = {"base": (False, False), "update": (True, False),
            "base-plain": (False, True), "update-plain": (True, True)}
LABELS = {"base": "Base", "update": "Update", "base-plain": "Base (no extras)", "update-plain": "Update (no extras)"}
WINDOWS = platform.system() == "Windows"
GIB = 1024 ** 3
# Rough upper bounds measured on Linux RelWithDebInfo builds.
SDK_BYTES, VARIANT_BYTES, CODEGEN_BYTES = 3 * GIB, 1 * GIB, GIB // 2


class BuildError(Exception):
    pass


def step(index, total, title):
    print(f"::step::{index}/{total}::{title}", flush=True)


def sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def run(*args, cwd=ROOT):
    print("$ " + " ".join(str(arg) for arg in args), flush=True)
    subprocess.run([str(arg) for arg in args], cwd=cwd, check=True)


def base_ready(game_dir):
    """A completed extraction writes disc-manifest.json last."""
    xex = game_dir / "Default.xex"
    return (game_dir / "disc-manifest.json").is_file() and xex.is_file() and sha256(xex) == DISC_SHA256


def update_ready(game_dir):
    """True for a complete overlay (`<game>/update`) or a complete separately staged folder."""
    _, update_root, xex = update_layout(game_dir)
    return ((update_root / "applied-update-manifest.json").is_file() and xex.is_file()
            and sha256(xex) == USA_UPDATE_SHA256
            and all((update_root / "CPKs" / name).is_file() for name in UPDATE_CPKS))


def game_update_dir(args):
    """The folder update is built and run from: --game-dir-update, else the base folder (overlay)."""
    return args.game_dir_update or args.game_dir


def cmake_version(cmake):
    try:
        output = subprocess.run([cmake, "--version"], capture_output=True, text=True, check=True).stdout
    except (OSError, subprocess.CalledProcessError):
        return None
    match = re.search(r"(\d+)\.(\d+)", output)
    return (int(match[1]), int(match[2])) if match else None


def missing_tools(args, compile_needed, need_patcher):
    """Human-readable problems that would stop the build before it starts."""
    problems = []
    if not shutil.which("git") and (compile_needed or need_patcher):
        problems.append("git is required to fetch the pinned SDK and patch tools.")
    if not compile_needed and not need_patcher:
        return problems
    if not args.cmake:
        problems.append("CMake 3.25 or newer was not found; install it or choose its path.")
    elif (cmake_version(args.cmake) or (0, 0)) < (3, 25):
        problems.append(f"{args.cmake} is older than CMake 3.25.")
    for tool in ("ninja", "clang", "clang++"):
        if not shutil.which(tool):
            problems.append(f"{tool} was not found on PATH.")
    if compile_needed and platform.system() not in ("Linux", "Windows"):
        problems.append("Automated compilation supports Linux and Windows only; use --data-only to prepare "
                        "the game folders.")
    return problems


HOST = "win" if WINDOWS else "linux"


def sdk_state(args):
    """"missing", "stale" (built from another SDK commit or patch set) or "current".

    An SDK installed elsewhere with --sdk-prefix is trusted as given: its patches
    are the caller's responsibility.
    """
    if WINDOWS:
        built = ((args.sdk_prefix / "lib/cmake/rexglue").is_dir()
                 and (args.sdk_source / "out/win-amd64/RelWithDebInfo/rexgluerd.exe").is_file())
    else:
        built = (args.sdk_prefix / "bin/rexglue").is_file()
    if not built:
        return "missing"
    if args.sdk_prefix != (ROOT / f"tools/rexglue-install-{HOST}").resolve():
        return "current"
    return sdk_patches.stamp_state(args.sdk_prefix, HOST)


def sdk_installed(args):
    return sdk_state(args) == "current"


def disc_bytes(iso):
    with iso.open("rb") as source:
        return sum(length for _, is_dir, _, length in extract_disc.Disc(source).entries() if not is_dir)


def existing_ancestor(path):
    return next(p for p in (path, *path.parents) if p.exists())


def same_filesystem(a, b):
    return os.stat(existing_ancestor(a)).st_dev == os.stat(existing_ancestor(b)).st_dev


def check_free_space(args, need_base, need_separate_update, need_sdk, compile_needed):
    """Fail early when a drive the build writes to lacks room for what is still to do."""
    writes = []  # (folder, bytes)
    if need_base:  # an interrupted extraction resumes, so only the rest is needed
        writes.append((args.game_dir, extract_disc.bytes_to_extract(args.iso, args.game_dir)))
    if need_separate_update and not same_filesystem(args.game_dir, args.game_dir_update):
        # A separate update folder hardlinks the disc files when it can and copies them otherwise.
        disc = disc_bytes(args.iso) if need_base else sum(
            f.stat().st_size for f in args.game_dir.rglob("*") if f.is_file())
        writes.append((args.game_dir_update, disc))
    if need_sdk:
        writes.append((args.sdk_source, SDK_BYTES))
    if compile_needed:
        writes.append((ROOT / "port", VARIANT_BYTES * len(args.variants) + CODEGEN_BYTES * 2))
    needed = {}  # device -> [folder, bytes]
    for folder, size in writes:
        device = os.stat(existing_ancestor(folder)).st_dev
        needed.setdefault(device, [folder, 0])[1] += size
    for folder, size in needed.values():
        free = shutil.disk_usage(existing_ancestor(folder)).free
        if size > free:
            raise BuildError(f"About {size / GIB:.1f} GiB of free space is needed on the drive of {folder}; "
                             f"{free / GIB:.1f} GiB is free.")


def verify_iso(iso):
    if not iso.is_file():
        raise BuildError(f"Disc image not found: {iso}")
    try:
        found = extract_disc.file_sha256(iso, "Default.xex")
    except ValueError as error:
        raise BuildError(f"{iso.name} is not a readable Xbox 360 game disc image ({error}).")
    if found == USA_UPDATE_SHA256:
        raise BuildError("That image already contains the update executable; choose the original disc image.")
    if found != DISC_SHA256:
        raise BuildError(f"{iso.name} is not the USA Diablo III: Reaper of Souls - Ultimate Evil Edition disc "
                         "(Default.xex does not match). Other regions are not supported yet.")


def verify_package(package):
    if not package.is_file():
        raise BuildError(f"Title update package not found: {package}")
    if sha256(package) != USA_UPDATE_PACKAGE_SHA256:
        raise BuildError(f"{package.name} is not the verified USA Title Update package "
                         f"(expected SHA-256 {USA_UPDATE_PACKAGE_SHA256}).")


def build_patcher(args):
    """Clone the pinned XenonRecomp and build tools/d3-patch/d3-patch."""
    lock = json.loads((SCRIPTS / "d3-patch/xenonrecomp.lock.json").read_text())
    source = ROOT / "tools/XenonRecomp"
    sdk_patches.checkout_pinned(source, lock["repository"], lock["commit"], run)
    build = ROOT / "tools/d3-patch"
    run(args.cmake, "-S", SCRIPTS / "d3-patch", "-B", build, "-G", "Ninja", "-DCMAKE_BUILD_TYPE=Release",
        "-DCMAKE_C_COMPILER=clang", "-DCMAKE_CXX_COMPILER=clang++", f"-DXENONRECOMP_DIR={source}")
    run(args.cmake, "--build", build, "--target", "d3-patch", "--parallel", args.jobs)
    return build / ("d3-patch.exe" if os.name == "nt" else "d3-patch")


def build_variant(args, variant):
    update, plain = VARIANTS[variant]
    game = game_update_dir(args) if update else args.game_dir
    command = [sys.executable, SCRIPTS / ("build_windows.py" if WINDOWS else "build_linux.py"),
               "--game-dir", game, "--sdk-prefix", args.sdk_prefix, "--jobs", args.jobs]
    if WINDOWS:
        command += ["--sdk-source", args.sdk_source]  # CMake, Ninja and Clang come from PATH
    else:
        command += ["--cmake", args.cmake]
    if update:
        command += ["--title-update", "usa"]
    if plain:
        command.append("--no-extra-features")
    # Reuse sources generated earlier from the same executable, hints and SDK code generator.
    if not args.regenerate and codegen_title_update.stamp_current("update" if update else "base"):
        command.append("--skip-codegen")
    run(*command)


def plan(args):
    """Return [(title, action)] for the work still to do, after checking inputs."""
    steps = []
    wanted_update = any(VARIANTS[v][0] for v in args.variants) or (args.data_only and args.title_update)
    need_base = not base_ready(args.game_dir)
    overlay = args.game_dir_update is None
    need_update = wanted_update and not update_ready(game_update_dir(args))
    compile_needed = bool(args.variants) and not args.data_only
    need_sdk = compile_needed and not sdk_installed(args)

    if need_base and not args.iso:
        raise BuildError(f"No extracted disc in {args.game_dir}; choose your disc image (ISO).")
    if need_update:
        incomplete = args.game_dir / "update" if overlay else args.game_dir_update
        if incomplete.exists():
            raise BuildError(f"{incomplete} exists but is not a complete staged update; "
                             "move it aside or choose another update game folder.")
        if not args.title_update:
            raise BuildError("update builds need the USA Title Update package.")
    problems = missing_tools(args, compile_needed, need_update and not args.patcher)
    if problems:
        raise BuildError("\n".join(problems))
    if need_sdk and args.no_sdk_download:
        raise BuildError("The pinned ReXGlue SDK is not built yet and downloading it was not approved."
                         if sdk_state(args) == "missing" else
                         "The installed ReXGlue SDK is out of date and rebuilding it was not approved.")

    if need_base:
        verify_iso(args.iso)
    if need_update:
        verify_package(args.title_update)

    check_free_space(args, need_base, need_update and not overlay, need_sdk, compile_needed)

    if need_base:
        steps.append(("Extract disc image", lambda: extract_disc.extract(args.iso, args.game_dir)))
    if need_update:
        update_dir = ROOT / "port/out/update-staging"
        steps.append(("Extract title update", lambda: extract_update.extract(args.title_update, update_dir)))
        patcher = [args.patcher]
        if not args.patcher:
            def patcher_step():
                patcher[0] = build_patcher(args)
            steps.append(("Build update patch tool", patcher_step))
        if overlay:
            steps.append(("Apply update", lambda: stage_overlay(args.game_dir, update_dir, patcher[0])))
        else:
            steps.append(("Apply update", lambda: stage(args.game_dir, update_dir, args.game_dir_update, patcher[0])))
    if need_sdk:
        sdk = argparse.Namespace(sdk_source=args.sdk_source, sdk_prefix=args.sdk_prefix, jobs=args.jobs)
        if WINDOWS:
            steps.append(("Build ReXGlue SDK (one-time)", lambda: build_windows.build_sdk(sdk)))
        else:
            import build_linux
            steps.append(("Build ReXGlue SDK (one-time)", lambda: build_linux.build_sdk(sdk, args.cmake)))
    if compile_needed:
        for variant in args.variants:
            steps.append((f"Build {LABELS[variant]} (codegen and compile)", lambda v=variant: build_variant(args, v)))
    return steps


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter,
                                     allow_abbrev=False)
    parser.add_argument("--iso", type=pathlib.Path, help="USA Ultimate Evil Edition disc image")
    parser.add_argument("--title-update", type=pathlib.Path, metavar="PACKAGE",
                        help="USA Title Update package")
    parser.add_argument("--variants", default=None,
                        help="Comma-separated builds: base, update, base-plain, update-plain "
                             "(default: base, plus update when a title update is given)")
    parser.add_argument("--data-only", action="store_true",
                        help="Only prepare the game folders; do not compile")
    parser.add_argument("--game-dir", type=pathlib.Path, default=ROOT / "game")
    parser.add_argument("--game-dir-update", type=pathlib.Path, default=None,
                        help="Stage the update as a complete separate folder here. By default the update is a small "
                             "update/ overlay inside --game-dir (an existing ./game-update is still used)")
    host = "win" if WINDOWS else "linux"
    parser.add_argument("--sdk-source", type=pathlib.Path, default=ROOT / f"tools/rexglue-sdk-{host}")
    parser.add_argument("--sdk-prefix", type=pathlib.Path, default=ROOT / f"tools/rexglue-install-{host}")
    parser.add_argument("--patcher", type=pathlib.Path, help="Existing d3-patch executable")
    parser.add_argument("--cmake", default="cmake")
    parser.add_argument("--jobs", type=int, default=os.cpu_count() or 8)
    parser.add_argument("--regenerate", action="store_true", help="Rerun codegen even if sources are current")
    parser.add_argument("--no-sdk-download", action="store_true",
                        help="Fail instead of cloning and building the pinned SDK when it is missing "
                             "(the launcher passes this until the user approves the download)")
    parser.add_argument("--print-sdk-status", action="store_true",
                        help="Print the ReXGlue SDK state (pinned commit, missing/stale/current) as JSON and stop")
    parser.add_argument("--check", action="store_true", help="Validate inputs and tools, list the steps, and stop")
    args = parser.parse_args(argv)
    if args.jobs < 1:
        parser.error("--jobs must be positive")
    if args.variants is None:
        args.variants = ["base"] + (["update"] if args.title_update else [])
    else:
        args.variants = [v.strip() for v in args.variants.split(",") if v.strip()]
        unknown = [v for v in args.variants if v not in VARIANTS]
        if unknown:
            parser.error(f"unknown variant(s): {', '.join(unknown)}")
    for legacy in (ROOT / "game-update", ROOT / "game-tu2"):  # game-tu2 predates the rename
        if args.game_dir_update is None and legacy.exists() and update_ready(legacy):
            args.game_dir_update = legacy
    for name in ("iso", "title_update", "game_dir", "game_dir_update", "sdk_source", "sdk_prefix", "patcher"):
        value = getattr(args, name)
        if value is not None:
            setattr(args, name, value.expanduser().resolve())
    if args.print_sdk_status:
        lock = sdk_patches.lock()
        print(json.dumps({"state": sdk_state(args), "repository": lock["repository"], "commit": lock["commit"]}))
        return
    try:
        if WINDOWS:
            # Finds clang, CMake and Ninja in their usual install folders (Visual Studio, LLVM).
            build_windows.add_tool_paths()
        args.cmake = shutil.which(args.cmake)
        steps = plan(args)
        if args.check:
            for index, (title, _) in enumerate(steps, 1):
                print(f"{index}. {title}")
            print("Everything is already built." if not steps else "Inputs and tools look good.")
            return
        for index, (title, action) in enumerate(steps, 1):
            step(index, len(steps), title)
            action()
        print("::done::", flush=True)
        print("Build complete." if steps else "Everything is already built.")
    except (BuildError, OSError, ValueError, KeyError, subprocess.CalledProcessError) as error:
        parser.exit(1, f"Build failed: {error}\n")


if __name__ == "__main__":
    main()
