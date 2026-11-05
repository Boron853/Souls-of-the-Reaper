#!/usr/bin/env python3
"""Build the shared port on Windows with the pinned ReXGlue SDK (Direct3D 12 and Vulkan).

Parallels build_linux.py: the same pinned SDK commit, the same common patches
(patches/common) and the same codegen output, plus patches/windows/rexglue-windows.patch for the
Direct3D 12 renderer and patches/windows/rexglue-gpu-backend.patch, which adds
the gpu_backend setting. The SDK compiles both renderers into one plugin and the
game picks one at launch (--gpu_backend=d3d12|vulkan). Needs Visual Studio 2022 (C++ and CMake workload), LLVM
clang 22+, Git and Python on the machine.
"""
import argparse
import hashlib
import os
import pathlib
import shutil
import subprocess
import sys

from codegen_title_update import generate
from sdk_patches import apply_common_patches, apply_patch, checkout_pinned_sdk, clear_stamp, write_stamp
from title_updates import DISC_SHA256, USA_UPDATE_SHA256, update_layout

ROOT = pathlib.Path(__file__).resolve().parents[1]
VS_CMAKE = pathlib.Path(r"C:\Program Files\Microsoft Visual Studio\2022\Community\Common7\IDE"
                        r"\CommonExtensions\Microsoft\CMake")


def run(*args, cwd=ROOT):
    print("$ " + " ".join(str(arg) for arg in args), flush=True)
    subprocess.run([str(arg) for arg in args], cwd=cwd, check=True)


def add_tool_paths():
    """Add the usual install locations of clang, CMake and Ninja when they are not on PATH."""
    candidates = [pathlib.Path(r"C:\Program Files\LLVM\bin"), VS_CMAKE / "CMake/bin", VS_CMAKE / "Ninja"]
    for tool, folder in (("clang", candidates[0]), ("cmake", candidates[1]), ("ninja", candidates[2])):
        if not shutil.which(tool) and folder.is_dir():
            os.environ["PATH"] = f"{folder}{os.pathsep}{os.environ['PATH']}"


def prepare_path():
    add_tool_paths()
    missing = [tool for tool in ("git", "clang", "clang++", "cmake", "ninja") if not shutil.which(tool)]
    if missing:
        raise ValueError(f"Not found on PATH: {', '.join(missing)}. Install Visual Studio 2022 with the C++ "
                         "and CMake workload, and LLVM clang 22+.")


def restore_symlinks(sdk):
    """Git checks symlinks out as text stubs on Windows; replace them with copies of their targets."""
    out = subprocess.check_output(["git", "-C", str(sdk / "thirdparty/libmspack"), "ls-files", "-s"], text=True)
    for line in out.splitlines():
        mode, _, _, name = line.split(maxsplit=3)
        if mode != "120000":
            continue
        link = sdk / "thirdparty/libmspack" / name
        target = link.parent / link.read_text().strip()
        if target.is_file() and link.stat().st_size < 260:
            shutil.copyfile(target, link)


def build_sdk(args):
    sdk = args.sdk_source
    # Long paths: a launcher's fetched sources sit deeper than a checkout, and the
    # SDK's vulkan-loader test files then pass Windows' 260-character limit.
    lock = checkout_pinned_sdk(sdk, run, config=("core.autocrlf=false", "core.longpaths=true"))
    restore_symlinks(sdk)
    apply_common_patches(sdk)
    apply_patch(sdk, ROOT / "patches/windows/rexglue-windows.patch")
    apply_patch(sdk, ROOT / "patches/windows/rexglue-gpu-backend.patch")
    shutil.copyfile(ROOT / "patches/windows/src/d3d_screenshot.cpp", sdk / "src/graphics/d3d12/d3d_screenshot.cpp")
    run("cmake", "--preset", "win-amd64", "-DREXGLUE_ENABLE_TRACY=OFF", "-DREXGLUE_BUILD_TESTS=OFF",
        "-DREXGLUE_USE_D3D12=ON", "-DREXGLUE_USE_VULKAN=ON", cwd=sdk)
    build = sdk / "out/build/win-amd64"
    run("cmake", "--build", build, "--config", "RelWithDebInfo", "--parallel", args.jobs)
    clear_stamp(args.sdk_prefix)
    run("cmake", "--install", build, "--config", "RelWithDebInfo", "--prefix", args.sdk_prefix)
    write_stamp(args.sdk_prefix, "win")
    return sdk / "out/win-amd64/RelWithDebInfo/rexgluerd.exe"


def codegen_exe(args):
    exe = args.sdk_source / "out/win-amd64/RelWithDebInfo/rexgluerd.exe"
    if not exe.is_file():
        raise ValueError("SDK not built; use --build-sdk")
    return exe


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter,
                                     allow_abbrev=False)
    parser.add_argument("--build-sdk", action="store_true", help="Clone, patch, build and install the pinned SDK")
    parser.add_argument("--sdk-source", type=pathlib.Path, default=ROOT / "tools/rexglue-sdk-win")
    parser.add_argument("--sdk-prefix", type=pathlib.Path, default=ROOT / "tools/rexglue-install-win")
    parser.add_argument("--game-dir", type=pathlib.Path, default=ROOT / "game")
    parser.add_argument("--title-update", choices=["usa"], help="Build the verified USA update executable separately")
    parser.add_argument("--no-extra-features", dest="plain", action="store_true",
                        help="Compile without the optional PC features (separate -plain directory). "
                             "By default they are built in and switched on at launch with --extra_features")
    parser.add_argument("--extra-features", action="store_true", help=argparse.SUPPRESS)  # now the default
    parser.add_argument("--skip-codegen", action="store_true", help="Reuse previously generated sources")
    parser.add_argument("--jobs", type=int, default=os.cpu_count() or 8)
    args = parser.parse_args()
    args.extra_features = not args.plain
    if args.jobs < 1:
        parser.error("--jobs must be positive")
    for name in ("sdk_source", "sdk_prefix", "game_dir"):
        setattr(args, name, getattr(args, name).resolve())
    try:
        prepare_path()
        if args.build_sdk:
            build_sdk(args)
        rexglue = codegen_exe(args)
        if not (args.sdk_prefix / "lib/cmake/rexglue").is_dir():
            raise ValueError("SDK not installed; use --build-sdk")
        xex = update_layout(args.game_dir)[2] if args.title_update else args.game_dir / "Default.xex"
        expected = USA_UPDATE_SHA256 if args.title_update else DISC_SHA256
        if not xex.is_file() or hashlib.sha256(xex.read_bytes()).hexdigest() != expected:
            raise ValueError(f"Default.xex missing or SHA-256 mismatch for {args.title_update or 'base-disc'} build")
        generate("update" if args.title_update else "base", args.game_dir, rexglue, args.skip_codegen)
        variant = ("update-" if args.title_update else "") + ("" if args.extra_features else "plain-")
        build = ROOT / f"port/out/build/win-amd64-{variant}relwithdebinfo"
        options = [f"-DSOULS_ENABLE_EXTRA_FEATURES={'ON' if args.extra_features else 'OFF'}",
                   f"-DSOULS_TITLE_UPDATE={'ON' if args.title_update else 'OFF'}"]
        if args.extra_features:
            options.append(f"-DSOULS_BASE_XEX={xex}")
        run("cmake", "-S", ROOT / "port", "-B", build, "-G", "Ninja", "-DCMAKE_BUILD_TYPE=RelWithDebInfo",
            "-DCMAKE_CXX_COMPILER=clang++", "-DCMAKE_CXX_FLAGS=-march=x86-64-v2",
            f"-DCMAKE_PREFIX_PATH={args.sdk_prefix}", *options)
        run("cmake", "--build", build, "--parallel", args.jobs)
        print(f"Built {build / 'diablo3.exe'}")
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        parser.exit(1, f"Windows build failed: {error}\n")


if __name__ == "__main__":
    sys.exit(main())
