import os
import sys
import shutil
import subprocess
import platform
from pathlib import Path

from PySide6.QtCore import Qt, QThread, Signal, QTimer
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QProgressBar, QTextEdit, QFrame
)

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "assets"

def asset_path(name):
    for p in [ASSETS / name, ROOT / name, Path(__file__).parent / name]:
        if p.exists():
            return p
    return None

def find_sreon_app():
    here = Path(__file__).resolve().parent
    candidates = [
        Path(sys.executable).parent / "Sreon.app" if platform.system() == "Darwin" else None,
        here.parent / "dist" / "Sreon.app",
        here / "Sreon.app",
        Path.cwd() / "Sreon.app",
        Path("/Volumes/Sreon/Sreon.app"),
        Path.home() / "Downloads" / "Sreon.app",
    ]
    for base in [Path(sys.argv[0]).parent, Path.cwd(), here.parent, here.parent.parent]:
        candidates.append(base / "Sreon.app")
        candidates.append(base / "macOS" / "Sreon.app")
        candidates.append(base / "Sreon.app")
    for c in candidates:
        if c and c.exists():
            return c
    return None

def find_sreon_folder():
    here = Path(__file__).resolve().parent
    candidates = [
        here.parent / "dist" / "Sreon",
        here / "Sreon",
        Path.cwd() / "Sreon",
        Path(sys.executable).parent / "Sreon",
    ]
    for c in candidates:
        if c and c.exists() and (c / "Sreon.exe").exists() or (c / "Sreon").exists():
            return c
    for base in [Path(sys.argv[0]).parent, Path.cwd()]:
        for name in ["Sreon", "Windows"]:
            p = base / name
            if p.exists() and ((p / "Sreon.exe").exists() or (p / "Sreon").exists()):
                return p
    return None

class InstallWorker(QThread):
    progress = Signal(int, str)
    finished_ok = Signal(str)
    finished_err = Signal(str)

    def __init__(self, mode):
        super().__init__()
        self.mode = mode

    def run(self):
        try:
            if self.mode == "mac":
                self.install_mac()
            elif self.mode == "win":
                self.install_win()
            else:
                self.install_linux()
        except Exception as e:
            self.finished_err.emit(str(e))

    def install_mac(self):
        self.progress.emit(10, "Finding Sreon.app")
        src = find_sreon_app()
        if not src:
            for p in [Path("/Volumes/Sreon/Sreon.app"), Path.cwd() / "Sreon.app", Path.home() / "Downloads" / "Sreon.app"]:
                if p.exists():
                    src = p
                    break
        if not src or not src.exists():
            raise RuntimeError("Sreon.app not found next to installer. Please keep Sreon.app and Installer together in the DMG.")
        self.progress.emit(25, "Preparing")
        try:
            subprocess.run(["xattr", "-cr", str(src)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)
        except Exception:
            pass
        dest_root = Path("/Applications")
        if not os.access(dest_root, os.W_OK):
            dest_root = Path.home() / "Applications"
            dest_root.mkdir(parents=True, exist_ok=True)
        dest = dest_root / "Sreon.app"
        self.progress.emit(40, f"Installing to {dest}")
        if dest.exists():
            self.progress.emit(45, "Removing old version")
            shutil.rmtree(dest, ignore_errors=True)
        self.progress.emit(60, "Copying")
        shutil.copytree(src, dest, symlinks=True)
        self.progress.emit(80, "Finishing")
        try:
            subprocess.run(["xattr", "-cr", str(dest)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=15)
        except Exception:
            pass
        exe = dest / "Contents" / "MacOS" / "Sreon"
        if exe.exists():
            try:
                os.chmod(exe, 0o755)
            except Exception:
                pass
        self.progress.emit(100, "Installed")
        self.finished_ok.emit(str(dest))

    def install_win(self):
        self.progress.emit(10, "Finding Sreon files")
        src = find_sreon_folder()
        if not src:
            here = Path(sys.argv[0]).parent
            if (here / "Sreon.exe").exists():
                src = here
            else:
                for p in [Path.cwd() / "Sreon", Path.cwd() / "Windows", here / "Windows"]:
                    if p.exists():
                        src = p
                        break
        if not src:
            raise RuntimeError("Sreon files not found")
        self.progress.emit(25, "Preparing")
        prog = Path(os.environ.get("PROGRAMFILES", r"C:\Program Files")) / "Sreon"
        local = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local"))) / "Sreon"
        dest = prog
        try:
            dest.mkdir(parents=True, exist_ok=True)
            test = dest / ".writetest"
            test.write_text("ok")
            test.unlink()
        except Exception:
            dest = local
            dest.mkdir(parents=True, exist_ok=True)
        self.progress.emit(50, f"Copying to {dest}")
        for item in src.iterdir():
            s = src / item.name
            d = dest / item.name
            if s.is_dir():
                if d.exists():
                    shutil.rmtree(d, ignore_errors=True)
                shutil.copytree(s, d, symlinks=True)
            else:
                shutil.copy2(s, d)
        self.progress.emit(75, "Creating shortcuts")
        try:
            start_menu = Path(os.environ.get("APPDATA", str(Path.home() / "AppData" / "Roaming"))) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Sreon"
            start_menu.mkdir(parents=True, exist_ok=True)
            self.create_shortcut(dest / "Sreon.exe", start_menu / "Sreon.lnk", dest)
            desktop = Path.home() / "Desktop"
            if desktop.exists():
                self.create_shortcut(dest / "Sreon.exe", desktop / "Sreon.lnk", dest)
        except Exception:
            pass
        self.progress.emit(100, "Installed")
        self.finished_ok.emit(str(dest))

    def create_shortcut(self, target, link_path, workdir):
        try:
            link_path.write_text(f"[InternetShortcut]\nURL=file:///{target}\n")
        except Exception:
            pass
        try:
            bat = link_path.with_suffix(".bat")
            bat.write_text(f'@echo off\nstart "" "{target}"\n')
        except Exception:
            pass

    def install_linux(self):
        self.progress.emit(10, "Finding Sreon")
        src = find_sreon_folder()
        if not src:
            here = Path(sys.argv[0]).parent
            if (here / "Sreon").exists():
                src = here
        if not src:
            raise RuntimeError("Sreon folder not found")
        self.progress.emit(30, "Preparing")
        dest = Path.home() / ".local" / "share" / "sreon"
        dest.mkdir(parents=True, exist_ok=True)
        self.progress.emit(50, f"Copying to {dest}")
        for item in src.iterdir():
            s = src / item.name
            d = dest / item.name
            if s.is_dir():
                if d.exists():
                    shutil.rmtree(d, ignore_errors=True)
                shutil.copytree(s, d, symlinks=True)
            else:
                shutil.copy2(s, d)
        exe = dest / "Sreon"
        if exe.exists():
            os.chmod(exe, 0o755)
        self.progress.emit(75, "Creating launcher")
        apps_dir = Path.home() / ".local" / "share" / "applications"
        apps_dir.mkdir(parents=True, exist_ok=True)
        desktop_file = apps_dir / "sreon.desktop"
        icon_src = ASSETS / "mark.png"
        icon_dest = dest / "sreon.png"
        if icon_src.exists():
            try:
                shutil.copy2(icon_src, icon_dest)
            except Exception:
                pass
        desktop_content = f"""[Desktop Entry]
Type=Application
Name=Sreon
Comment=Fast private browser
Exec={exe}
Icon={icon_dest if icon_dest.exists() else 'web-browser'}
Categories=Network;WebBrowser;
Terminal=false
StartupWMClass=Sreon
"""
        desktop_file.write_text(desktop_content)
        try:
            subprocess.run(["update-desktop-database", str(apps_dir)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5)
        except Exception:
            pass
        self.progress.emit(100, "Installed")
        self.finished_ok.emit(str(dest))


class InstallerWindow(QWidget):
    def __init__(self, mode):
        super().__init__()
        self.mode = mode
        self.setWindowTitle("Sreon Installer")
        self.setFixedSize(560, 500)
        self.setStyleSheet("""
            QWidget { background: #fdf8f0; color: #2a213a; font-family: 'DM Sans', 'Inter', sans-serif; }
            QLabel#title { font-size: 30px; font-weight: 900; color: #2a213a; letter-spacing: -0.5px; }
            QLabel#subtitle { font-size: 13px; color: #6b5a8a; line-height: 1.4; }
            QLabel#headerBg { background: qlineargradient(x1:0,y1:0,x2:1,y2:1, stop:0 #5c43a0, stop:1 #7a5fc2); border-radius: 16px; }
            QPushButton { background: #5c43a0; color: white; border-radius: 14px; padding: 14px 28px; font-size: 15px; font-weight: 800; border: none; }
            QPushButton:hover { background: #6d54b5; }
            QPushButton:pressed { background: #4d3890; }
            QPushButton:disabled { background: #ddd4ef; color: #8a7ab0; }
            QPushButton#open { background: #fdf8f0; color: #5c43a0; border: 2px solid #5c43a0; }
            QPushButton#open:hover { background: #f3eefc; }
            QPushButton#open:disabled { border-color: #ddd4ef; color: #b8a9d8; }
            QProgressBar { border: none; border-radius: 10px; background: #ece3f9; text-align: center; height: 22px; font-size: 11px; font-weight: 700; color: #5c43a0; }
            QProgressBar::chunk { background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 #5c43a0, stop:1 #8a72c0); border-radius: 10px; }
            QTextEdit { background: #ffffff; border: 1px solid #e8dff6; border-radius: 14px; padding: 12px; font-size: 12px; color: #4a3d66; selection-background-color: #ece3f9; }
            QLabel#guide { background: #f3eefc; border-radius: 10px; padding: 10px 14px; }
        """)
        icon_path = ASSETS / "mark.png"
        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0,0,0,0)
        outer.setSpacing(0)

        header_frame = QFrame()
        header_frame.setObjectName("headerBg")
        header_frame.setStyleSheet("QFrame#headerBg { background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 #5c43a0, stop:1 #7c5fc7); border-radius: 0px; }")
        header_frame.setFixedHeight(92)
        h_layout = QHBoxLayout(header_frame)
        h_layout.setContentsMargins(28,18,28,18)
        h_layout.setSpacing(16)
        icon_label = QLabel()
        if icon_path.exists():
            pix = QPixmap(str(icon_path)).scaled(64, 64, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            icon_label.setPixmap(pix)
        h_layout.addWidget(icon_label)
        title_box = QVBoxLayout()
        title_box.setSpacing(2)
        title = QLabel("Install Sreon")
        title.setObjectName("title")
        title.setStyleSheet("color: white; font-size: 28px; font-weight: 900;")
        subtitle_text = "Fast, private browser — installs to Applications" if mode == "mac" else "Fast, private browser — installs to Program Files" if mode == "win" else "Fast, private browser — appears in Applications"
        subtitle = QLabel(subtitle_text)
        subtitle.setObjectName("subtitle")
        subtitle.setStyleSheet("color: #d9cffd; font-size: 13px;")
        subtitle.setWordWrap(True)
        title_box.addWidget(title)
        title_box.addWidget(subtitle)
        h_layout.addLayout(title_box)
        h_layout.addStretch()
        dot = QLabel("●")
        dot.setStyleSheet("color: #a8f0c6; font-size: 14px;")
        h_layout.addWidget(dot)
        outer.addWidget(header_frame)

        content = QVBoxLayout()
        content.setContentsMargins(28,20,28,20)
        content.setSpacing(14)

        status_row = QHBoxLayout()
        self.status = QLabel("Ready to install")
        self.status.setStyleSheet("color: #5c43a0; font-weight: 800; font-size: 14px;")
        status_row.addWidget(self.status)
        status_row.addStretch()
        self.spinner = QLabel("")
        self.spinner.setStyleSheet("color: #8a72c0; font-size: 14px;")
        status_row.addWidget(self.spinner)
        content.addLayout(status_row)

        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setFormat("%p% — %v")
        content.addWidget(self.progress)

        self.log = QTextEdit()
        self.log.setReadOnly(True)
        self.log.setFixedHeight(170)
        self.log.setText("Sreon will be installed and appear in Applications / Start Menu.\n\n✦ Beautiful installer with loading — watch progress above.\n\nIf macOS says unverified:\n• Control-click Sreon → Open → Open (once)\n• System Settings → Privacy & Security → Open Anyway\n• Terminal: xattr -dr com.apple.quarantine /Applications/Sreon.app\n\nIf DMG won't open:\n• Control-click DMG → Open\n• Terminal: xattr -dr com.apple.quarantine ~/Downloads/Sreon.dmg\n• Terminal: hdiutil attach ~/Downloads/Sreon.dmg -noverify\n\nWindows: More info → Run anyway\nLinux DEB: sudo dpkg -i sreon.deb — appears in Applications\nLinux AppImage: chmod +x Sreon.AppImage\n")
        content.addWidget(self.log)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(12)
        self.install_btn = QPushButton("Install to Applications" if mode == "mac" else "Install Sreon")
        self.install_btn.clicked.connect(self.start_install)
        btn_row.addWidget(self.install_btn, 2)
        self.open_btn = QPushButton("Open Sreon")
        self.open_btn.setObjectName("open")
        self.open_btn.setEnabled(False)
        self.open_btn.clicked.connect(self.open_app)
        btn_row.addWidget(self.open_btn, 1)
        content.addLayout(btn_row)

        self.guide = QLabel()
        self.guide.setObjectName("guide")
        self.guide.setWordWrap(True)
        self.guide.setStyleSheet("font-size: 11px; color: #6b5a8a; background: #f3eefc; border-radius: 10px; padding: 10px 12px;")
        self.guide.setText("After install, Sreon appears in Applications / Start Menu / Applications menu. No Terminal needed. First launch may need Control-click → Open.")
        content.addWidget(self.guide)

        outer.addLayout(content)

        self.installed_path = None
        self.worker = None
        self.dot_timer = QTimer(self)
        self.dot_timer.timeout.connect(self.tick_dot)
        self.dot_idx = 0

    def tick_dot(self):
        dots = ["⠋","⠙","⠹","⠸","⠼","⠴","⠦","⠧","⠇","⠏"]
        self.spinner.setText(dots[self.dot_idx % len(dots)])
        self.dot_idx += 1

    def start_install(self):
        self.install_btn.setEnabled(False)
        self.progress.setValue(5)
        self.status.setText("Installing...")
        self.spinner.setText("⠋")
        self.dot_timer.start(100)
        self.log.append("\n⟡ Starting installation…")
        self.worker = InstallWorker(self.mode)
        self.worker.progress.connect(self.on_progress)
        self.worker.finished_ok.connect(self.on_ok)
        self.worker.finished_err.connect(self.on_err)
        self.worker.start()

    def on_progress(self, val, msg):
        self.progress.setValue(val)
        self.status.setText(msg)
        self.log.append(f"{val}%  {msg}")

    def on_ok(self, path):
        self.dot_timer.stop()
        self.spinner.setText("✓")
        self.installed_path = path
        self.progress.setValue(100)
        self.status.setText(f"Installed to {path}")
        self.log.append(f"\n✓ Installed to {path}\nSreon now appears in Applications / Start Menu. Click Open Sreon below.")
        self.open_btn.setEnabled(True)
        self.install_btn.setText("Reinstall")
        self.install_btn.setEnabled(True)
        self.guide.setText(f"✓ Installed! Open from {path}. If macOS says unverified: Control-click → Open → Open, or System Settings → Privacy & Security → Open Anyway. Guide in If-it-says-unverified.txt")

    def on_err(self, err):
        self.dot_timer.stop()
        self.spinner.setText("✗")
        self.status.setText("Failed — see guide below")
        self.log.append(f"\n✗ Failed: {err}\n\nMinimal guide:\nMac DMG won't open: Control-click DMG → Open, or xattr -dr com.apple.quarantine ~/Downloads/Sreon.dmg, or hdiutil attach ~/Downloads/Sreon.dmg -noverify\nMac app unverified: Control-click /Applications/Sreon → Open → Open, or System Settings → Privacy → Open Anyway, or xattr -dr com.apple.quarantine /Applications/Sreon.app\nWindows SmartScreen: More info → Run anyway, or Right-click → Properties → Unblock\nLinux: chmod +x Sreon.AppImage, or sudo dpkg -i sreon.deb\nFull guide: If-it-says-unverified.txt and HOW-IT-WORKS.md")
        self.install_btn.setEnabled(True)

    def open_app(self):
        if not self.installed_path:
            return
        p = Path(self.installed_path)
        try:
            if self.mode == "mac":
                subprocess.Popen(["open", str(p)])
            elif self.mode == "win":
                exe = p / "Sreon.exe"
                if exe.exists():
                    subprocess.Popen([str(exe)], cwd=str(p))
            else:
                exe = p / "Sreon"
                if exe.exists():
                    subprocess.Popen([str(exe)], cwd=str(p))
        except Exception as e:
            self.log.append(f"Could not open: {e}")


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["mac", "win", "linux"], default=None)
    args = parser.parse_args()
    if args.mode:
        mode = args.mode
    else:
        sysname = platform.system().lower()
        if "darwin" in sysname:
            mode = "mac"
        elif "windows" in sysname:
            mode = "win"
        else:
            mode = "linux"
    app = QApplication(sys.argv)
    w = InstallerWindow(mode)
    w.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
