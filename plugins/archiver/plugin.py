"""Archive extraction, packing, and content listing."""
from __future__ import annotations

import shlex
import shutil
import subprocess
from pathlib import Path

from PySide6.QtCore import QThread, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from core.event_bus import bus
from core.logger import get_logger
from core.plugin_manager import BasePlugin

log = get_logger("plugin.archiver")

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
SEVENZ_DIR = ROOT_DIR / "7z"


def _find_7z() -> str:
    candidates = [
        SEVENZ_DIR / "7za",
        SEVENZ_DIR / "7z.exe",
        Path("/usr/bin/7za"),
        Path("/usr/bin/7z"),
    ]
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    return shutil.which("7za") or shutil.which("7z") or "7z"


BIN_7Z = _find_7z()


def _display_cmd(args: list[str]) -> str:
    return shlex.join(args)


class _Worker(QThread):
    line = Signal(str)
    done = Signal(int)

    def __init__(self, args: list[str]):
        super().__init__()
        self.args = args

    def run(self) -> None:
        try:
            process = subprocess.Popen(
                self.args,
                shell=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )
            assert process.stdout is not None
            for line in process.stdout:
                self.line.emit(line.rstrip())
            process.wait()
            self.done.emit(process.returncode)
        except OSError as exc:
            self.line.emit(f"[ERR] {exc}")
            self.done.emit(1)


class ArchiverWidget(QWidget):
    def __init__(self):
        super().__init__()
        vbox = QVBoxLayout(self)

        binary_available = Path(BIN_7Z).exists() or shutil.which(BIN_7Z)
        status = f"7z binary: {BIN_7Z}" if binary_available else "7z not found"
        vbox.addWidget(QLabel(status))

        extract_group = QGroupBox("Extract Archive")
        extract_layout = QVBoxLayout(extract_group)
        row = QHBoxLayout()
        row.addWidget(QLabel("Archive:"))
        self.ex_src = QLineEdit()
        row.addWidget(self.ex_src)
        browse = QPushButton("...")
        browse.clicked.connect(
            lambda: self._pick(
                self.ex_src, "Archives (*.zip *.7z *.tar *.apk *.jar *.rar)"
            )
        )
        row.addWidget(browse)
        extract_layout.addLayout(row)

        row = QHBoxLayout()
        row.addWidget(QLabel("Output dir:"))
        self.ex_dst = QLineEdit()
        row.addWidget(self.ex_dst)
        browse = QPushButton("...")
        browse.clicked.connect(lambda: self._pick_dir(self.ex_dst))
        row.addWidget(browse)
        extract_layout.addLayout(row)

        extract_button = QPushButton("Extract")
        extract_button.clicked.connect(self.do_extract)
        extract_layout.addWidget(extract_button)
        vbox.addWidget(extract_group)

        pack_group = QGroupBox("Pack Archive")
        pack_layout = QVBoxLayout(pack_group)
        row = QHBoxLayout()
        row.addWidget(QLabel("Source dir:"))
        self.pk_src = QLineEdit()
        row.addWidget(self.pk_src)
        browse = QPushButton("...")
        browse.clicked.connect(lambda: self._pick_dir(self.pk_src))
        row.addWidget(browse)
        pack_layout.addLayout(row)

        row = QHBoxLayout()
        row.addWidget(QLabel("Output file:"))
        self.pk_dst = QLineEdit()
        row.addWidget(self.pk_dst)
        pack_layout.addLayout(row)

        row = QHBoxLayout()
        row.addWidget(QLabel("Format:"))
        self.fmt = QComboBox()
        self.fmt.addItems(["zip", "7z", "tar"])
        row.addWidget(self.fmt)
        row.addStretch()
        pack_layout.addLayout(row)

        pack_button = QPushButton("Pack")
        pack_button.clicked.connect(self.do_pack)
        pack_layout.addWidget(pack_button)
        vbox.addWidget(pack_group)

        list_group = QGroupBox("List Contents")
        list_layout = QHBoxLayout(list_group)
        self.ls_path = QLineEdit()
        list_layout.addWidget(self.ls_path)
        browse = QPushButton("...")
        browse.clicked.connect(
            lambda: self._pick(self.ls_path, "Archives (*.zip *.7z *.apk *.jar)")
        )
        list_layout.addWidget(browse)
        list_button = QPushButton("List")
        list_button.clicked.connect(self.do_list)
        list_layout.addWidget(list_button)
        vbox.addWidget(list_group)

        self.console = QPlainTextEdit()
        self.console.setReadOnly(True)
        self.console.setFont(QFont("Monospace", 9))
        vbox.addWidget(self.console)

        clear_button = QPushButton("Clear Output")
        clear_button.clicked.connect(self.console.clear)
        vbox.addWidget(clear_button)

        self._workers: list[_Worker] = []

    def _pick(self, target: QLineEdit, file_filter: str) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Select", str(ROOT_DIR), file_filter
        )
        if path:
            target.setText(path)

    def _pick_dir(self, target: QLineEdit) -> None:
        path = QFileDialog.getExistingDirectory(self, "Select folder", str(ROOT_DIR))
        if path:
            target.setText(path)

    def _run(self, args: list[str], event_name: str, payload: dict) -> None:
        display = _display_cmd(args)
        self.console.appendPlainText(f"\n$ {display}")
        log.info("[ARCHIVER] %s", display)
        bus.emit("archive.start", {"cmd": display}, source="archiver")

        worker = _Worker(args)
        worker.line.connect(self.console.appendPlainText)

        def on_done(return_code: int) -> None:
            self.console.appendPlainText(f"[exit {return_code}]")
            bus.emit(
                event_name,
                {**payload, "rc": return_code},
                source="archiver",
            )
            try:
                self._workers.remove(worker)
            except ValueError:
                pass
            worker.deleteLater()

        worker.done.connect(on_done)
        self._workers.append(worker)
        worker.start()

    def do_extract(self) -> None:
        source = Path(self.ex_src.text().strip()).expanduser()
        if not source.is_file():
            self.console.appendPlainText("[!] Select an existing archive")
            return

        requested = self.ex_dst.text().strip()
        destination = (
            Path(requested).expanduser()
            if requested
            else source.parent / f"{source.stem}_extracted"
        )
        args = [BIN_7Z, "x", str(source), f"-o{destination}", "-y"]
        self._run(
            args,
            "archive.extracted",
            {"src": str(source), "dst": str(destination)},
        )

    def do_pack(self) -> None:
        source = Path(self.pk_src.text().strip()).expanduser()
        destination_text = self.pk_dst.text().strip()
        if not source.is_dir() or not destination_text:
            self.console.appendPlainText(
                "[!] Existing source directory and output are required"
            )
            return

        destination = Path(destination_text).expanduser()
        fmt = self.fmt.currentText()
        args = [
            BIN_7Z,
            "a",
            f"-t{fmt}",
            str(destination),
            str(source / "*"),
            "-y",
        ]
        self._run(
            args,
            "archive.packed",
            {"src": str(source), "dst": str(destination)},
        )

    def do_list(self) -> None:
        path = Path(self.ls_path.text().strip()).expanduser()
        if not path.is_file():
            self.console.appendPlainText("[!] Select an existing archive")
            return
        self._run([BIN_7Z, "l", str(path)], "archive.listed", {"path": str(path)})


class ArchiverPlugin(BasePlugin):
    def __init__(self):
        super().__init__()
        self.name = "Archiver"
        self.description = "Archive extraction, packing, and inspection."
        self.widget = None

    def initialize(self, main_window) -> None:
        self.widget = ArchiverWidget()
        main_window.add_plugin_dock("Archiver", self.widget)

    def shutdown(self) -> None:
        if self.widget:
            for worker in list(self.widget._workers):
                worker.requestInterruption()
        self.widget = None
