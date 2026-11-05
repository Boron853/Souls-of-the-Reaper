"""Patches to the pinned ReXGlue SDK that both the Linux and Windows builds apply."""
import hashlib
import json
import os
import pathlib
import shutil
import stat
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
COMMON_DIR = ROOT / "patches/common"
LINUX_DIR = ROOT / "patches/linux"
COMMON_PATCHES = ("rexglue-registration.patch", "rexglue-texture-exponent.patch",
                  "rexglue-object-reference.patch", "rexglue-keyboard.patch",
                  "rexglue-wait-precision.patch", "rexglue-idle-toast.patch",
                  "rexglue-username.patch", "rexglue-systemlink-net.patch")
LINUX_PATCHES = ("rexglue-present-effects.patch",)
STAMP = ".sotr-sdk.json"
# Folders under patches/ that go into the SDK, per host.
PATCH_DIRS = {"linux": ("common", "systemlink", "linux"), "win": ("common", "systemlink", "windows")}


def lock():
    return json.loads((ROOT / "port/base/rexglue.lock.json").read_text())


def patch_hash(host):
    """Digest of everything this port adds to the SDK for `host` ("linux" or "win")."""
    digest = hashlib.sha256()
    for name in PATCH_DIRS[host]:
        base = ROOT / "patches" / name
        for path in sorted(p for p in base.rglob("*") if p.is_file()):
            digest.update(path.relative_to(ROOT).as_posix().encode() + b"\0")
            # Line endings differ between checkouts and must not change the digest.
            digest.update(path.read_bytes().replace(b"\r\n", b"\n") + b"\0")
    return digest.hexdigest()


def codegen_patch_hash():
    """Digest of the patch sections that change the SDK's code generator.

    Generated guest sources depend on these and on the SDK commit, but not on the
    runtime patches, so editing a runtime patch does not force a regeneration.
    """
    digest = hashlib.sha256()
    for path in sorted((ROOT / "patches").rglob("*.patch")):
        lines = path.read_bytes().replace(b"\r\n", b"\n").decode("utf-8").split("\n")
        # A file section starts at a "--- " line directly followed by "+++ ".
        starts = [i for i in range(len(lines) - 1)
                  if lines[i].startswith("--- ") and lines[i + 1].startswith("+++ ")]
        for start, end in zip(starts, starts[1:] + [len(lines)]):
            if "/codegen/" in lines[start + 1]:
                digest.update(path.relative_to(ROOT).as_posix().encode() + b"\0")
                digest.update("\n".join(lines[start:end]).encode() + b"\0")
    return digest.hexdigest()


def write_stamp(prefix, host):
    """Record which SDK revision and patch set an install was built from."""
    (prefix / STAMP).write_text(json.dumps({"commit": lock()["commit"], "patches": patch_hash(host)}) + "\n")


def clear_stamp(prefix):
    """Forget which SDK an install was built from, before replacing its files."""
    (prefix / STAMP).unlink(missing_ok=True)


def stamp_state(prefix, host):
    """"current" when the install matches the pinned commit and patches, else "stale"
    (an install from before stamps existed has no stamp and counts as stale)."""
    try:
        stamp = json.loads((prefix / STAMP).read_text())
    except (OSError, ValueError):
        return "stale"
    return "current" if stamp == {"commit": lock()["commit"], "patches": patch_hash(host)} else "stale"


def remove_tree(path):
    """shutil.rmtree that also removes read-only files (git marks its objects read-only on Windows)."""
    def retry(function, name, *_):
        os.chmod(name, stat.S_IWRITE)
        function(name)
    if sys.version_info >= (3, 12):
        shutil.rmtree(path, onexc=retry)
    else:
        shutil.rmtree(path, onerror=retry)


def checkout_pinned(source, repository, commit, run, config=(), clean=False):
    """Make `source` a checkout of `commit`, whatever state an earlier run left it in.

    - No checkout yet: clone into `<source>.partial` and rename it when complete, so
      a clone that is killed part way never leaves a broken checkout behind.
    - Checkout at another commit (the pin moved): fetch the commit and switch to it.
    - `clean`: discard local changes and untracked files first (ignored build
      folders such as `out/` are kept), so patches always meet pristine sources.

    `run` is the caller's command runner; `config` holds git settings (e.g.
    core.autocrlf=false) applied to the clone before checkout. Submodules do not
    read the clone's config, so they get the same settings on the command line.
    """
    options = [a for c in config for a in ("-c", c)]
    if not (source / ".git").exists():
        if source.exists() and any(source.iterdir()):
            raise ValueError(f"{source} exists but is not a git checkout; move it aside and run again.")
        partial = source.with_name(source.name + ".partial")
        if partial.exists():
            remove_tree(partial)
        run("git", *options, "clone", "--no-checkout", repository, partial)
        for c in config:
            run("git", "-C", partial, "config", *c.split("=", 1))
        if source.exists():
            source.rmdir()
        partial.rename(source)
    else:
        for c in config:
            run("git", "-C", source, "config", *c.split("=", 1))
    def present():
        return subprocess.run(["git", "-C", str(source), "cat-file", "-e", f"{commit}^{{commit}}"],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0
    if not present():
        try:
            run("git", *options, "-C", source, "fetch", "--no-tags", repository, commit)
        except subprocess.CalledProcessError:
            # Servers that refuse fetching a bare commit id still serve the branches that contain it.
            run("git", *options, "-C", source, "fetch", "--no-tags", repository,
                "+refs/heads/*:refs/remotes/origin/*")
    if clean:
        run("git", *options, "-C", source, "checkout", "--force", "--detach", commit)
        run("git", "-C", source, "clean", "-fd", "--quiet")
    else:
        run("git", *options, "-C", source, "checkout", "--detach", commit)
    actual = subprocess.check_output(["git", "-C", str(source), "rev-parse", "HEAD"], text=True).strip()
    if actual != commit:
        raise ValueError(f"{source} is at {actual}; expected {commit}")
    run("git", *options, "-C", source, "submodule", "update", "--init", "--recursive",
        *(["--force"] if clean else []))


def checkout_pinned_sdk(sdk, run, config=()):
    """Check out the pinned SDK commit with no local changes, ready for the patches below.

    Every SDK build starts from pristine sources. Patches left by an earlier
    (failed, cancelled or outdated) build are discarded rather than detected:
    later patches change context that earlier ones need to be recognised.
    """
    pinned = lock()
    checkout_pinned(sdk, pinned["repository"], pinned["commit"], run, config, clean=True)
    return pinned


def apply_patch(sdk, patch):
    """Apply a patch to the pristine SDK checkout; git applies all of it or nothing."""
    subprocess.run(["git", "-C", str(sdk), "apply", str(patch)], check=True)


def install_sources(sdk):
    """Copy whole source files this port adds to the SDK (patches/systemlink mirrors the SDK tree)."""
    source_root = ROOT / "patches/systemlink"
    for source in sorted(p for p in source_root.rglob("*") if p.is_file()):
        target = sdk / source.relative_to(source_root)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)


def apply_common_patches(sdk):
    # The new files go in first: the patches below refer to them.
    install_sources(sdk)
    for name in COMMON_PATCHES:
        apply_patch(sdk, COMMON_DIR / name)


def apply_linux_patches(sdk):
    for name in LINUX_PATCHES:
        apply_patch(sdk, LINUX_DIR / name)
