"""
Analysis Plugin — TypeLibs & SigLibs browser with metadata indexer.
Subscribes to: file.opened  → auto-suggest relevant libs.
Publishes:     analysis.lib_selected, analysis.lib_loaded
"""
import os
from pathlib import Path
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QSplitter,
    QListWidget, QListWidgetItem, QPlainTextEdit, QLabel,
    QComboBox, QLineEdit, QPushButton, QGroupBox
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont
from core.plugin_manager import BasePlugin
from core.event_bus import bus
from core.logger import get_logger

log = get_logger("plugin.analysis")

ROOT_DIR    = Path(__file__).resolve().parent.parent.parent
TYPELIBS    = ROOT_DIR / "typelibs"
SIGLIBS     = ROOT_DIR / "siglibs"

# Extension → human description
_EXT_INFO = {
    ".typelib":  "JEB Type Library — contains type/struct definitions for binary analysis",
    ".siglib":   "JEB Signature Library — contains function signature patterns",
    ".h":        "C/C++ header — additional type definitions",
    ".tld.yml":  "Type Library Descriptor — YAML manifest for typelib",
    ".txt":      "Text reference file",
}


def _ext(p: Path) -> str:
    return "".join(p.suffixes) or p.suffix


class AnalysisWidget(QWidget):
    def __init__(self):
        super().__init__()
        vbox = QVBoxLayout(self)

        # Mode selector
        row = QHBoxLayout()
        self.mode = QComboBox()
        self.mode.addItems(["TypeLibs", "SigLibs"])
        self.mode.currentTextChanged.connect(self._load_list)
        row.addWidget(QLabel("Library Set:")); row.addWidget(self.mode)

        # Search
        self.search = QLineEdit(); self.search.setPlaceholderText("Filter by name…")
        self.search.textChanged.connect(self._apply_filter)
        row.addWidget(self.search); row.addStretch()
        vbox.addLayout(row)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        # Left list
        left = QWidget(); lv = QVBoxLayout(left)
        self.lib_list = QListWidget()
        self.lib_list.itemClicked.connect(self._on_select)
        lv.addWidget(QLabel("Available Libraries:")); lv.addWidget(self.lib_list)
        splitter.addWidget(left)

        # Right detail pane
        right = QWidget(); rv = QVBoxLayout(right)
        self.detail_label = QLabel("Select a library to inspect")
        self.detail_label.setWordWrap(True)
        rv.addWidget(self.detail_label)
        self.detail_view = QPlainTextEdit()
        self.detail_view.setReadOnly(True)
        self.detail_view.setFont(QFont("Monospace", 9))
        rv.addWidget(self.detail_view)

        grp = QGroupBox("Load into JEB")
        gv = QHBoxLayout(grp)
        self.load_btn = QPushButton("📥 Load selected lib in JEB")
        self.load_btn.clicked.connect(self._load_in_jeb)
        gv.addWidget(self.load_btn)
        rv.addWidget(grp)
        splitter.addWidget(right)
        splitter.setSizes([270, 560])

        vbox.addWidget(splitter)

        self._all: list[Path] = []
        self._load_list("TypeLibs")

    # ── Data loading ─────────────────────────────────────────────────
    def _load_list(self, mode: str | None = None):
        if mode is None:
            mode = self.mode.currentText()
        base = TYPELIBS if mode == "TypeLibs" else SIGLIBS
        self._all = sorted(base.rglob("*") if base.exists() else [])
        self._all = [p for p in self._all if p.is_file()]
        self._apply_filter(self.search.text())

    def _apply_filter(self, text: str):
        self.lib_list.clear()
        for p in self._all:
            if text.lower() in p.name.lower():
                item = QListWidgetItem(p.name)
                item.setData(Qt.ItemDataRole.UserRole, str(p))
                item.setToolTip(str(p.relative_to(ROOT_DIR)))
                self.lib_list.addItem(item)

    def _on_select(self, item: QListWidgetItem):
        path = Path(item.data(Qt.ItemDataRole.UserRole))
        ext  = _ext(path)
        desc = _EXT_INFO.get(ext, f"Binary/data file  [{ext}]")
        size = path.stat().st_size
        rel  = path.relative_to(ROOT_DIR)

        info_lines = [
            f"Name:      {path.name}",
            f"Path:      {rel}",
            f"Size:      {size:,} bytes  ({size/1024:.1f} KB)",
            f"Type:      {desc}",
        ]

        # Try reading partial text
        preview = ""
        if ext in (".txt", ".h", ".tld.yml", ".TXT", ".md"):
            try:
                preview = "\n--- Preview (first 3 KB) ---\n" + \
                          path.read_text(errors="replace")[:3072]
            except Exception:
                pass

        self.detail_label.setText(desc)
        self.detail_view.setPlainText("\n".join(info_lines) + preview)

        bus.emit("analysis.lib_selected",
                 {"name": path.name, "path": str(path), "type": ext},
                 source="analysis")
        log.info("[ANALYSIS] selected: %s", path.name)

    def _load_in_jeb(self):
        sel = self.lib_list.currentItem()
        if not sel:
            return
        path = Path(sel.data(Qt.ItemDataRole.UserRole))
        jeb  = ROOT_DIR / "jar" / "jeb.jar"
        if not jeb.exists():
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.warning(self, "Not found", "jeb.jar not in jar/")
            return
        import subprocess
        subprocess.Popen(f'java -jar "{jeb}"', shell=True)
        bus.emit("analysis.lib_loaded", {"lib": str(path)}, source="analysis")
        log.info("[ANALYSIS] opened JEB for %s", path.name)


class AnalysisPlugin(BasePlugin):
    def __init__(self):
        super().__init__()
        self.name        = "Analysis"
        self.description = "TypeLibs / SigLibs browser and JEB integration."
        self.widget      = None

    def activate(self):
        # React when another plugin opens a file
        bus.subscribe("file.opened", self._on_file_opened, priority=80)

    def _on_file_opened(self, event):
        path = event.payload.get("path", "")
        log.debug("[ANALYSIS] file.opened event: %s — suggesting libs", path)

    def initialize(self, main_window):
        self.widget = AnalysisWidget()
        main_window.add_plugin_dock("Analysis", self.widget)
        log.info("Analysis plugin attached to GUI")

    def shutdown(self):
        bus.unsubscribe("file.opened", self._on_file_opened)
        self.widget = None
