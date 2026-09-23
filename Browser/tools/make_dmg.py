"""Build Sreon's styled macOS disk image.

Why not `hdiutil create -srcfolder`?  That produces a working DMG whose window
opens as a plain folder list -- no background art, no Applications drop target,
icons scattered by "clean up".  Finder's layout lives in a `.DS_Store` inside the
image, and writing one needs Apple's Desktop Services Store format, which
`dmgbuild` does natively.  So:

  1. dmgbuild (+ our PNG artwork, + a HiDPI @2x pair merged into a TIFF)  ->  styled DMG
  2. plain `hdiutil create`                                                 ->  still installable

Step 2 keeps the release shippable if the dmgbuild wheel is unavailable, and both
paths are verified with `hdiutil verify` plus a real mount before we call it done.

    python3 Browser/tools/make_dmg.py dist/Sreon.app dist/Sreon.dmg
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
ROOT = TOOLS.parent
sys.path.insert(0, str(TOOLS))

from make_dmg_background import ICON_SIZE, TEXT_SIZE, WINDOW, layout  # noqa: E402

VERSION_DEFAULT = "auto"   # make_dmg_background reads Browser/VERSION
VOLUME_NAME = "Sreon"


def log(*parts):
    print("make_dmg:", *parts, flush=True)


def sh(command, *, check=False, quiet=True):
    """Run a command, returning (code, output). Never raises unless check=True."""
    log("+", " ".join(str(part) for part in command))
    process = subprocess.run([str(part) for part in command], stdout=subprocess.PIPE,
                             stderr=subprocess.STDOUT, text=True)
    if not quiet:
        print(process.stdout, flush=True)
    if check and process.returncode:
        raise SystemExit(f"command failed ({process.returncode}): {process.stdout[-1500:]}")
    return process.returncode, process.stdout or ""


def prepare_app(app: Path) -> None:
    """Make sure the bundle is executable and ad-hoc signed.

    An ad-hoc signature ( `-s -` ) does not silence Gatekeeper -- only a Developer ID
    plus notarisation does that -- but the dynamic linker *requires* a valid signature
    on Apple silicon, so a copy whose signature breaks (e.g. after we chmod a nested
    helper) would be killed with "Killed: 9" instead of launching.
    """
    binary = app / "Contents" / "MacOS" / app.stem
    if binary.is_file():
        os.chmod(binary, 0o755)
    helper = app / "Contents" / "Frameworks" / "QtWebEngineCore.framework" / "Helpers"
    if helper.is_dir():
        for item in helper.iterdir():
            if item.is_file() or item.is_symlink():
                try:
                    os.chmod(item, 0o755)
                except OSError:
                    pass
    identity = (os.environ.get("SREON_CODESIGN_IDENTITY") or "-").strip()
    entitlements = ROOT / "installer" / "mac" / "entitlements.plist"
    command = ["codesign", "--force", "--verbose=1", "--sign", identity]
    if identity != "-":
        # Hardened runtime only makes sense next to a Developer ID + notarisation;
        # forcing it on an ad-hoc signature just gets the app killed.
        command += ["--options", "runtime", "--timestamp", "--deep"]
        if entitlements.is_file():
            command += ["--entitlements", str(entitlements)]
    command.append(str(app))
    code, output = sh(command, quiet=identity == "-")
    if code and identity != "-":
        raise SystemExit(f"codesign failed for identity {identity!r}: {output[-1200:]}")
    if code:
        log("ad-hoc codesign skipped (", output.strip().splitlines()[-1] if output.strip() else "?", ")")


def artwork() -> tuple[Path, Path]:
    """Return (background@1x, background@2x), rendering them if they are missing."""
    one = ROOT / "assets" / "dmg-background.png"
    two = ROOT / "assets" / "dmg-background@2x.png"
    if not one.is_file() or not two.is_file():
        code, _ = sh([sys.executable, str(TOOLS / "make_dmg_background.py")])
        if code:
            log("could not render artwork; falling back to a plain image")
    return one, two


def _setfile_exists() -> bool:
    """dmgbuild hides the .app extension and blesses the volume icon with SetFile.

    That tool ships with Xcode, not always with the command-line tools, and dmgbuild lets
    a missing binary escape as an exception - which would throw away the styled image and
    silently downgrade everyone to the plain folder. So: only ask for those two touches
    when SetFile is really there, and retry without them if anything still goes wrong.
    """
    return Path("/usr/bin/SetFile").is_file()


def build_with_dmgbuild(app: Path, out: Path) -> bool:
    try:
        from dmgbuild.core import build_dmg
    except ImportError:
        log("dmgbuild is not installed (pip install dmgbuild) -- using the plain image")
        return False
    one, _ = artwork()
    geometry = layout()
    settings = {
        "files": [(str(app), app.name)],
        "symlinks": {"Applications": "/Applications"},
        "format": "UDZO",
        "filesystem": "HFS+",
        "icon_size": float(ICON_SIZE),
        "text_size": float(TEXT_SIZE),
        "label_pos": "bottom",
        "default_view": "icon-view",
        "icon_locations": {name: tuple(position) for name, position in geometry["icon_locations"].items()},
        "window_rect": ((100, 100), WINDOW),
        "background": str(one),          # dmgbuild finds .dmg-background@2x.png next to it
        "show_status_bar": False,
        "show_tab_view": False,
        "show_toolbar": False,
        "show_pathbar": False,
        "show_sidebar": False,
    }
    cosmetics = {"hide_extensions": [app.name], "icon": str(ROOT / "assets" / "icon.icns")} \
        if _setfile_exists() and (ROOT / "assets" / "icon.icns").is_file() else {}
    for attempt, extra in enumerate((cosmetics, {})):
        options = {**settings, **extra}
        if out.exists():
            out.unlink()
        log(f"dmgbuild -> {out} (attempt {attempt + 1}, "
            f"{'with' if extra else 'without'} SetFile-only options)")
        try:
            build_dmg(str(out), VOLUME_NAME, settings=options, lookForHiDPI=True, detach_retries=20)
        except Exception as error:        # dmgbuild shells out to hdiutil; anything can happen in CI
            log("dmgbuild failed:", type(error).__name__, str(error)[-600:])
            continue
        if out.is_file() and out.stat().st_size > 1_000_000:
            return True
        log("dmgbuild reported success but produced no usable image")
    return False


def build_plain(app: Path, out: Path) -> None:
    """Fallback: a correct-but-plain folder image, so a release never hangs."""
    stage = Path(tempfile.mkdtemp(prefix="sreon-dmg-"))
    try:
        shutil.copytree(app, stage / app.name, symlinks=True)
        (stage / "Applications").symlink_to("/Applications")
        if out.exists():
            out.unlink()
        sh(["hdiutil", "create", "-volname", VOLUME_NAME, "-srcfolder", str(stage), "-ov",
            "-fs", "HFS+", "-format", "UDZO", "-imagekey", "zlib-level=9", str(out)], check=True)
    finally:
        shutil.rmtree(stage, ignore_errors=True)


def verify(out: Path, app_name: str) -> str:
    """Verify checksums and mount the image to prove the payload is really inside."""
    code, output = sh(["hdiutil", "verify", str(out)])
    if code:
        raise SystemExit(f"hdiutil verify failed: {output[-800:]}")
    mount = Path(tempfile.mkdtemp(prefix="sreon-check-"))
    try:
        code, output = sh(["hdiutil", "attach", "-readonly", "-noverify", "-noautoopen",
                           "-mountpoint", str(mount), str(out)])
        if code:
            raise SystemExit(f"could not mount the image: {output[-800:]}")
        listing = sorted(item.name for item in mount.iterdir() if not item.name.startswith("."))
        binary = mount / app_name / "Contents" / "MacOS" / Path(app_name).stem
        if app_name not in listing or not binary.is_file():
            raise SystemExit(f"mounted image is wrong: {listing}")
        if not (mount / "Applications").is_symlink():
            raise SystemExit("Applications drop link is missing from the image")
        background = list(mount.glob(".background*"))
        log("mounted ok:", listing, "background:", [item.name for item in background])
        details = sh(["codesign", "-dvvv", str(mount / app_name)])[1]
        signature = "ad-hoc" if "Signature=adhoc" in details else (
            "Developer ID" if "Authority=Developer ID" in details else "not signed")
        notarised = "sealed" if "notarizationticket" in details.lower() else "not notarised"
        summary = f"{listing} · signed: {signature} ({notarised})"
        sh(["hdiutil", "detach", str(mount), "-force"])
        return summary
    finally:
        shutil.rmtree(mount, ignore_errors=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("app", type=Path)
    parser.add_argument("out", type=Path)
    parser.add_argument("--plain", action="store_true", help="skip dmgbuild (CI smoke test)")
    parser.add_argument("--background-only", action="store_true",
                        help="just render the artwork and print the geometry")
    args = parser.parse_args()

    if args.background_only:
        artwork()
        return

    app = args.app.resolve()
    if not app.is_dir():
        raise SystemExit(f"no app bundle at {app}")
    out = args.out.resolve()
    out.parent.mkdir(parents=True, exist_ok=True)

    prepare_app(app)
    styled = False if args.plain else build_with_dmgbuild(app, out)
    if not styled:
        build_plain(app, out)
    summary = verify(out, app.name)
    log("wrote", out, f"{out.stat().st_size / 1e6:.0f} MB", "styled" if styled else "plain", "|", summary)
    print(f"::notice::Sreon.dmg {'uses the styled layout' if styled else 'fell back to a plain image'} · {summary}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
