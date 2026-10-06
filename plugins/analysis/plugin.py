"""Analysis plugin: TypeLib/SigLib browser and JEB launcher."""
from __future__ import annotations

import subprocess
from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QComboBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from core.event_bus import bus
from core.logger import get_logger
from core.plugin_manager import BasePlugin

log = get_logger("plugin.analysis")

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
TYPELIBS = ROOT_DIR / "typelibs"
SIGLIBS = ROOT_DIR / "siglibs"

_EXT_INFO = {
    ".typelib": "JEB Type Library - type/struct definitions for binary analysis",
    ".siglib": "JEB Signature Library - function signature patterns",
    ".h": "C/C++ header - additional type definitions",
    ".tld.yml": "Type Library Descriptor - YAML manifest",
    ".txt": "Text reference file",
}


def _ext(path: Path) -> str:
    return "".join(path.suffixes) or path.suffix


class AnalysisWidget(QWidget):
    def __init__(self):
        super().__init__()
        vbox = QVBoxLayout(self)

        row = QHBoxLayout()
        self.mode = QComboBox()
        self.mode.addItems(["TypeLibs", "SigLibs"])
        self.mode.currentTextChanged.connect(self._load_list)
        row.addWidget(QLabel("Library Set:"))
        row.addWidget(self.mode)

        self.search = QLineEdit()
        self.search.setPlaceholderText("Filter by name...")
        self.search.textChanged.connect(self._apply_filter)
        row.addWidget(self.search)
        row.addStretch()
        vbox.addLayout(row)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        left = QWidget()
        left_layout = QVBoxLayout(left)
        self.lib_list = QListWidget()
        self.lib_list.itemClicked.connect(self._on_select)
        left_layout.addWidget(QLabel("Available Libraries:"))
        left_layout.addWidget(self.lib_list)
        splitter.addWidget(left)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        self.detail_label = QLabel("Select a library to inspect")
        self.detail_label.setWordWrap(True)
        right_layout.addWidget(self.detail_label)

        self.detail_view = QPlainTextEdit()
        self.detail_view.setReadOnly(True)
        self.detail_view.setFont(QFont("Monospace", 9))
        right_layout.addWidget(self.detail_view)

        group = QGroupBox("Open JEB")
        group_layout = QHBoxLayout(group)
        self.load_btn = QPushButton("Open JEB")
        self.load_btn.clicked.connect(self._load_in_jeb)
        group_layout.addWidget(self.load_btn)
        right_layout.addWidget(group)

        splitter.addWidget(right)
        splitter.setSizes([270, 560])
        vbox.addWidget(splitter)

        self._all: list[Path] = []
        self._load_list("TypeLibs")

    def _load_list(self, mode: str | None = None) -> None:
        mode = mode or self.mode.currentText()
        base = TYPELIBS if mode == "TypeLibs" else SIGLIBS
        self._all = sorted(
            path for path in (base.rglob("*") if base.exists() else []) if path.is_file()
        )
        self._apply_filter(self.search.text())

    def _apply_filter(self, text: str) -> None:
        self.lib_list.clear()
        needle = text.casefold()
        for path in self._all:
            if needle in path.name.casefold():
                item = QListWidgetItem(path.name)
                item.setData(Qt.ItemDataRole.UserRole, str(path))
                item.setToolTip(str(path.relative_to(ROOT_DIR)))
                self.lib_list.addItem(item)

    def _on_select(self, item: QListWidgetItem) -> None:
        path = Path(item.data(Qt.ItemDataRole.UserRole))
        try:
            size = path.stat().st_size
        except OSError as exc:
            QMessageBox.warning(self, "Read error", str(exc))
            return

        ext = _ext(path)
        desc = _EXT_INFO.get(ext, f"Binary/data file [{ext}]")
        info_lines = [
            f"Name:      {path.name}",
            f"Path:      {path.relative_to(ROOT_DIR)}",
            f"Size:      {size:,} bytes ({size / 1024:.1f} KB)",
            f"Type:      {desc}",
        ]

        preview = ""
        if ext.lower() in {".txt", ".h", ".tld.yml", ".md"}:
            try:
                preview = "\n--- Preview (first 3 KB) ---\n" + path.read_text(
                    encoding="utf-8", errors="replace"
                )[:3072]
            except OSError:
                log.exception("Could not preview %s", path)

        self.detail_label.setText(desc)
        self.detail_view.setPlainText("\n".join(info_lines) + preview)
        bus.emit(
            "analysis.lib_selected",
            {"name": path.name, "path": str(path), "type": ext},
            source="analysis",
        )

    def _load_in_jeb(self) -> None:
        selected = self.lib_list.currentItem()
        if not selected:
            return

        path = Path(selected.data(Qt.ItemDataRole.UserRole))
        jeb = ROOT_DIR / "jar" / "jeb.jar"
        if not jeb.exists():
            QMessageBox.warning(self, "Not found", "jeb.jar was not found in jar/.")
            return

        try:
            subprocess.Popen(["java", "-jar", str(jeb)], shell=False)
        except OSError as exc:
            QMessageBox.critical(self, "Launch failed", str(exc))
            log.exception("Failed to launch JEB")
            return

        bus.emit("analysis.lib_loaded", {"lib": str(path)}, source="analysis")
        log.info("[ANALYSIS] opened JEB for %s", path.name)


class AnalysisPlugin(BasePlugin):
    def __init__(self):
        super().__init__()
        self.name = "Analysis"
        self.description = "TypeLib/SigLib browser and JEB integration."
        self.widget = None

    def activate(self) -> None:
        bus.subscribe("file.opened", self._on_file_opened, priority=80)

    def _on_file_opened(self, event) -> None:
        path = event.payload.get("path", "")
        log.debug("[ANALYSIS] file.opened: %s", path)

    def initialize(self, main_window) -> None:
        self.widget = AnalysisWidget()
        main_window.add_plugin_dock("Analysis", self.widget)

    def shutdown(self) -> None:
        bus.unsubscribe("file.opened", self._on_file_opened)
        self.widget = None
