#!/usr/bin/env python3
"""End-to-end Linux installer for the Diablo III port.

This is the non-GUI implementation of the full setup flow documented in
README.md and docs/LINUX.md:

  1. extract the Xbox 360 ISO/XISO into the game-data directory;
  2. obtain the pinned ReXGlue SDK (or reuse an existing checkout);
  3. build and install the SDK;
  4. run codegen and apply the generated-code hand patches;
  5. build the Linux game binary;
  6. write the launcher-managed configuration;
  7. optionally launch the game.

The graphical installer calls this script so both the GUI and automation use
the same commands and the same error handling.

Examples:
  python3 port/install_game.py --iso /path/disc.iso --launch
  python3 port/install_game.py --iso /path/disc.iso --extract-only
  python3 port/install_game.py --iso /path/disc.iso --sdk-dir /path/rexglue-sdk
  python3 port/install_game.py --iso /path/disc.iso --sdk-bundle sdk.tar.gz

If cmake/ninja/clang are not on PATH but Nix is available, build steps are run
inside the repository dev shell. The launcher still handles the runtime Nix
environment separately.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EXTRACTOR = ROOT / "port" / "extract_iso.py"
LOCK_FILE = ROOT / "port" / "rexglue.lock.json"
APPLY_CONFIG = ROOT / "apply_config.py"
BUILD_PRESET = "linux-amd64-relwithdebinfo"
TOML = ROOT / "port" / "out" / "build" / BUILD_PRESET / "diablo3.toml"
DEFAULT_OUT = ROOT / "game"
DEFAULT_SDK_BUNDLE = ROOT / "sdk" / "rexglue-sdk-linux-amd64.tar.gz"


class InstallError(RuntimeError):
    pass


def log(message: str = "") -> None:
    print(message, flush=True)


def run(
    command: list[str],
    *,
    env: dict[str, str] | None = None,
    cwd: Path = ROOT,
) -> list[str]:
    """Run a command, stream its output, and return the output lines."""
    log("$ " + " ".join(shlex.quote(part) for part in command))
    try:
        proc = subprocess.Popen(
            command,
            cwd=str(cwd),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
    except OSError as exc:
        raise InstallError(f"could not start {command[0]}: {exc}") from exc

    assert proc.stdout is not None
    lines: list[str] = []
    try:
        for line in proc.stdout:
            print(line, end="", flush=True)
            lines.append(line.rstrip("\n"))
    except KeyboardInterrupt:
        proc.terminate()
        proc.wait()
        raise

    rc = proc.wait()
    if rc != 0:
        raise InstallError(f"command failed with exit code {rc}: {shlex.join(command)}")
    return lines


def find_nix() -> str | None:
    for candidate in ("/run/current-system/sw/bin/nix", "/nix/var/nix/profiles/default/bin/nix"):
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    return shutil.which("nix")


def is_nixos() -> bool:
    return Path("/etc/NIXOS").exists()


def has_build_tools() -> bool:
    compiler = shutil.which("clang-20") or shutil.which("clang") or shutil.which("clang++")
    return bool(
        compiler
        and shutil.which("cmake")
        and shutil.which("ninja")
        and shutil.which("pkg-config")
    )


def nix_command(
    command: list[str], sdk_dir: Path, sdk_install: Path, prebuilt: bool
) -> list[str]:
    nix = find_nix()
    if not nix:
        raise InstallError(
            "cmake/ninja/clang are missing and Nix is not installed. "
            "Install the build prerequisites from docs/LINUX.md or use the Nix dev shell."
        )
    return [
        nix,
        "develop",
        f"path:{ROOT}",
        "--command",
        "env",
        f"REXSDK_DIR={sdk_dir}",
        f"REXSDK_INSTALL={sdk_install}",
        f"REXSDK_PREBUILT={1 if prebuilt else 0}",
        *command,
    ]


def read_lock() -> tuple[str, str]:
    try:
        data = json.loads(LOCK_FILE.read_text(encoding="utf-8"))
        return str(data["repository"]), str(data["commit"])
    except (OSError, KeyError, json.JSONDecodeError) as exc:
        raise InstallError(f"cannot read {LOCK_FILE}: {exc}") from exc


def git_head(path: Path) -> str | None:
    try:
        result = subprocess.run(
            ["git", "-C", str(path), "rev-parse", "HEAD"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            check=False,
        )
    except OSError:
        return None
    return result.stdout.strip() if result.returncode == 0 else None


def is_pinned(path: Path, commit: str) -> bool:
    return path.is_dir() and git_head(path) == commit


def ensure_sdk(requested: Path | None) -> tuple[Path, Path]:
    """Return (checkout, install prefix) for a clean pinned SDK."""
    repository, commit = read_lock()

    if requested is not None:
        sdk_dir = requested.expanduser().resolve()
        if not sdk_dir.is_dir():
            raise InstallError(f"SDK directory does not exist: {sdk_dir}")
        if not is_pinned(sdk_dir, commit):
            raise InstallError(
                f"{sdk_dir} is not at the pinned ReXGlue commit {commit}. "
                "Use a clean checkout or omit --sdk-dir to let the installer create one."
            )
        run(["git", "-C", str(sdk_dir), "submodule", "update", "--init", "--recursive"])
        return sdk_dir, sdk_dir / "out" / "install" / "linux-amd64"

    env_sdk = os.environ.get("REXSDK_DIR")
    if env_sdk:
        sdk_dir = Path(env_sdk).expanduser().resolve()
        if not is_pinned(sdk_dir, commit):
            raise InstallError(
                f"REXSDK_DIR={sdk_dir} is not at the pinned ReXGlue commit {commit}."
            )
        run(["git", "-C", str(sdk_dir), "submodule", "update", "--init", "--recursive"])
        return sdk_dir, Path(
            os.environ.get("REXSDK_INSTALL", str(sdk_dir / "out" / "install" / "linux-amd64"))
        ).expanduser().resolve()

    # Prefer an existing correct checkout next to the repository. If the
    # repository already has a different checkout, leave it untouched and use
    # an installer-managed checkout instead.
    local_sdk = ROOT / "rexglue-sdk"
    if is_pinned(local_sdk, commit):
        sdk_dir = local_sdk
    else:
        sdk_dir = ROOT / ".install" / "rexglue-sdk"
        if local_sdk.exists():
            log(
                f"NOTE: {local_sdk} is not the pinned ReXGlue checkout; "
                f"using {sdk_dir} instead."
            )

    sdk_install = sdk_dir / "out" / "install" / "linux-amd64"

    if not sdk_dir.exists():
        log(f"Cloning ReXGlue SDK into {sdk_dir} (this is the large one-time download)...")
        sdk_dir.parent.mkdir(parents=True, exist_ok=True)
        run(
            [
                "git",
                "clone",
                "--filter=blob:none",
                "--no-checkout",
                repository,
                str(sdk_dir),
            ]
        )
        run(["git", "-C", str(sdk_dir), "fetch", "--depth", "1", "origin", commit])
        run(["git", "-C", str(sdk_dir), "checkout", "--detach", commit])
        run(["git", "-C", str(sdk_dir), "submodule", "update", "--init", "--recursive"])
    elif not is_pinned(sdk_dir, commit):
        if not (sdk_dir / ".git").exists():
            raise InstallError(f"{sdk_dir} exists but is not a git checkout")
        log(f"Updating installer-managed ReXGlue SDK to {commit}...")
        run(["git", "-C", str(sdk_dir), "fetch", "--depth", "1", "origin", commit])
        run(["git", "-C", str(sdk_dir), "checkout", "--detach", "-f", commit])
        run(["git", "-C", str(sdk_dir), "submodule", "update", "--init", "--recursive"])
    else:
        log(f"Using pinned ReXGlue SDK at {sdk_dir}")
        # A clone can be interrupted after the superproject checkout but before
        # all submodules are populated. This is cheap when they are already
        # present and keeps a resumed install valid.
        run(["git", "-C", str(sdk_dir), "submodule", "update", "--init", "--recursive"])

    return sdk_dir, sdk_install


def prepare_sdk_bundle(source: Path) -> tuple[Path, Path]:
    """Unpack/validate a prebuilt SDK bundle and return (root, install)."""
    source = source.expanduser().resolve()
    if not source.exists():
        raise InstallError(f"SDK bundle not found: {source}")

    if source.is_dir():
        root = source
    else:
        root = ROOT / ".install" / "sdk-bundle"
        if root.exists():
            shutil.rmtree(root)
        root.mkdir(parents=True)
        try:
            with tarfile.open(source, "r:*") as archive:
                try:
                    archive.extractall(root, filter="data")
                except TypeError:  # Python without the extraction filter
                    archive.extractall(root)
        except (OSError, tarfile.TarError) as exc:
            raise InstallError(f"could not extract SDK bundle {source}: {exc}") from exc
        children = list(root.iterdir())
        if len(children) == 1 and children[0].is_dir():
            root = children[0]

    if not (root / "install").is_dir():
        children = [child for child in root.iterdir() if child.is_dir()]
        if len(children) == 1 and (children[0] / "install").is_dir():
            root = children[0]

    install = root / "install"
    codegen = install / "bin" / "rexglue"
    if not install.is_dir():
        raise InstallError(f"SDK bundle has no install/ directory: {root}")
    if not (codegen.is_file() and os.access(codegen, os.X_OK)):
        raise InstallError(f"SDK bundle has no executable install/bin/rexglue: {root}")

    # Verify that the bundled codegen can actually execute on this host. A
    # bundle built for glibc Linux will not run on NixOS without nix-ld, and
    # should be rejected before the installer reaches the build phase.
    bundle_env = os.environ.copy()
    lib_dirs = [str(install / "lib64"), str(install / "lib")]
    bundle_env["LD_LIBRARY_PATH"] = ":".join(lib_dirs + [bundle_env.get("LD_LIBRARY_PATH", "")])
    probe = subprocess.run(
        [str(codegen), "--version"],
        env=bundle_env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        check=False,
    )
    if probe.returncode != 0:
        detail = probe.stdout.strip().splitlines()[-1] if probe.stdout.strip() else "no output"
        raise InstallError(
            f"SDK bundle codegen cannot run on this host: {detail}. "
            "On NixOS, omit --sdk-bundle and let the installer build the SDK "
            "with the Nix dev shell."
        )

    metadata_path = root / "metadata.json"
    if metadata_path.is_file():
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise InstallError(f"invalid SDK bundle metadata: {exc}") from exc
        _, expected_commit = read_lock()
        bundle_commit = str(metadata.get("sdk_commit", ""))
        if bundle_commit and bundle_commit != expected_commit:
            raise InstallError(
                f"SDK bundle is built from {bundle_commit}, expected {expected_commit}"
            )

    return root, install


def parse_bool(value: str) -> bool:
    lowered = value.strip().lower()
    if lowered in {"1", "true", "yes", "on"}:
        return True
    if lowered in {"0", "false", "no", "off"}:
        return False
    raise argparse.ArgumentTypeError(f"expected true/false, got {value!r}")


def parse_language(lines: list[str]) -> tuple[int, int] | None:
    for line in lines:
        match = re.search(
            r"Detected language:.*user_language=(\d+),\s*user_country=(\d+)",
            line,
        )
        if match:
            return int(match.group(1)), int(match.group(2))
    return None


def build_installer_command(args: argparse.Namespace, out: Path) -> list[str]:
    command = [
        sys.executable,
        str(APPLY_CONFIG),
        "--toml",
        str(TOML),
        "--game-data-root",
        str(out),
        "--fps",
        str(args.fps),
        "--vsync",
        "true" if args.vsync else "false",
        "--present-effect",
        args.present_effect,
        "--resolution",
        args.resolution,
        "--res-scale",
        str(args.res_scale),
        "--fullscreen",
        "true" if args.fullscreen else "false",
        "--borderless",
        "true" if args.borderless else "false",
        "--dynamic-resolution",
        "false",
        "--user-language",
        str(args.user_language),
        "--user-country",
        str(args.user_country),
    ]
    return command


def install(args: argparse.Namespace) -> int:
    if args.sdk_bundle is None and args.sdk_dir is None and DEFAULT_SDK_BUNDLE.is_file():
        if is_nixos():
            log(
                "NOTE: ignoring the glibc SDK bundle on NixOS; "
                "building the pinned SDK with the Nix dev shell instead."
            )
        else:
            args.sdk_bundle = DEFAULT_SDK_BUNDLE
    if args.sdk_bundle is not None and args.sdk_dir is not None:
        raise InstallError("use either --sdk-dir or --sdk-bundle, not both")
    out = (args.out or DEFAULT_OUT).expanduser().resolve()
    iso = args.iso.expanduser().resolve() if args.iso else None

    if not args.skip_extract:
        if iso is None:
            raise InstallError("--iso is required unless --skip-extract is used")
        if not iso.is_file():
            raise InstallError(f"ISO not found: {iso}")
        log("==> [1/7] Extracting game data")
        extract_cmd = [sys.executable, "-u", str(EXTRACTOR), str(iso), "--out", str(out)]
        if args.force:
            extract_cmd.append("--force")
        lines = run(extract_cmd)
        language = parse_language(lines)
        if language:
            args.user_language, args.user_country = language
    else:
        log("==> [1/7] Skipping game-data extraction")

    if args.extract_only:
        log("==> Extraction complete (--extract-only)")
        return 0

    if not (out / "default.xex").is_file():
        raise InstallError(f"game/default.xex not found under {out}")

    prebuilt = args.sdk_bundle is not None
    if prebuilt:
        log("==> [2/7] Preparing the prebuilt ReXGlue SDK")
        sdk_dir, sdk_install = prepare_sdk_bundle(args.sdk_bundle)
    else:
        log("==> [2/7] Preparing the pinned ReXGlue SDK")
        sdk_dir, sdk_install = ensure_sdk(args.sdk_dir)

    build_env = os.environ.copy()
    build_env["REXSDK_DIR"] = str(sdk_dir)
    build_env["REXSDK_INSTALL"] = str(sdk_install)
    build_env["REXSDK_PREBUILT"] = "1" if prebuilt else "0"

    def build_cmd(command: list[str]) -> list[str]:
        return (
            command
            if has_build_tools()
            else nix_command(command, sdk_dir, sdk_install, prebuilt)
        )

    jobs = ["-j", str(args.jobs)] if args.jobs else []

    log("==> [3/7] Building and installing ReXGlue SDK")
    if prebuilt:
        log("==> Using prebuilt SDK; skipping clone/build")
    else:
        run(build_cmd([str(ROOT / "port" / "build_sdk.sh"), *jobs]), env=build_env)

    log("==> [4/7] Generating game code")
    run(
        build_cmd(
            [str(ROOT / "port" / "codegen.sh"), "--game-dir", str(out), *jobs]
        ),
        env=build_env,
    )

    log("==> [5/7] Building the Linux game")
    run(
        build_cmd(
            [
                str(ROOT / "port" / "build.sh"),
                "-c",
                "RelWithDebInfo",
                "--no-patch",
                *jobs,
            ]
        ),
        env=build_env,
    )

    log("==> [6/7] Writing the launcher configuration")
    run(build_installer_command(args, out))

    if args.launch:
        log("==> [7/7] Launching the game")
        launch = subprocess.Popen(
            [str(ROOT / "launch-diablo3.sh")],
            cwd=str(ROOT),
            env=os.environ.copy(),
            start_new_session=True,
        )
        log(f"Game launcher started (pid {launch.pid}).")
    else:
        log("==> [7/7] Installation complete; launch with ./launch-diablo3.sh")

    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--iso", type=Path, help="Xbox 360 Diablo III ISO/XISO")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help=f"game data directory (default: {DEFAULT_OUT})")
    parser.add_argument("--force", action="store_true", help="re-extract existing game files")
    parser.add_argument("--skip-extract", action="store_true", help="reuse an existing game-data directory")
    parser.add_argument("--extract-only", action="store_true", help="stop after extracting game data")
    parser.add_argument("--sdk-dir", type=Path, help="existing clean pinned ReXGlue SDK checkout")
    parser.add_argument(
        "--sdk-bundle",
        type=Path,
        help="prebuilt SDK bundle directory or .tar.gz created by port/package_sdk.sh",
    )
    parser.add_argument("--jobs", type=int, help="parallel build jobs")
    parser.add_argument("--resolution", default="1440p", help="guest video mode/window (default: 1440p)")
    parser.add_argument("--res-scale", type=int, choices=[1, 2, 3], default=1)
    parser.add_argument("--fullscreen", type=parse_bool, default=True)
    parser.add_argument("--borderless", type=parse_bool, default=False)
    parser.add_argument("--fps", type=int, default=60)
    parser.add_argument("--vsync", type=parse_bool, default=False)
    parser.add_argument("--present-effect", choices=["bilinear", "cas", "fsr"], default="bilinear")
    parser.add_argument("--user-language", type=int, default=1)
    parser.add_argument("--user-country", type=int, default=103)
    parser.add_argument("--launch", action="store_true", help="launch the game after installation")
    parser.add_argument("--version", action="version", version="Souls of the Reaper installer 2.0")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        return install(args)
    except InstallError as exc:
        log(f"ERROR: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
