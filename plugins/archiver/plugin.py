"""
Archiver Plugin — 7z/zip/tar extraction + APK resource repackaging.
Wraps the bundled 7z/ binaries via subprocess.
Publishes: archive.extracted, archive.packed
"""
import subprocess, shutil
from pathlib import Path
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QLineEdit, QPlainTextEdit, QFileDialog, QGroupBox, QComboBox
)
from PyQt6.QtCore import QThread, pyqtSignal
from PyQt6.QtGui import QFont
from core.plugin_manager import BasePlugin
from core.event_bus import bus
from core.logger import get_logger

log = get_logger("plugin.archiver")

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
SEVENZ_DIR = ROOT_DIR / "7z"

# Resolve 7z binary: bundled linux 7za > system p7zip > system 7z
def _find_7z() -> str:
    for candidate in [
        SEVENZ_DIR / "7za",
        Path("/usr/bin/7za"),
        Path("/usr/bin/7z"),
    ]:
        if candidate.exists():
            return str(candidate)
    found = shutil.which("7za") or shutil.which("7z")
    return found or "7z"

BIN_7Z = _find_7z()


class _Worker(QThread):
    line = pyqtSignal(str)
    done = pyqtSignal(int)
    def __init__(self, cmd): super().__init__(); self.cmd = cmd
    def run(self):
        try:
            p = subprocess.Popen(self.cmd, shell=True, stdout=subprocess.PIPE,
                                 stderr=subprocess.STDOUT, text=True)
            for ln in p.stdout: self.line.emit(ln.rstrip())
            p.wait(); self.done.emit(p.returncode)
        except Exception as e: self.line.emit(f"[ERR] {e}"); self.done.emit(1)


class ArchiverWidget(QWidget):
    def __init__(self):
        super().__init__()
        vbox = QVBoxLayout(self)

        # 7z status
        status_txt = f"7z binary: {BIN_7Z}" if Path(BIN_7Z).exists() or shutil.which(BIN_7Z) \
                     else "⚠ 7z not found — install p7zip-full"
        vbox.addWidget(QLabel(status_txt))

        # ── Extract ────────────────────────────────────────────────
        ex_grp = QGroupBox("Extract Archive")
        ev = QVBoxLayout(ex_grp)
        er1 = QHBoxLayout()
        er1.addWidget(QLabel("Archive:"))
        self.ex_src = QLineEdit(); self.ex_src.setPlaceholderText("path/to/file.zip")
        er1.addWidget(self.ex_src)
        b1 = QPushButton("…"); b1.setMaximumWidth(30)
        b1.clicked.connect(lambda: self._pick(self.ex_src, "Archives (*.zip *.7z *.tar *.apk *.jar *.rar)"))
        er1.addWidget(b1); ev.addLayout(er1)

        er2 = QHBoxLayout()
        er2.addWidget(QLabel("Output dir:"))
        self.ex_dst = QLineEdit(); self.ex_dst.setPlaceholderText("destination folder")
        er2.addWidget(self.ex_dst)
        b2 = QPushButton("…"); b2.setMaximumWidth(30)
        b2.clicked.connect(lambda: self._pick_dir(self.ex_dst))
        er2.addWidget(b2); ev.addLayout(er2)

        ex_btn = QPushButton("📦 Extract"); ex_btn.clicked.connect(self.do_extract)
        ev.addWidget(ex_btn)
        vbox.addWidget(ex_grp)

        # ── Pack ───────────────────────────────────────────────────
        pk_grp = QGroupBox("Pack / Re-sign APK Resources")
        pv = QVBoxLayout(pk_grp)
        pr1 = QHBoxLayout()
        pr1.addWidget(QLabel("Source dir:"))
        self.pk_src = QLineEdit(); self.pk_src.setPlaceholderText("folder to compress")
        pr1.addWidget(self.pk_src)
        b3 = QPushButton("…"); b3.setMaximumWidth(30)
        b3.clicked.connect(lambda: self._pick_dir(self.pk_src))
        pr1.addWidget(b3); pv.addLayout(pr1)

        pr2 = QHBoxLayout()
        pr2.addWidget(QLabel("Output file:"))
        self.pk_dst = QLineEdit(); self.pk_dst.setPlaceholderText("out.zip / out.apk")
        pr2.addWidget(self.pk_dst); pv.addLayout(pr2)

        pr3 = QHBoxLayout()
        pr3.addWidget(QLabel("Format:"))
        self.fmt = QComboBox(); self.fmt.addItems(["zip", "7z", "tar"])
        pr3.addWidget(self.fmt); pr3.addStretch()
        pv.addLayout(pr3)

        pk_btn = QPushButton("🗜 Pack"); pk_btn.clicked.connect(self.do_pack)
        pv.addWidget(pk_btn)
        vbox.addWidget(pk_grp)

        # ── List contents ──────────────────────────────────────────
        ls_grp = QGroupBox("List Contents")
        lv = QVBoxLayout(ls_grp)
        lr = QHBoxLayout()
        self.ls_path = QLineEdit(); self.ls_path.setPlaceholderText("archive to inspect")
        lr.addWidget(self.ls_path)
        b4 = QPushButton("…"); b4.setMaximumWidth(30)
        b4.clicked.connect(lambda: self._pick(self.ls_path, "Archives (*.zip *.7z *.apk *.jar)"))
        lr.addWidget(b4)
        ls_btn = QPushButton("📋 List"); ls_btn.clicked.connect(self.do_list)
        lr.addWidget(ls_btn)
        lv.addLayout(lr); vbox.addWidget(ls_grp)

        # Output
        self.console = QPlainTextEdit()
        self.console.setReadOnly(True)
        self.console.setFont(QFont("Monospace", 9))
        vbox.addWidget(self.console)

        clr = QPushButton("✖ Clear Output"); clr.clicked.connect(self.console.clear)
        vbox.addWidget(clr)

        self._workers = []

    def _pick(self, target: QLineEdit, filt: str):
        p, _ = QFileDialog.getOpenFileName(self, "Select", str(ROOT_DIR), filt)
        if p: target.setText(p)

    def _pick_dir(self, target: QLineEdit):
        p = QFileDialog.getExistingDirectory(self, "Select folder", str(ROOT_DIR))
        if p: target.setText(p)

    def _run(self, cmd: str, event_name: str, payload: dict):
        self.console.appendPlainText(f"\n$ {cmd}")
        log.info("[ARCHIVER] %s", cmd)
        bus.emit(f"archive.start", {"cmd": cmd}, source="archiver")
        w = _Worker(cmd)
        w.line.connect(self.console.appendPlainText)
        def _on_done(rc):
            self.console.appendPlainText(f"[exit {rc}]")
            bus.emit(event_name, {**payload, "rc": rc}, source="archiver")
        w.done.connect(_on_done)
        self._workers.append(w); w.start()

    def do_extract(self):
        src = self.ex_src.text().strip()
        dst = self.ex_dst.text().strip()
        if not src:
            self.console.appendPlainText("[!] No archive selected"); return
        out_arg = f'-o"{dst}"' if dst else f'-o"{Path(src).parent / (Path(src).stem + "_extracted")}"'
        cmd = f'"{BIN_7Z}" x "{src}" {out_arg} -y'
        self._run(cmd, "archive.extracted", {"src": src})

    def do_pack(self):
        src = self.pk_src.text().strip()
        dst = self.pk_dst.text().strip()
        if not src or not dst:
            self.console.appendPlainText("[!] Source and output required"); return
        fmt = self.fmt.currentText()
        cmd = f'"{BIN_7Z}" a -t{fmt} "{dst}" "{src}/*" -y'
        self._run(cmd, "archive.packed", {"src": src, "dst": dst})

    def do_list(self):
        p = self.ls_path.text().strip()
        if not p:
            self.console.appendPlainText("[!] No archive selected"); return
        self._run(f'"{BIN_7Z}" l "{p}"', "archive.listed", {"path": p})


class ArchiverPlugin(BasePlugin):
    def __init__(self):
        super().__init__()
        self.name        = "Archiver"
        self.description = "7z/zip archive extraction, packing, and APK resource inspection."
        self.widget      = None

    def initialize(self, main_window):
        self.widget = ArchiverWidget()
        main_window.add_plugin_dock("Archiver", self.widget)
        log.info("Archiver plugin attached to GUI")

    def shutdown(self):
        self.widget = None
