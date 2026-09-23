#!/usr/bin/env python3
"""Build the deliverable: one zip holding exactly the double-click installers.

    python3 Browser/tools/make_double_click_zip.py --stage stage --out bundle/Sreon-0.5.1-double-click.zip

``stage`` is a flat folder with the files the user should be able to double-click - Sreon.dmg,
SreonSetup.exe, Sreon.AppImage. Nothing else belongs in the zip: no README, no folder, no
archive of an archive. The zip carries the unix +x bit so the AppImage is runnable straight out
of it (extract, double-click, done) and no "chmod +x" step is needed.

The file is written by streaming each entry, never by reading a 250 MB installer into memory,
and the result is re-opened and checked before we call it done - a zip that unpacks to
something other than the three installers is worse than no zip at all.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import time
import zipfile
from pathlib import Path

# The three files the request asked for, and the only ones allowed in the archive.
EXPECTED = ("Sreon.dmg", "SreonSetup.exe", "Sreon.AppImage")


def pack(stage: Path, target: Path, *, allow_missing: bool = False) -> dict:
    """Zip every file in *stage* into *target*; return a summary of what went in."""
    present = sorted(path.name for path in stage.iterdir() if path.is_file())
    if not present:
        raise SystemExit(f"nothing to pack: {stage} is empty")
    missing = [name for name in EXPECTED if name not in present]
    if missing and not allow_missing:
        raise SystemExit(
            "the deliverable must hold the three double-click files; missing "
            + ", ".join(missing)
            + f" (stage holds: {', '.join(present) or 'nothing'})"
        )
    if missing:
        print("::warning::zip is missing " + ", ".join(missing), flush=True)

    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        target.unlink()
    sizes = {}
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for name in present:
            source = stage / name
            info = zipfile.ZipInfo(name, date_time=time.localtime(source.stat().st_mtime)[:6])
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3                      # unix, so external_attr means something
            info.external_attr = (0o755 & 0xFFFF) << 16
            with archive.open(info, "w") as dst, source.open("rb") as src:
                shutil.copyfileobj(src, dst, 1024 * 1024)
            sizes[name] = source.stat().st_size

    # Read it back: corrupt member, wrong mode or a stray entry is a build failure here,
    # not something for the user to discover after a 250 MB download.
    with zipfile.ZipFile(target) as archive:
        bad = archive.testzip()
        if bad is not None:
            raise SystemExit(f"the zip we just wrote has a corrupt member: {bad}")
        entries = {entry.filename: entry for entry in archive.infolist()}
        if set(entries) != set(present):
            raise SystemExit(f"zip holds {sorted(entries)} expected {sorted(present)}")
        for name, entry in entries.items():
            if entry.external_attr >> 16 != 0o755:
                raise SystemExit(f"{name} lost its +x bit: {oct(entry.external_attr >> 16)}")
            if entry.file_size != sizes[name]:
                raise SystemExit(f"{name} is {entry.file_size} bytes in the zip, {sizes[name]} on disk")

    return {
        "zip": str(target),
        "bytes": target.stat().st_size,
        "entries": {name: sizes[name] for name in present},
        "missing": missing,
    }


def checksums(stage: Path, out: Path) -> None:
    """SHA256 of each staged file, in the format `sha256sum -c` accepts."""
    lines = []
    for path in sorted(p for p in stage.iterdir() if p.is_file()):
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
        lines.append(f"{digest.hexdigest()}  {path.name}\n")
    out.write_text("".join(lines), encoding="utf-8")
    print("".join(lines).strip(), flush=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--stage", type=Path, required=True,
                        help="folder holding the installers to include")
    parser.add_argument("--out", type=Path, required=True, help="path of the zip to write")
    parser.add_argument("--sums", type=Path, help="also write SHA256SUMS.txt here")
    parser.add_argument("--allow-missing", action="store_true",
                        help="pack what exists instead of failing when a platform file is absent")
    args = parser.parse_args(argv)

    summary = pack(args.stage.expanduser().resolve(), args.out.expanduser().resolve(),
                   allow_missing=args.allow_missing)
    if args.sums:
        checksums(args.stage, args.sums.expanduser().resolve())
    print(json.dumps(summary, indent=2), flush=True)
    print(f"::notice::{summary['zip'].split('/')[-1]} holds "
          + ", ".join(f"{name} ({size / 1e6:.0f} MB)" for name, size in summary["entries"].items()),
          flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
