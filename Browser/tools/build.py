#!/usr/bin/env python3
"""Build Sreon for every desktop: the frozen app, then one double-clickable file per OS.

    macOS    dist/Sreon.app  ->  dist/Sreon.dmg (styled)  +  dist/Sreon.pkg
    Windows  dist/Sreon/Sreon.exe  ->  dist/SreonSetup.exe (NSIS, branded)
    Linux    dist/Sreon/Sreon  ->  dist/Sreon.AppImage (double click)  +  dist/sreon_amd64.deb

Everything reads its version from Browser/VERSION so the bundle, the installers,
the search engine and the artwork can never disagree.

    python3 Browser/tools/build.py --skip-engine          # everything for this OS
    python3 Browser/tools/build.py --only dmg            # just the disk image
    SREON_CODESIGN_IDENTITY="Developer ID Application: ..." python3 Browser/tools/build.py

`--skip-engine` expects Browser/engine/sreon-api to exist already (CI compiles it
with cargo first).  Without it, this script runs cargo itself.
"""

from __future__ import annotations

import argparse
import os
import platform
import shutil
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
ROOT = TOOLS.parent                     # Browser/
REPO = ROOT.parent

STEPS = ("engine", "app", "installer", "dmg", "pkg", "nsis", "appimage", "deb")


def version() -> str:
    return (ROOT / "VERSION").read_text(encoding="utf-8").splitlines()[0].strip()


def machine():
    arm = platform.machine().lower() in ("arm64", "aarch64", "armv8l")
    return {"win32": ("windows", "amd64" if not arm else "arm64"),
            "darwin": ("macos", "arm64" if arm else "x86_64"),
            }.get(sys.platform, ("linux", "arm64" if arm else "amd64"))


def engine_name():
    return "sreon-api.exe" if sys.platform == "win32" else "sreon-api"


class Builder:
    def __init__(self, args):
        self.args = args
        self.version = version()
        self.os_name, self.arch = machine()
        self.dist = ROOT / "dist"
        self.log_path = ROOT / "freeze.log"
        self.produced = []
        self.notes = []

    # ---------------------------------------------------------------- plumbing
    def want(self, step) -> bool:
        only = self.args.only
        return only is None or step in only

    def run(self, command, *, cwd=None, check=True, env=None):
        printable = " ".join(str(part) for part in command)
        print("+", printable, flush=True)
        with self.log_path.open("a", encoding="utf-8") as handle:
            handle.write(f"\n$ {printable}\n")
            handle.flush()
            process = subprocess.run([str(part) for part in command], cwd=str(cwd or ROOT),
                                     stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                     text=True, env={**os.environ, **(env or {})})
        text = process.stdout or ""
        with self.log_path.open("a", encoding="utf-8") as handle:
            handle.write(text)
        tail = text.strip().splitlines()[-40:]
        print("\n".join(tail)[-3000:], flush=True)
        if process.returncode:
            snippet = text[-2500:].replace("\r", " ").replace("%", "/")
            print(f"::error::{snippet[:3900]}", flush=True)
            if check:
                raise SystemExit(f"step failed ({process.returncode}): {printable}")
        return process.returncode, text

    def note(self, message):
        self.notes.append(message)
        print("::warning::" + message, flush=True)

    def record(self, path: Path, kind: str):
        if path.is_file() and path.stat().st_size:
            self.produced.append((kind, path, path.stat().st_size))
            print(f"built {kind}: {path}  {path.stat().st_size / 1e6:.1f} MB", flush=True)
            return True
        return False

    # ------------------------------------------------------------------ engine
    def engine(self):
        """Compile the native search sidecar the frozen app ships inside itself."""
        target = ROOT / "engine" / engine_name()
        manifest = ROOT / "search" / "Cargo.toml"
        built = ROOT / "search" / "target" / "release" / engine_name()
        if target.is_file() and built.is_file() and target.stat().st_mtime >= built.stat().st_mtime:
            print("engine already current:", target, flush=True)
            return
        if shutil.which("cargo") is None:
            if target.is_file():
                self.note("cargo missing, using the engine binary already in Browser/engine")
                return
            raise SystemExit("cargo is needed to build the search engine (https://rustup.rs)")
        if not manifest.is_file():
            raise SystemExit(f"no search engine source at {manifest}")
        self.run(["cargo", "build", "--release", "--manifest-path", str(manifest),
                  "--bin", "sreon-api"])
        if not built.is_file():
            raise SystemExit("cargo finished without producing sreon-api")
        target.parent.mkdir(exist_ok=True)
        shutil.copy2(built, target)
        if sys.platform != "win32":
            os.chmod(target, 0o755)
        print("engine ready:", target, flush=True)

    # --------------------------------------------------------------------- app
    def version_file(self) -> Path:
        """A PyInstaller --version-file so Info.plist / EXE properties carry our version."""
        path = ROOT / "build" / "sreon-version.txt"
        path.parent.mkdir(parents=True, exist_ok=True)
        parts = (self.version.split(".") + ["0", "0", "0"])[:4]
        numeric = ",".join(part for part in parts)
        body = ("# UTF-8\n"
                "VSVersionInfo(\n"
                "  ffi=FixedFileInfo(filevers=(" + numeric + "), prodvers=(" + numeric + "),\n"
                "    mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0, resources=(0, 0)),\n"
                "  kids=[\n"
                "    StringFileInfo([\n"
                "      StringTable(u\"040904b0\", [\n"
                "        StringStruct(u\"CompanyName\", u\"Sreon\"),\n"
                "        StringStruct(u\"FileDescription\", u\"Sreon browser\"),\n"
                "        StringStruct(u\"FileVersion\", u\"" + self.version + "\"),\n"
                "        StringStruct(u\"InternalName\", u\"Sreon\"),\n"
                "        StringStruct(u\"LegalCopyright\", u\"Free and open source - no warranty\"),\n"
                "        StringStruct(u\"OriginalFilename\", u\"Sreon.exe\"),\n"
                "        StringStruct(u\"ProductName\", u\"Sreon\"),\n"
                "        StringStruct(u\"ProductVersion\", u\"" + self.version + "\")])]),\n"
                "    VarFileInfo([VarStruct(u\"Translation\", [1033, 1200])])\n"
                "  ]\n"
                ")\n")
        path.write_text(body, encoding="utf-8")
        return path

    def pyinstaller(self, entry, name, *, data, extra=(), windowed=True):
        command = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
                   "--name", name, "--distpath", str(self.dist), "--workpath",
                   str(ROOT / "build"), "--specpath", str(ROOT / "build")]
        if windowed:
            command.append("--windowed")
        sep = ";" if sys.platform == "win32" else ":"
        for source, destination in data:
            command += ["--add-data", f"{source}{sep}{destination}"]
        qt = ["PySide6.QtCore", "PySide6.QtGui", "PySide6.QtWidgets", "PySide6.QtNetwork",
              "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtWebChannel",
              "PySide6.QtPrintSupport", "PySide6.QtSvg", "shiboken6", "cryptography"]
        if name == "Sreon":
            for module in qt:
                command += ["--hidden-import", module]
        command += ["--exclude-module", "tkinter", "--exclude-module", "matplotlib",
                    "--exclude-module", "numpy", "--exclude-module", "pytest"]
        if sys.platform == "darwin":
            icns = ROOT / "assets" / "icon.icns"
            if icns.is_file():
                command += ["--icon", str(icns)]
            command += ["--osx-bundle-identifier",
                        "com.sreon.browser" if name == "Sreon" else "com.sreon.installer"]
        elif sys.platform == "win32":
            ico = ROOT / "assets" / "icon.ico"
            if ico.is_file():
                command += ["--icon", str(ico)]
        if sys.platform in ("win32", "darwin") and name == "Sreon":
            command += ["--version-file", str(self.version_file())]
        command += list(extra) + [str(entry)]
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        self.run(command)

    def app(self):
        guide = REPO / "If-it-says-unverified.txt"
        self.pyinstaller(Path("app/main.py"), "Sreon",
                         data=[(ROOT / "assets", "assets"), (ROOT / "engine", "engine"),
                               (ROOT / "VERSION", "."), (guide, ".")])
        launcher = "Sreon.exe" if sys.platform == "win32" else "Sreon"
        bundle = self.app_bundle()
        if sys.platform == "darwin":
            if bundle is None:
                raise SystemExit("PyInstaller finished without producing dist/Sreon.app")
            roots = [bundle / "Contents" / "Resources"]
            found = bundle / "Contents" / "MacOS" / launcher
            kind = "app bundle"
        else:
            directory = self.app_dir()
            roots = [directory / "_internal", directory]
            found = directory / launcher
            kind = "app folder"
        if not found.is_file():
            raise SystemExit(f"PyInstaller produced no launcher at {found}")

        # PyInstaller 6 keeps collected data under _internal (or Contents/Resources in a
        # .app). Check the files the app reads at runtime really travelled with it, or a
        # frozen Sreon would silently lose its start page, its engine and its guide.
        for required in ("assets", "engine", "VERSION", "If-it-says-unverified.txt"):
            if not any((root / required).exists() for root in roots if root.is_dir()):
                raise SystemExit(f"bundle is missing {required!r} (looked in "
                                 + ", ".join(str(root) for root in roots) + ")")
        self.record(found, kind)

    def app_dir(self) -> Path:
        """The onedir folder (Windows/Linux) that holds Sreon(.exe)."""
        for candidate in (self.dist / "Sreon", self.dist):
            if (candidate / ("Sreon.exe" if sys.platform == "win32" else "Sreon")).is_file():
                return candidate
        return self.dist / "Sreon"

    def app_bundle(self):
        """The .app bundle on macOS (PyInstaller nests it under dist/Sreon in some layouts)."""
        if sys.platform != "darwin":
            return None
        for candidate in (self.dist / "Sreon.app", self.dist / "Sreon" / "Sreon.app"):
            if candidate.is_dir():
                return candidate
        return None

    # -------------------------------------------------------------- installer
    def installer(self):
        """Optional native installer GUI (off by default: dmg/pkg/NSIS already cover it)."""
        if not self.args.installer_app:
            print("skipping the custom installer app (pass --installer-app to build it)", flush=True)
            return
        entry = {"darwin": "installer/mac_installer.py", "win32": "installer/win_installer.py",
                 }.get(sys.platform, "installer/linux_installer.py")
        self.pyinstaller(Path(entry), "Sreon Installer",
                         data=[(ROOT / "assets", "assets"), (ROOT / "installer", "installer")],
                         extra=["--hidden-import", "installer.installer_ui"])

    # --------------------------------------------------------------------- dmg
    def dmg(self):
        if sys.platform != "darwin":
            print("dmg: needs macOS, skipped here", flush=True)
            return
        app = self.app_bundle()
        if app is None:
            raise SystemExit("no Sreon.app to package")
        out = self.dist / "Sreon.dmg"
        code, _ = self.run([sys.executable, str(TOOLS / "make_dmg.py"), str(app), str(out)],
                           check=False)
        if not self.record(out, "dmg"):
            raise SystemExit("disk image was not produced")

    def pkg(self):
        app = self.app_bundle()
        if app is None or sys.platform != "darwin":
            return
        root = self.dist / "pkgroot"
        shutil.rmtree(root, ignore_errors=True)
        (root / "Applications").mkdir(parents=True)
        self.run(["ditto", str(app), str(root / "Applications" / app.name)])
        out = self.dist / "Sreon.pkg"
        if out.exists():
            out.unlink()
        self.run(["pkgbuild", "--root", str(root), "--identifier", "com.sreon.browser",
                  "--version", self.version, "--install-location", "/", str(out)])
        identity = (os.environ.get("SREON_PRODUCTSIGN_IDENTITY") or "").strip()
        if identity:
            signed = self.dist / "Sreon-signed.pkg"
            self.run(["productsign", "--sign", identity, str(out), str(signed)], check=False)
            if signed.is_file():
                signed.replace(out)
        else:
            print("pkg is unsigned (set SREON_PRODUCTSIGN_IDENTITY to sign it)", flush=True)
        self.record(out, "pkg")

    # -------------------------------------------------------------------- nsis
    def nsis(self):
        if sys.platform != "win32":
            print("nsis: needs Windows to freeze Sreon.exe, skipped here", flush=True)
            return
        source = self.app_dir()
        if not (source / "Sreon.exe").is_file():
            raise SystemExit(f"no Sreon.exe in {source}")
        makensis = None
        for candidate in ("makensis", "makensis.exe"):
            found = shutil.which(candidate)
            if found:
                makensis = found
                break
        if makensis is None:
            # choco/brew/manual installs are not always on PATH in the same shell
            for guess in ("C:/Program Files (x86)/NSIS/makensis.exe",
                          "C:/Program Files/NSIS/makensis.exe",
                          "/usr/local/bin/makensis", "/opt/homebrew/bin/makensis",
                          "/usr/bin/makensis"):
                if Path(guess).is_file():
                    makensis = guess
                    break
        if makensis is None:
            raise SystemExit("makensis not found - install NSIS (choco install nsis / "
                             "brew install nsis / apt install nsis) or pass --only without nsis")
        print("makensis:", makensis, flush=True)
        out = self.dist / "SreonSetup.exe"
        if out.exists():
            out.unlink()
        nsi = ROOT / "installer" / "nsis" / "Sreon.nsi"
        art = nsi.parent
        missing = [name for name in ("header.bmp", "welcome.bmp") if not (art / name).is_file()]
        if missing:
            self.run([sys.executable, str(TOOLS / "make_dmg_background.py"), "--nsis-assets"], check=False)
        self.run([makensis, f"-DVERSION={self.version}", f"-DSOURCE_DIR={source.as_posix()}",
                  f"-DICON={(ROOT / 'assets' / 'icon.ico').as_posix()}",
                  f"-DARTDIR={art.as_posix()}",
                  f"-DGUIDE={(ROOT.parent / 'If-it-says-unverified.txt').as_posix()}",
                  f"-DOUTFILE={out.as_posix()}", str(nsi)])
        if not self.record(out, "exe installer"):
            raise SystemExit("NSIS produced no installer")

    # ----------------------------------------------------------------- appimage
    def appimage(self):
        source = self.app_dir()
        if sys.platform.startswith("linux"):
            binary = source / "Sreon"
        else:
            return
        if not binary.is_file():
            raise SystemExit(f"no Linux binary at {binary}")
        appdir = self.dist / "AppDir"
        shutil.rmtree(appdir, ignore_errors=True)
        payload = appdir / "usr" / "bin" / "Sreon"
        payload.parent.mkdir(parents=True)
        shutil.copytree(source, payload)
        os.chmod(payload / "Sreon", 0o755)
        (appdir / "AppRun").write_text(
            "#!/bin/sh\n"
            "# Sreon lives in usr/bin/Sreon next to its _internal folder, so start from there.\n"
            'here="$(dirname "$(readlink -f "$0")")"\n'
            'exec "$here/usr/bin/Sreon/Sreon" "$@"\n', encoding="utf-8")
        os.chmod(appdir / "AppRun", 0o755)
        shutil.copy2(ROOT / "assets" / "mark.png", appdir / "sreon.png")
        (appdir / "sreon.desktop").write_text(
            "[Desktop Entry]\nType=Application\nName=Sreon\nComment=Search privately. Browse freely.\n"
            "Exec=Sreon %U\nIcon=sreon\nTerminal=false\nCategories=Network;WebBrowser;\n"
            "StartupWMClass=Sreon\nKeywords=browser;private;search;\n", encoding="utf-8")
        tool = shutil.which("appimagetool")
        if tool is None and (TOOLS / "linux" / "appimagetool").is_file():
            tool = str(TOOLS / "linux" / "appimagetool")
        out = self.dist / "Sreon.AppImage"
        if out.exists():
            out.unlink()
        if tool is None:
            archive = self.dist / "Sreon-linux.tar.gz"
            with tarfile.open(archive, "w:gz") as tar:
                tar.add(source, arcname="Sreon")
            self.record(archive, "linux folder archive")
            self.note("appimagetool missing - built Sreon-linux.tar.gz instead of Sreon.AppImage")
            return
        env = {"ARCH": "aarch64" if self.arch == "arm64" else "x86_64"}
        self.run([tool, str(appdir), str(out)], check=False, env=env)
        if not self.record(out, "appimage"):
            archive = self.dist / "Sreon-linux.tar.gz"
            with tarfile.open(archive, "w:gz") as tar:
                tar.add(source, arcname="Sreon")
            self.record(archive, "linux folder archive")
            self.note("appimagetool failed - built Sreon-linux.tar.gz instead")
        else:
            os.chmod(out, 0o755)

    # --------------------------------------------------------------------- deb
    def deb(self):
        if not sys.platform.startswith("linux"):
            return
        source = self.app_dir()
        root = self.dist / "deb"
        shutil.rmtree(root, ignore_errors=True)
        (root / "DEBIAN").mkdir(parents=True)
        shutil.copytree(source, root / "opt" / "sreon")
        for directory, name in (("usr/share/applications", "sreon.desktop"),):
            (root / directory).mkdir(parents=True, exist_ok=True)
        (root / "usr" / "share" / "applications" / "sreon.desktop").write_text(
            "[Desktop Entry]\nType=Application\nName=Sreon\nGenericName=Web Browser\n"
            "Comment=Search privately. Browse freely.\nExec=/opt/sreon/Sreon %u\nIcon=sreon\n"
            "Terminal=false\nCategories=Network;WebBrowser;\nStartupWMClass=Sreon\n"
            "Keywords=browser;private;search;\n", encoding="utf-8")
        icons = root / "usr" / "share" / "icons" / "hicolor" / "256x256" / "apps"
        icons.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / "assets" / "mark.png", icons / "sreon.png")
        shutil.copy2(REPO / "If-it-says-unverified.txt", root / "opt" / "sreon" / "If-it-says-unverified.txt")
        (root / "DEBIAN" / "control").write_text(
            f"""Package: sreon
Version: {self.version}
Section: web
Priority: optional
Architecture: {self.arch if self.arch != 'x86_64' else 'amd64'}
Maintainer: Sreon <sreon@localhost>
Depends: libgl1, libnss3, libxkbcommon0, libasound2t64 | libasound2
Recommends: libvulkan1
Description: Sreon - private browser
 A native desktop browser with its own search front-end: Qt WebEngine (Chromium)
 pages, encrypted local vault, no accounts and no telemetry.
 .
 Websites need internet access. Queries go to the public search sources the
 built-in engine adapts; Sreon itself never phones home.
""", encoding="utf-8")
        doc = root / "usr" / "share" / "doc" / "sreon"
        doc.mkdir(parents=True, exist_ok=True)
        date = subprocess.run(["date", "-R"], capture_output=True, text=True).stdout.strip()
        import gzip
        with gzip.open(doc / "changelog.Debian.gz", "wb") as handle:
            handle.write(f"sreon ({self.version}) stable; urgency=low\n"
                         f"\n  * Sreon {self.version}: installer artwork, native AppImage and\n"
                         "    deb packaging, corrected Gatekeeper guidance.\n"
                         f"\n -- Sreon <sreon@localhost>  {date}\n".encode("utf-8"))
        (doc / "README.Debian").write_text(
            "Sreon is installed in /opt/sreon and started from /usr/share/applications/sreon.desktop.\n"
            "Your profile lives in $XDG_DATA_HOME/sreon (usually ~/.local/share/sreon).\n"
            "If Sreon will not open, read /opt/sreon/If-it-says-unverified.txt.\n", encoding="utf-8")

        out = self.dist / f"sreon_{self.version}_{self.arch if self.arch != 'x86_64' else 'amd64'}.deb"
        if out.exists():
            out.unlink()
        self.run(["chmod", "-R", "a+rX", str(root / "DEBIAN")])
        self.run(["dpkg-deb", "--root-owner-group", "--build", str(root), str(out)])
        self.record(out, "deb")

    # ------------------------------------------------------------------- misc
    def bundle_zip(self):
        """A zip of the bare launcher for people who refuse installers (Windows/Linux)."""
        if sys.platform == "darwin":
            return
        source = self.app_dir()
        out = self.dist / f"Sreon-{self.os_name}-{self.arch}.zip"
        if out.exists():
            out.unlink()
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
            for path in sorted(source.rglob("*")):
                if path.is_file():
                    archive.write(path, f"Sreon/{path.relative_to(source).as_posix()}")
        self.record(out, "portable zip")

    def summary(self):
        print("\n=== artifacts ===", flush=True)
        for kind, path, size in self.produced:
            print(f"  {kind:16s} {path.name:26s} {size / 1e6:8.1f} MB", flush=True)
        for note in self.notes:
            print("  note:", note, flush=True)
        if not self.produced:
            print("  (nothing - every step was skipped)", flush=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--only", nargs="+", choices=STEPS, default=None,
                        help="build just these steps (default: everything this OS can do)")
    parser.add_argument("--skip-engine", action="store_true",
                        help="use the engine binary already in Browser/engine")
    parser.add_argument("--installer-app", action="store_true",
                        help="also freeze the custom Qt installer GUI")
    parser.add_argument("--zip", action="store_true",
                        help="also zip the unpacked folder as a portable fallback")
    args = parser.parse_args(argv)

    builder = Builder(args)
    builder.log_path.write_text(
        f"Sreon {builder.version} build log ({builder.os_name}/{builder.arch})\n")
    print(f"Sreon {builder.version} on {builder.os_name}/{builder.arch} -> {builder.dist}", flush=True)

    def step(name, action):
        if builder.want(name):
            action()

    if not args.skip_engine:
        step("engine", builder.engine)
    step("app", builder.app)
    step("installer", builder.installer)
    step("dmg", builder.dmg)
    step("pkg", builder.pkg)
    step("nsis", builder.nsis)
    step("appimage", builder.appimage)
    step("deb", builder.deb)
    if args.zip:
        builder.bundle_zip()
    builder.summary()


if __name__ == "__main__":
    main()
