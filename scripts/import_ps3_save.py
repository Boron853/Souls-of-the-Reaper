#!/usr/bin/env python3
"""Inspect PS3/RPCS3 Diablo III RoS saves or import into a NEW update state directory.

Experimental: preserves payload bytes; desktop load/save validation is pending.
The source is read-only. No third-party Python packages are required.
"""
import argparse
import hashlib
import json
import pathlib
import re
import shutil
import sys

MAX_FILE_SIZE = 16 * 1024 * 1024
TITLE_ID = "394F07D4"
DEFAULT_XUID = "B13EBABEBABEBABE"


class SaveError(ValueError):
    pass


def decode(data):
    # Diablo's rolling XOR stream, also documented by GoobyCorp/D3Edit.
    state = 0x305F92D82EC9A01B
    result = bytearray()
    for encrypted in data:
        plain = encrypted ^ (state & 255)
        result.append(plain)
        state = (((state ^ plain) << 56) | (state >> 8)) & 0xFFFFFFFFFFFFFFFF
    return bytes(result)


def fields(data):
    """Read protobuf wire fields without reserializing or discarding unknowns."""
    offset = 0

    def varint():
        nonlocal offset
        value = 0
        for shift in range(0, 70, 7):
            if offset >= len(data):
                raise SaveError("Truncated protobuf varint")
            byte = data[offset]
            offset += 1
            if shift == 63 and byte > 1:
                raise SaveError("Overflowing protobuf varint")
            value |= (byte & 127) << shift
            if byte < 128:
                return value
        raise SaveError("Invalid protobuf varint")

    result = []
    while offset < len(data):
        tag = varint()
        number, wire = tag >> 3, tag & 7
        if not 1 <= number < (1 << 29):
            raise SaveError("Invalid protobuf field number")
        if wire == 0:
            value = varint()
        elif wire in (1, 2, 5):
            size = varint() if wire == 2 else (8 if wire == 1 else 4)
            if size > len(data) - offset:
                raise SaveError("Truncated protobuf field")
            value = data[offset:offset + size]
            offset += size
        else:
            raise SaveError(f"Unsupported protobuf wire type {wire}")
        result.append((number, wire, value))
    if not result:
        raise SaveError("Empty protobuf message")
    return result


def one(message, number, wire):
    values = [value for field, kind, value in message if field == number and kind == wire]
    if len(values) != 1 or any(field == number and kind != wire for field, kind, _ in message):
        raise SaveError(f"Expected one field {number} with wire type {wire}")
    return values[0]


def entity_id(data):
    message = fields(data)
    return one(message, 1, 0), one(message, 2, 0)


def read_payload(path):
    if path.is_symlink() or not path.is_file():
        raise SaveError(f"Expected a regular, non-symlink file: {path}")
    if not 0 < path.stat().st_size <= MAX_FILE_SIZE:
        raise SaveError(f"Invalid save file size: {path.name}")
    raw = path.read_bytes()
    if len(raw) > MAX_FILE_SIZE:
        raise SaveError(f"Save file exceeds size limit: {path.name}")
    return raw, fields(decode(raw))


def hero_info(message):
    version = one(message, 1, 0)
    digest = fields(one(message, 2, 2))
    digest_version = one(digest, 1, 0)
    high, low = entity_id(one(digest, 2, 2))
    if not low:
        raise SaveError("Hero has a zero filename identifier")
    # Required saved attributes must also be structurally readable.
    fields(one(message, 3, 2))
    return {"version": version, "digest_version": digest_version,
            "id_high": f"{high:016x}", "id_low": f"{low:016x}"}


def inspect_source(source, reference=None):
    source = source.resolve(strict=True)
    if not source.is_dir():
        raise SaveError("Source must be an extracted RPCS3 save directory")
    payloads = {}
    account_raw, account = read_payload(source / "ACCOUNT.DAT")
    profile_raw, profile = read_payload(source / "PROFILE.DAT")
    fields(one(account, 2, 2))
    for _, wire, value in profile:
        if wire == 2:
            fields(value)
    payloads["account.dat"] = account_raw
    payloads["profile.dat"] = profile_raw
    _, index = read_payload(source / "HEROES.IDX")
    indexed_ids = []
    for number, wire, value in index:
        if number == 1 and wire == 2:
            # PS3 index entries carry an EntityId in their first field.
            indexed_ids.append(entity_id(one(fields(value), 1, 2)))
        else:
            raise SaveError("Unrecognized PS3 hero index layout")
    if len(set(indexed_ids)) != len(indexed_ids):
        raise SaveError("Duplicate hero IDs in PS3 index")
    heroes = []
    actual_ids = []
    for path in sorted(source.iterdir()):
        if path.suffix.upper() != ".HRO":
            continue
        raw, message = read_payload(path)
        hero = hero_info(message)
        low = int(hero["id_low"], 16)
        if not re.fullmatch(r"[0-9a-fA-F]{8}", path.stem) or int(path.stem, 16) != low & 0xFFFFFFFF:
            raise SaveError(f"PS3 hero filename does not match embedded ID: {path.name}")
        target = f"heroes/{hero['id_low']}.dat"
        if target in payloads:
            raise SaveError("Duplicate destination hero filename")
        payloads[target] = raw
        actual_ids.append((int(hero["id_high"], 16), low))
        heroes.append({"source": path.name, "destination": target, **hero})
    if not heroes or set(actual_ids) != set(indexed_ids):
        raise SaveError("Hero index does not match the available .HRO files")
    account_version = one(account, 1, 0)
    reference_versions = None
    if reference:
        reference = reference.resolve(strict=True)
        _, reference_account = read_payload(reference / "account.dat")
        reference_heroes = sorted((reference / "heroes").glob("*.dat"))
        if not reference_heroes:
            raise SaveError("Reference Xbox save needs at least one hero")
        reference_versions = {"account": one(reference_account, 1, 0), "heroes": []}
        for path in reference_heroes:
            _, message = read_payload(path)
            hero = hero_info(message)
            if path.name != f"{hero['id_low']}.dat":
                raise SaveError("Reference Xbox filename does not match embedded ID")
            reference_versions["heroes"].append([hero["version"], hero["digest_version"]])
    compatible = account_version == 108 and all(
        hero["version"] == 905 and hero["digest_version"] == 905 for hero in heroes)
    if reference_versions:
        compatible = compatible and account_version == reference_versions["account"] and all(
            [hero["version"], hero["digest_version"]] in reference_versions["heroes"] for hero in heroes)
    report = {"format": "souls-ps3-import-v1", "source": str(source),
              "account_version": account_version, "heroes": heroes,
              "known_update_versions_match": compatible, "reference_versions": reference_versions,
              "runtime_validated": False,
              "omitted": ["PREFS.DAT", "HEROES.IDX", "PARAM.SFO", "PARAM.PFD", "ICON0.PNG"],
              "files": {name: {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
                        for name, raw in payloads.items()}}
    return source, report, payloads


def import_save(source, output, xuid, reference=None):
    source, report, payloads = inspect_source(source, reference)
    if not report["known_update_versions_match"]:
        hero_versions = sorted({(hero["version"], hero["digest_version"]) for hero in report["heroes"]})
        raise SaveError(
            f"Save versions are outside the inspected update format (account {report['account_version']}, "
            f"hero/digest {hero_versions}; expected account 108, hero/digest 905). "
            "Saves from newer or different editions, such as Ultimate Evil Edition, are not imported; "
            "inspection only")
    if not re.fullmatch(r"[0-9a-fA-F]{16}", xuid):
        raise SaveError("XUID must contain exactly 16 hexadecimal digits")
    output = output.resolve()
    if output == source or output in source.parents or source in output.parents:
        raise SaveError("Output must be separate from the PS3 source directory")
    if reference:
        reference = reference.resolve()
        if output == reference or output in reference.parents or reference in output.parents:
            raise SaveError("Output must be separate from the Xbox reference save")
    # Exclusive creation: an existing state directory is never merged or replaced.
    output.mkdir(parents=True, exist_ok=False)
    try:
        package = output / xuid.upper() / TITLE_ID / "00000001" / "d3save"
        (package / "heroes").mkdir(parents=True)
        for name, raw in payloads.items():
            with (package / name).open("xb") as file:
                file.write(raw)
        report["destination_package"] = str(package)
        report["xuid"] = xuid.upper()
        with (output / "import-report.json").open("x", encoding="utf-8") as file:
            json.dump(report, file, indent=2)
            file.write("\n")
    except BaseException:
        # Only remove the new output owned by this invocation, never source/reference.
        shutil.rmtree(output)
        raise
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=pathlib.Path, help="Read-only PS3/RPCS3 save directory")
    parser.add_argument("--output-state", type=pathlib.Path,
                        help="Import into a NEW state directory; omitted means inspection only")
    parser.add_argument("--xuid", default=DEFAULT_XUID, help="Destination emulated Xbox profile ID")
    parser.add_argument("--reference-save", type=pathlib.Path,
                        help="Read-only Xbox update d3save directory for version/filename comparison")
    args = parser.parse_args()
    try:
        if args.output_state:
            report = import_save(args.source, args.output_state, args.xuid, args.reference_save)
        else:
            _, report, _ = inspect_source(args.source, args.reference_save)
        print(json.dumps(report, indent=2))
        return 0
    except (OSError, SaveError) as error:
        print(f"PS3 save import: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
