"""Packaging invariants: version, artwork geometry, installer scripts, honest advice.

These are cheap checks that fail the build for the mistakes that actually happen in
this repo: a stale version string in one of five places, artwork whose text no longer
fits the window, an NSIS script that references a bitmap nobody committed, or a guide
file that starts telling users to switch their security features off.
"""

import re
import sys
from pathlib import Path

import pytest

BROWSER = Path(__file__).resolve().parents[1]
REPO = BROWSER.parent
sys.path.insert(0, str(BROWSER / "tools"))

SEMVER = re.compile(r"^\d+\.\d+\.\d+$")


def version():
    return (BROWSER / "VERSION").read_text(encoding="utf-8").splitlines()[0].strip()


def test_version_file_is_semver():
    assert SEMVER.match(version()), "Browser/VERSION must look like 1.2.3"


def test_every_manifest_agrees_on_the_version():
    cargo = (BROWSER / "search" / "Cargo.toml").read_text(encoding="utf-8")
    found = re.search(r'^version = "([^"]+)"', cargo, re.M).group(1)
    assert found == version(), f"Browser/search/Cargo.toml says {found}, VERSION says {version()}"


def test_artwork_exists_at_both_scales_and_matches_the_window():
    from make_dmg_background import WINDOW, render

    for name, scale in (("dmg-background.png", 1), ("dmg-background@2x.png", 2)):
        path = BROWSER / "assets" / name
        assert path.is_file(), f"{path.name} is missing - run tools/make_dmg_background.py"
        # PNG header: bytes 16..24 are the big-endian width/height
        head = path.read_bytes()[:24]
        width = int.from_bytes(head[16:20], "big")
        height = int.from_bytes(head[20:24], "big")
        assert (width, height) == (WINDOW[0] * scale, WINDOW[1] * scale), (
            f"{path.name} is {width}x{height}, needs {WINDOW[0] * scale}x{WINDOW[1] * scale}"
        )
    render(1.0)  # raises SystemExit if any text run no longer fits the window


def test_icons_sit_inside_their_panels_and_clear_of_the_instruction_card():
    from make_dmg_background import CARD, CHIP, DROP, ICON_SIZE, layout

    positions = layout()["icon_locations"]
    for name, (x, y) in positions.items():
        panel = CHIP if name == "Sreon.app" else DROP
        assert x >= panel[0], name
        assert x + ICON_SIZE <= panel[2], f"{name} icon runs past its panel"
        assert y >= panel[1], name
        # Finder draws the label just under the icon; it must not touch the card below
        assert y + ICON_SIZE + 22 <= panel[3] <= CARD[1], f"{name} label collides with the card"


def test_guide_shows_the_documented_route_and_never_disables_security():
    guide = (REPO / "If-it-says-unverified.txt").read_text(encoding="utf-8")
    for phrase in ("Privacy & Security", "Open Anyway", "More info", "Run anyway",
                   "Sreon.dmg", "SreonSetup.exe", "Sreon.AppImage", "chmod +x"):
        assert phrase in guide, f"guide lost {phrase!r}"
    forbidden = ("sudo spctl", "spctl --global-disable", "xattr -dr", "xattr -cr",
                 "-noverify", "Gatekeeper: disabled")
    for phrase in forbidden:
        assert phrase not in guide, f"guide must not tell users to run {phrase!r}"


def test_help_dialog_matches_the_guide():
    window = (BROWSER / "app" / "window.py").read_text(encoding="utf-8")
    assert "If Sreon Won't Open" in window
    assert "Open Anyway" in window and "Privacy & Security" in window
    for phrase in ("spctl", "xattr", "noverify"):
        assert phrase not in window, f"the in-app dialog mentions {phrase!r}"


def test_nsis_script_is_fully_parameterised_and_branded():
    script = (BROWSER / "installer" / "nsis" / "Sreon.nsi").read_text(encoding="utf-8")
    for define in ("VERSION", "SOURCE_DIR", "ICON", "GUIDE", "OUTFILE", "ARTDIR"):
        assert f"!ifndef {define}" in script, f"{define} must have a fallback, not a hardcoded value"
    assert "RequestExecutionLevel admin" in script
    assert "Uninstall" in script and "GetSize" in script
    for bitmap in ("header.bmp", "welcome.bmp"):
        assert bitmap in script, f"installer art {bitmap} is referenced nowhere"
        assert (BROWSER / "installer" / "nsis" / bitmap).is_file(), f"{bitmap} was never generated"
    assert script.count("!insertmacro MUI_DESCRIPTION_TEXT") == script.count(
        "!insertmacro MUI_FUNCTION_DESCRIPTION_BEGIN") or "!insertmacro MUI_FUNCTION_DESCRIPTION_BEGIN" in script, \
        "MUI_DESCRIPTION_TEXT emits ${elseif}: it must sit inside MUI_FUNCTION_DESCRIPTION_BEGIN/END"


@pytest.mark.parametrize("tool", ["build.py", "make_dmg.py", "make_dmg_background.py"])
def test_packaging_scripts_compile(tool):
    path = BROWSER / "tools" / tool
    compile(path.read_text(encoding="utf-8"), str(path), "exec")


def test_bundle_carries_the_files_the_app_reads_at_runtime():
    build = (BROWSER / "tools" / "build.py").read_text(encoding="utf-8")
    for needed in ('(ROOT / "VERSION", ".")', '"engine"', "If-it-says-unverified.txt"):
        assert needed in build, f"build.py no longer bundles {needed}"


# ---------------------------------------------------------------- dmg self-checks
def _fake_volume(root: Path):
    """A directory that looks exactly like a correctly built mounted image."""
    bundle = root / "Sreon.app"
    binary = bundle / "Contents" / "MacOS" / "Sreon"
    binary.parent.mkdir(parents=True)
    binary.write_bytes(b"\xcf\xfa\xed\xfe fake mach-o")
    binary.chmod(0o755)
    helpers = bundle / "Contents" / "Frameworks" / "QtWebEngineCore.framework" / "Helpers"
    helpers.mkdir(parents=True)
    (bundle / "Contents" / "Info.plist").write_text("<plist/>", encoding="utf-8")
    (root / ".background").mkdir()
    (root / ".background" / "dmg-background.png").write_bytes(b"\x89PNG")
    (root / "Applications").symlink_to("/Applications")
    return root


def _write_store(volume: Path, background_type: int) -> None:
    from ds_store import DSStore

    with DSStore.open(str(volume / ".DS_Store"), "w+") as handle:
        handle["."]["vSrn"] = ("long", 1)
        handle["."]["icvp"] = ("blob", {
            "viewOptionsVersion": 1, "backgroundType": background_type,
            "iconSize": 128.0, "textSize": 13.0,
            "backgroundColorRed": 1.0, "backgroundColorGreen": 1.0, "backgroundColorBlue": 1.0,
            "backgroundImageAlias": b"\x00\x00alias",
            "gridOffsetX": 0.0, "gridOffsetY": 0.0, "gridSpacing": 100.0,
            "arrangeBy": "none", "showIconPreview": True, "showItemInfo": False,
            "labelOnBottom": True, "scrollPositionX": 0.0, "scrollPositionY": 0.0})
        handle["."]["bwsp"] = ("blob", {"ShowStatusBar": False, "ShowSidebar": False,
                                       "WindowBounds": "{{100, 100}, {680, 486}}"})
        handle["Sreon.app"]["Iloc"] = (76, 146)
        handle["Applications"]["Iloc"] = (476, 146)


def test_check_dmg_passes_a_good_volume_and_fails_an_unstyled_one(tmp_path):
    import importlib.util

    if importlib.util.find_spec("ds_store") is None:
        pytest.skip("ds_store is a build extra (pip install dmgbuild)")
    sys.path.insert(0, str(BROWSER / "tools"))
    from check_dmg import check

    volume = _fake_volume(tmp_path / "Sreon")
    _write_store(volume, background_type=2)
    findings, problems = check(volume)
    assert problems == [], problems
    assert any("drop link" in line for line in findings)
    assert any("icon positions" in line for line in findings)
    assert any("backgroundType=2" in line for line in findings)

    # same image, but the picture record says "flat colour": the design never landed
    (volume / ".DS_Store").unlink()
    _write_store(volume, background_type=1)
    _, problems = check(volume)
    assert any("backgroundType is 1" in line for line in problems), problems


def test_check_dmg_reports_a_plain_folder_image(tmp_path):
    sys.path.insert(0, str(BROWSER / "tools"))
    from check_dmg import check

    volume = _fake_volume(tmp_path / "Sreon")
    (volume / ".background").rename(volume / "leftover")   # no artwork, no .DS_Store
    _, problems = check(volume)
    assert any(".background" in line for line in problems)
    assert any(".DS_Store" in line for line in problems)
