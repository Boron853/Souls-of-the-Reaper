#!/usr/bin/env python3
"""Generate verified guest sources (base disc or title update) for any supported host platform.

Generated sources are reused only while everything that shapes them is unchanged:
the executable, the codegen manifest and function hints (config/*.toml), the
pinned SDK commit and the SDK patches that touch the code generator. The stamp
recording those is written last, so an interrupted run is never reused.
"""
import argparse
import hashlib
import json
import pathlib
import subprocess

import sdk_patches
from apply_generated_patches import patch_generated
from title_updates import DISC_SHA256, USA_UPDATE_SHA256, update_layout

ROOT = pathlib.Path(__file__).resolve().parents[1]
STAMP = "codegen-inputs.json"
# Variant -> (manifest folder, game folder placeholder in the manifest).
MANIFESTS = {"base": ("port/base", "../../game"),
             "update": ("port/title_updates/update", "../../../game-update")}


def expected_sha256(variant):
    return USA_UPDATE_SHA256 if variant == "update" else DISC_SHA256


def codegen_inputs(variant):
    """What the generated sources of `variant` ("base" or "update") are derived from."""
    manifest_dir = ROOT / MANIFESTS[variant][0]
    digest = hashlib.sha256()
    for path in [manifest_dir / "diablo3_manifest.toml", *sorted((manifest_dir / "config").glob("*.toml"))]:
        digest.update(path.relative_to(ROOT).as_posix().encode() + b"\0")
        digest.update(path.read_bytes().replace(b"\r\n", b"\n") + b"\0")
    return {"executable": expected_sha256(variant), "sdk_commit": sdk_patches.lock()["commit"],
            "codegen_patches": sdk_patches.codegen_patch_hash(), "manifest": digest.hexdigest()}


def stamp_current(variant):
    """True when port/generated/<variant> was generated from the current inputs."""
    try:
        stamp = json.loads((ROOT / "port/generated" / variant / STAMP).read_text())
    except (OSError, ValueError):
        return False
    return stamp == codegen_inputs(variant)


def generate(variant, game_dir, rexglue, skip_codegen=False):
    """Run codegen for `variant` unless `skip_codegen`, then apply the guest fixes."""
    game_dir = pathlib.Path(game_dir).resolve()
    xex = update_layout(game_dir)[2] if variant == "update" else game_dir / "Default.xex"
    if not xex.is_file() or hashlib.sha256(xex.read_bytes()).hexdigest() != expected_sha256(variant):
        raise ValueError("Default.xex must match the verified USA update executable" if variant == "update"
                         else "Default.xex must match the verified base disc executable")
    generated = ROOT / "port/generated" / variant
    stamp = generated / STAMP
    if skip_codegen:
        if not stamp_current(variant):
            raise ValueError(f"{variant} generated sources missing or stale; regenerate without --skip-codegen")
    else:
        # An interrupted regeneration must not leave a valid reuse stamp. (Codegen itself
        # deletes shards it no longer writes and leaves unchanged ones untouched.)
        stamp.unlink(missing_ok=True)
        folder, placeholder = MANIFESTS[variant]
        manifest_dir = ROOT / folder
        manifest = (manifest_dir / "diablo3_manifest.toml").read_text(encoding="utf-8")
        # JSON strings also encode paths safely as TOML basic strings.
        manifest = manifest.replace(json.dumps(placeholder + "/Default.xex"),
                                    json.dumps(xex.as_posix(), ensure_ascii=False))
        manifest = manifest.replace(json.dumps(placeholder), json.dumps(game_dir.as_posix(), ensure_ascii=False))
        local = manifest_dir / "local_manifest.toml"
        local.write_text(manifest, encoding="utf-8")
        print(f"$ {rexglue} codegen {local}", flush=True)
        subprocess.run([str(rexglue), "codegen", str(local)], cwd=ROOT, check=True)
        generated.mkdir(parents=True, exist_ok=True)
    patch_generated(generated, "usa" if variant == "update" else None)
    stamp.write_text(json.dumps(codegen_inputs(variant), indent=2) + "\n")
    return generated


def generate_update(game_dir, rexglue, skip_codegen=False):
    return generate("update", game_dir, rexglue, skip_codegen)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--game-dir", type=pathlib.Path, required=True)
    parser.add_argument("--rexglue", type=pathlib.Path, required=True)
    parser.add_argument("--variant", choices=sorted(MANIFESTS), default="update")
    parser.add_argument("--skip-codegen", action="store_true")
    args = parser.parse_args()
    try:
        generate(args.variant, args.game_dir, args.rexglue, args.skip_codegen)
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        parser.exit(1, f"{args.variant} codegen failed: {error}\n")


if __name__ == "__main__":
    main()
