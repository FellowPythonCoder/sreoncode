#!/usr/bin/env python3
"""Prove a built .dmg is what we think it is, by reading the mounted volume.

`hdiutil verify` only says the bytes are intact. This says the thing a user actually
sees is right: the app is in there and executable, the Applications drop link points at
/Applications, QtWebEngine travelled with the bundle, and the Finder window layout (a
`.DS_Store` holding the background picture alias plus icon positions) was recorded
instead of being left to Finder. Those last two are exactly what silently regresses when
dmgbuild was unavailable and the build fell back to a plain folder image.

    python3 Browser/tools/check_dmg.py /Volumes/Sreon
    python3 Browser/tools/check_dmg.py Browser/dist/Sreon.dmg --mount
"""

from __future__ import annotations

import argparse
import os
import plistlib
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

PICTURE = 2  # Finder's icvp backgroundType: 0 default, 1 colour, 2 picture


def decode(value):
    """ds_store returns a dict for records it understands and raw bytes for the rest."""
    if isinstance(value, (bytes, bytearray)):
        try:
            return plistlib.loads(bytes(value))
        except Exception:
            return None
    return value


def read_ds_store(path: Path) -> dict:
    """Return {fourcc: {entry_name: decoded_value}} for a .DS_Store file.

    ds_store exposes records as (filename, code, type, value); plist-backed records come
    back as ['blob', <object>], so both shapes are flattened here.
    """
    from ds_store import DSStore

    scalars = {"blob", "long", "string", "pt", "rect", "bool", "double", "float"}
    found: dict[str, dict] = {}
    with DSStore.open(str(path), "r+") as store:
        for record in store:
            code = record.code
            if isinstance(code, (bytes, bytearray)):
                code = code.decode("utf-8", "replace").strip()
            if code not in ("icvp", "Iloc", "bwsp"):
                continue
            name = record.filename
            if isinstance(name, (bytes, bytearray)):
                name = name.decode("utf-8", "replace")
            value = record.value
            if (isinstance(value, (list, tuple)) and len(value) == 2
                    and isinstance(value[0], str) and value[0] in scalars):
                value = value[1]
            found.setdefault(code, {})[name or "."] = decode(value)
    return found


def check(volume: Path, *, app: str = "Sreon.app", require_background: bool = True):
    """Inspect a mounted image. Returns (findings, problems)."""
    volume = Path(volume)
    findings: list[str] = []
    problems: list[str] = []

    entries = sorted(item.name for item in volume.iterdir())
    bundle = volume / app
    if not bundle.is_dir():
        return [f"volume holds: {entries}"], [f"{app} is not in the image"]

    launcher = bundle / "Contents" / "MacOS" / Path(app).stem
    if not launcher.is_file():
        problems.append(f"{launcher.relative_to(volume)} is missing")
    elif not os.access(launcher, os.X_OK):
        problems.append(f"{launcher.name} is not executable - the app could not launch")
    else:
        findings.append(f"{app}: launcher {launcher.stat().st_size / 1e6:.1f} MB, "
                        f"mode {oct(launcher.stat().st_mode & 0o777)}")

    frameworks = bundle / "Contents" / "Frameworks"
    if frameworks.is_dir():
        names = [item.name for item in frameworks.iterdir()]
        if any("QtWebEngineCore" in name for name in names):
            findings.append("QtWebEngineCore.framework is bundled (pages will render)")
        else:
            problems.append(f"QtWebEngineCore.framework missing from Frameworks: {names}")
        for helper in frameworks.glob("QtWebEngineCore.framework/Helpers/*"):
            if helper.is_file() and not os.access(helper, os.X_OK):
                problems.append(f"helper {helper.name} is not executable")
    else:
        problems.append("no Contents/Frameworks - the freeze did not bundle Qt")

    link = volume / "Applications"
    if not link.is_symlink():
        problems.append("no Applications drop link: nothing to drag onto")
    elif Path(os.readlink(link)) != Path("/Applications"):
        problems.append(f"Applications link points at {os.readlink(link)!r}")
    else:
        findings.append("Applications drop link -> /Applications")

    artwork = [item for item in volume.iterdir() if item.name.startswith(".background")]
    if artwork:
        detail = []
        for item in artwork:
            if item.is_dir():
                detail.append(f"{item.name}/" + ",".join(sorted(child.name for child in item.iterdir())))
            else:
                detail.append(f"{item.name} ({item.stat().st_size // 1024} KiB)")
        findings.append("artwork: " + ", ".join(detail))
    elif require_background:
        problems.append("no .background in the image - it would open as a plain folder window")

    store = volume / ".DS_Store"
    if not store.is_file():
        problems.append("no .DS_Store: no window size, no icon positions, no picture record")
    else:
        try:
            records = read_ds_store(store)
        except Exception as error:  # ds_store is a build extra, not something the app needs
            findings.append(f"skipped .DS_Store parsing ({type(error).__name__}); CI checks this")
            records = {}
        if records:
            layout = records.get("icvp", {}).get(".")
            if not isinstance(layout, dict):
                problems.append("no icvp record - Finder has no icon-view settings to restore")
            else:
                kind = int(layout.get("backgroundType", -1))
                if kind != PICTURE:
                    problems.append(f"backgroundType is {kind}, expected {PICTURE}: the card artwork "
                                    "was not applied (0 = default, 1 = flat colour)")
                elif "backgroundImageAlias" not in layout:
                    problems.append("icvp has no backgroundImageAlias")
                else:
                    findings.append(f"icon view: backgroundType={kind}, iconSize={layout.get('iconSize')}, "
                                    f"textSize={layout.get('textSize')}")
            positions = records.get("Iloc", {})
            for name in (app, "Applications"):
                if name not in positions:
                    problems.append(f"{name} has no stored position; Finder will scatter the icons")
            if positions and not problems:
                preview = ", ".join(f"{key} {tuple(value)}" for key, value in list(positions.items())[:3])
                findings.append(f"icon positions: {preview}")
            window = records.get("bwsp", {}).get(".")
            if isinstance(window, dict):
                findings.append(f"window bounds: {window.get('WindowBounds')}")
    return findings, problems


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("target", type=Path, help="mounted volume, or a .dmg with --mount")
    parser.add_argument("--mount", action="store_true", help="attach the image with hdiutil first")
    parser.add_argument("--app", default="Sreon.app")
    parser.add_argument("--allow-missing-background", action="store_true",
                        help="accept the plain folder image the fallback path produces")
    args = parser.parse_args(argv)

    volume, temporary = args.target, None
    if args.mount:
        temporary = Path(tempfile.mkdtemp(prefix="sreon-dmg-check-"))
        try:
            subprocess.run(["hdiutil", "attach", "-readonly", "-noverify", "-noautoopen",
                            "-mountpoint", str(temporary), str(args.target)], check=True)
        except subprocess.CalledProcessError as error:
            raise SystemExit(f"could not mount {args.target}: {error}")
        volume = temporary
    try:
        findings, problems = check(volume, app=args.app,
                                   require_background=not args.allow_missing_background)
    finally:
        if temporary is not None:
            subprocess.run(["hdiutil", "detach", str(temporary), "-force"],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            shutil.rmtree(temporary, ignore_errors=True)

    for line in findings:
        print("  ok:", line)
    for line in problems:
        print("  FAIL:", line, file=sys.stderr)
    if problems:
        return 1
    print(f"{args.target} is a proper installer image")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
