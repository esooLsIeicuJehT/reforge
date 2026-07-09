"""
RE Toolkit Plugin – ADB Console, Command Reference, Script Runner, TypeLibs/SigLibs Browser
Integrates: adb/, batch/, commands/, scripts/, python scripts/, typelibs/, siglibs/
"""

import os, subprocess
from pathlib import Path
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QTabWidget, QTextEdit, QLineEdit, QListWidget, QListWidgetItem,
    QGroupBox, QSplitter, QFileDialog, QComboBox, QMessageBox,
    QTreeWidget, QTreeWidgetItem, QPlainTextEdit
)
from PyQt6.QtCore import Qt, pyqtSignal, QThread, QProcess
from PyQt6.QtGui import QFont, QColor
from core.plugin_manager import BasePlugin
from core.logger import get_logger

logger = get_logger(__name__)

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
ADB_DIR  = ROOT_DIR / "adb"
CMD_DIR  = ROOT_DIR / "commands"
BATCH_DIR = ROOT_DIR / "batch"
SCRIPTS_DIR = ROOT_DIR / "scripts"
PYSCRIPTS_DIR = ROOT_DIR / "python scripts" / "samples"
TYPELIBS_DIR = ROOT_DIR / "typelibs"
SIGLIBS_DIR  = ROOT_DIR / "siglibs"
JAR_DIR = ROOT_DIR / "jar"

# Prefer bundled adb if present, else fall back to system adb
_bundled_adb = ADB_DIR / "adb"
ADB_BIN = str(_bundled_adb) if _bundled_adb.exists() else "adb"


# ---------------------------------------------------------------------------
# Async command runner thread
# ---------------------------------------------------------------------------
class CmdThread(QThread):
    output = pyqtSignal(str)
    done   = pyqtSignal(int)

    def __init__(self, cmd, env=None):
        super().__init__()
        self.cmd = cmd
        self.env = env

    def run(self):
        try:
            logger.info("[TERMINAL] command started: %s", self.cmd)
            proc = subprocess.Popen(
                self.cmd, shell=True, stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT, text=True, env=self.env
            )
            for line in proc.stdout:
                self.output.emit(line.rstrip())
            proc.wait()
            logger.info("[TERMINAL] command finished rc=%d: %s", proc.returncode, self.cmd)
            self.done.emit(proc.returncode)
        except Exception as e:
            logger.exception("[TERMINAL] command failed: %s", self.cmd)
            self.output.emit(f"[ERROR] {e}")
            self.done.emit(1)


# ---------------------------------------------------------------------------
# ADB / Fastboot Console Tab
# ---------------------------------------------------------------------------
class AdbConsoleTab(QWidget):
    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)

        # Device row
        dev_row = QHBoxLayout()
        dev_row.addWidget(QLabel("Device:"))
        self.device_combo = QComboBox()
        self.device_combo.setMinimumWidth(220)
        dev_row.addWidget(self.device_combo)
        self.refresh_btn = QPushButton("Refresh Devices")
        self.refresh_btn.clicked.connect(self.refresh_devices)
        dev_row.addWidget(self.refresh_btn)
        dev_row.addStretch()
        layout.addLayout(dev_row)

        # Quick-action buttons
        quick = QGroupBox("Quick Actions")
        qlay = QHBoxLayout(quick)
        for label, cmd in [
            ("Reboot",          "reboot"),
            ("Reboot Recovery", "reboot recovery"),
            ("Reboot Bootloader","reboot bootloader"),
            ("Logcat",          "logcat -d"),
            ("Package List",    "shell pm list packages"),
            ("Get Props",       "shell getprop"),
        ]:
            btn = QPushButton(label)
            btn.clicked.connect(lambda _, c=cmd: self.run_adb(c))
            qlay.addWidget(btn)
        layout.addWidget(quick)

        # Fastboot quick actions
        fb_group = QGroupBox("Fastboot Quick Actions")
        fblay = QHBoxLayout(fb_group)
        for label, cmd in [
            ("Devices",          "fastboot devices"),
            ("OEM Unlock",       "fastboot oem unlock"),
            ("OEM Lock",         "fastboot oem lock"),
            ("Reboot",           "fastboot reboot"),
            ("Get Unlock Ability","fastboot flashing get_unlock_ability"),
        ]:
            btn = QPushButton(label)
            btn.clicked.connect(lambda _, c=cmd: self.run_fastboot(c))
            fblay.addWidget(btn)
        layout.addWidget(fb_group)

        # Output
        self.output = QPlainTextEdit()
        self.output.setReadOnly(True)
        self.output.setFont(QFont("Monospace", 9))
        layout.addWidget(self.output)

        # Custom command row
        cmd_row = QHBoxLayout()
        self.mode_combo = QComboBox()
        self.mode_combo.addItems(["adb", "fastboot"])
        cmd_row.addWidget(self.mode_combo)
        self.cmd_input = QLineEdit()
        self.cmd_input.setPlaceholderText("e.g. shell ls /sdcard")
        self.cmd_input.returnPressed.connect(self.run_custom)
        cmd_row.addWidget(self.cmd_input)
        run_btn = QPushButton("Run")
        run_btn.clicked.connect(self.run_custom)
        cmd_row.addWidget(run_btn)
        clr_btn = QPushButton("Clear")
        clr_btn.clicked.connect(self.clear_output)
        cmd_row.addWidget(clr_btn)
        layout.addLayout(cmd_row)

        self.refresh_devices()

    def _adb(self, serial=None):
        s = self.device_combo.currentText().strip()
        if s and s != "No devices":
            return f'"{ADB_BIN}" -s {s.split()[0]}'
        return f'"{ADB_BIN}"'

    def refresh_devices(self):
        logger.info("[TERMINAL] refreshing adb devices")
        self.device_combo.clear()
        try:
            out = subprocess.check_output(f'"{ADB_BIN}" devices', shell=True, text=True, stderr=subprocess.STDOUT)
            devs = [l for l in out.splitlines()[1:] if l.strip() and "List" not in l]
            if devs:
                self.device_combo.addItems(devs)
            else:
                self.device_combo.addItem("No devices")
        except Exception as e:
            logger.exception("[TERMINAL] failed to refresh adb devices")
            self.device_combo.addItem("adb not found")

    def _run(self, cmd):
        self.output.appendPlainText(f"\n$ {cmd}")
        logger.info("[TERMINAL] run: %s", cmd)
        self._thread = CmdThread(cmd)
        self._thread.output.connect(self.output.appendPlainText)
        self._thread.done.connect(lambda rc, command=cmd: self._command_done(command, rc))
        self._thread.start()

    def _command_done(self, cmd, rc):
        self.output.appendPlainText(f"[exit {rc}]")
        if rc:
            logger.error("[TERMINAL] command exited rc=%d: %s", rc, cmd)
        else:
            logger.info("[TERMINAL] command exited rc=%d: %s", rc, cmd)

    def clear_output(self):
        logger.info("[TERMINAL] console cleared")
        self.output.clear()

    def run_adb(self, subcmd):
        self._run(f'{self._adb()} {subcmd}')

    def run_fastboot(self, subcmd):
        self._run(f'fastboot {subcmd}')

    def run_custom(self):
        txt = self.cmd_input.text().strip()
        if not txt:
            return
        if self.mode_combo.currentText() == "adb":
            self._run(f'{self._adb()} {txt}')
        else:
            self._run(f'fastboot {txt}')
        self.cmd_input.clear()


# ---------------------------------------------------------------------------
# Command Reference Tab
# ---------------------------------------------------------------------------
class CommandReferenceTab(QWidget):
    REFS = {
        "ADB":        "adb-commands-list.txt",
        "Fastboot":   "fastboot-commands-list.txt",
        "APKTool":    "apktool-commands-list.txt",
        "Smali":      "smali-commands-list.txt",
        "Baksmali":   "baksmali-commands-list.txt",
        "AAPT":       "aapt-commands-list.txt",
        "zipalign":   "zipalign-commands-list.txt",
        "signapk":    "signapk-commmands-list.txt",
        "Lang Codes": "Android-Language-codes.txt",
        "XML Chars":  "XML special characters.txt",
        "Readme":     "Readme.txt",
    }

    def __init__(self):
        super().__init__()
        layout = QHBoxLayout(self)
        self.list_widget = QListWidget()
        self.list_widget.setMaximumWidth(160)
        for name in self.REFS:
            self.list_widget.addItem(name)
        self.list_widget.currentTextChanged.connect(self.load_ref)
        layout.addWidget(self.list_widget)

        self.viewer = QPlainTextEdit()
        self.viewer.setReadOnly(True)
        self.viewer.setFont(QFont("Monospace", 9))
        layout.addWidget(self.viewer)

        self.list_widget.setCurrentRow(0)

    def load_ref(self, name):
        fname = self.REFS.get(name, "")
        path = CMD_DIR / fname
        if path.exists():
            self.viewer.setPlainText(path.read_text(errors="replace"))
        else:
            self.viewer.setPlainText(f"File not found: {path}")


# ---------------------------------------------------------------------------
# Batch Operations Tab
# ---------------------------------------------------------------------------
class BatchOpsTab(QWidget):
    BATCHES = [
        ("Decompile APK", "java -jar \"{apktool}\" d -f -o \"{out}\" \"{apk}\""),
        ("Compile APK",   "java -jar \"{apktool}\" b \"{src}\" -o \"{out}\""),
        ("Decompile JAR", "java -jar \"{jadx}\" \"{jar}\" -d \"{out}\""),
        ("Sign APK (uber)","java -jar \"{uber}\" --apks \"{apk}\" -o \"{out}\""),
        ("Sign (signapk)", "java -jar \"{signapk}\" \"{pem}\" \"{pk8}\" \"{apk}\" \"{out}\""),
        ("Smali → DEX",    "java -jar \"{smali}\" ass \"{src}\" -o \"{out}\""),
        ("DEX → Smali",    "java -jar \"{baksmali}\" d \"{apk}\" -o \"{out}\""),
        ("AAPT Dump Badging","aapt dump badging \"{apk}\""),
        ("zipalign",       "zipalign -v 4 \"{apk}\" \"{out}\""),
    ]

    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Select a batch operation – fields will be filled in automatically from the jar/ folder:"))

        self.op_combo = QComboBox()
        for name, _ in self.BATCHES:
            self.op_combo.addItem(name)
        self.op_combo.currentIndexChanged.connect(self.build_cmd)
        layout.addWidget(self.op_combo)

        # File pickers
        def row(label, attr, filt="All (*)"):
            hb = QHBoxLayout()
            hb.addWidget(QLabel(label))
            le = QLineEdit()
            le.setPlaceholderText("(optional)")
            setattr(self, attr, le)
            hb.addWidget(le)
            btn = QPushButton("…")
            btn.setMaximumWidth(32)
            btn.clicked.connect(lambda _, a=attr, f=filt: self._pick(a, f))
            hb.addWidget(btn)
            layout.addLayout(hb)

        row("Input APK/JAR:", "in_apk",  "APK/JAR (*.apk *.jar)")
        row("Source Dir:",    "in_src")
        row("Output Path:",   "out_path")

        self.cmd_preview = QLineEdit()
        self.cmd_preview.setFont(QFont("Monospace", 9))
        layout.addWidget(QLabel("Command preview:"))
        layout.addWidget(self.cmd_preview)

        run_btn = QPushButton("▶  Run Batch Op")
        run_btn.clicked.connect(self.run_batch)
        layout.addWidget(run_btn)

        self.output = QPlainTextEdit()
        self.output.setReadOnly(True)
        self.output.setFont(QFont("Monospace", 9))
        layout.addWidget(self.output)

        self.build_cmd()

    def _pick(self, attr, filt):
        path, _ = QFileDialog.getOpenFileName(self, "Select", str(ROOT_DIR), filt)
        if path:
            getattr(self, attr).setText(path)
        self.build_cmd()

    def _j(self, name):
        return str(JAR_DIR / name)

    def build_cmd(self):
        idx = self.op_combo.currentIndex()
        _, template = self.BATCHES[idx]
        subs = {
            "apktool":  self._j("apktool.jar"),
            "jadx":     self._j("jadx.jar"),
            "uber":     self._j("uber-apk-signer.jar"),
            "signapk":  self._j("signapk.jar"),
            "smali":    self._j("smali.jar"),
            "baksmali": self._j("baksmali.jar"),
            "pem":      str(CMD_DIR / "testkey.x509.pem"),
            "pk8":      str(CMD_DIR / "testkey.pk8"),
            "apk":      self.in_apk.text() or "<input.apk>",
            "jar":      self.in_apk.text() or "<input.jar>",
            "src":      self.in_src.text() or "<source_dir>",
            "out":      self.out_path.text() or "<output>",
        }
        try:
            self.cmd_preview.setText(template.format(**subs))
        except KeyError as e:
            self.cmd_preview.setText(f"Template error: {e}")

    def run_batch(self):
        cmd = self.cmd_preview.text().strip()
        if not cmd or "<" in cmd:
            QMessageBox.warning(self, "Incomplete", "Fill in all required paths first.")
            return
        self.output.appendPlainText(f"\n$ {cmd}")
        self._thread = CmdThread(cmd)
        self._thread.output.connect(self.output.appendPlainText)
        self._thread.done.connect(lambda rc: self.output.appendPlainText(f"[exit {rc}]"))
        self._thread.start()


# ---------------------------------------------------------------------------
# Script Browser Tab (JEB scripts + .DISABLED scripts)
# ---------------------------------------------------------------------------
class ScriptBrowserTab(QWidget):
    def __init__(self):
        super().__init__()
        layout = QHBoxLayout(self)
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # Left: file tree
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.addWidget(QLabel("Scripts (click to view):"))
        self.tree = QTreeWidget()
        self.tree.setHeaderLabel("File")
        self.tree.itemClicked.connect(self.load_script)
        ll.addWidget(self.tree)
        splitter.addWidget(left)

        # Right: viewer + run
        right = QWidget()
        rl = QVBoxLayout(right)
        self.script_path_label = QLabel("No file selected")
        rl.addWidget(self.script_path_label)
        self.viewer = QPlainTextEdit()
        self.viewer.setFont(QFont("Monospace", 9))
        self.viewer.setReadOnly(True)
        rl.addWidget(self.viewer)

        btn_row = QHBoxLayout()
        self.run_btn = QPushButton("▶  Run with python3")
        self.run_btn.clicked.connect(self.run_script)
        btn_row.addWidget(self.run_btn)
        self.open_jeb_btn = QPushButton("Open in JEB")
        self.open_jeb_btn.clicked.connect(self.open_in_jeb)
        btn_row.addWidget(self.open_jeb_btn)
        rl.addLayout(btn_row)

        self.output = QPlainTextEdit()
        self.output.setReadOnly(True)
        self.output.setFont(QFont("Monospace", 9))
        self.output.setMaximumHeight(180)
        rl.addWidget(self.output)
        splitter.addWidget(right)
        splitter.setSizes([240, 600])

        layout.addWidget(splitter)
        self._current_path = None
        self._populate_tree()

    def _populate_tree(self):
        self.tree.clear()
        for folder, label in [(PYSCRIPTS_DIR, "Python Scripts (JEB)"), (SCRIPTS_DIR, "Java/Py Scripts")]:
            parent = QTreeWidgetItem(self.tree, [label])
            parent.setExpanded(True)
            if folder.exists():
                for f in sorted(folder.iterdir()):
                    if f.is_file():
                        item = QTreeWidgetItem(parent, [f.name])
                        item.setData(0, Qt.ItemDataRole.UserRole, str(f))

    def load_script(self, item, col):
        path = item.data(0, Qt.ItemDataRole.UserRole)
        if not path:
            return
        self._current_path = Path(path)
        self.script_path_label.setText(str(self._current_path))
        try:
            self.viewer.setPlainText(self._current_path.read_text(errors="replace"))
        except Exception as e:
            self.viewer.setPlainText(f"Error reading: {e}")

    def run_script(self):
        if not self._current_path:
            return
        cmd = f'python3 "{self._current_path}"'
        self.output.appendPlainText(f"\n$ {cmd}")
        self._thread = CmdThread(cmd)
        self._thread.output.connect(self.output.appendPlainText)
        self._thread.done.connect(lambda rc: self.output.appendPlainText(f"[exit {rc}]"))
        self._thread.start()

    def open_in_jeb(self):
        jeb_jar = JAR_DIR / "jeb.jar"
        if not jeb_jar.exists():
            QMessageBox.warning(self, "Error", "jeb.jar not found in jar/")
            return
        subprocess.Popen(f'java -jar "{jeb_jar}"', shell=True)


# ---------------------------------------------------------------------------
# TypeLibs / SigLibs Browser Tab
# ---------------------------------------------------------------------------
class LibsBrowserTab(QWidget):
    def __init__(self):
        super().__init__()
        layout = QHBoxLayout(self)
        splitter = QSplitter(Qt.Orientation.Horizontal)

        left = QWidget()
        ll = QVBoxLayout(left)

        self.mode_combo = QComboBox()
        self.mode_combo.addItems(["TypeLibs", "SigLibs"])
        self.mode_combo.currentTextChanged.connect(self._populate)
        ll.addWidget(self.mode_combo)

        self.search = QLineEdit()
        self.search.setPlaceholderText("Filter…")
        self.search.textChanged.connect(self._filter)
        ll.addWidget(self.search)

        self.list = QListWidget()
        self.list.itemClicked.connect(self._show_info)
        ll.addWidget(self.list)
        ll.addWidget(QLabel("Click item for details"))

        splitter.addWidget(left)

        right = QWidget()
        rl = QVBoxLayout(right)
        rl.addWidget(QLabel("Library Info:"))
        self.info = QPlainTextEdit()
        self.info.setReadOnly(True)
        self.info.setFont(QFont("Monospace", 9))
        rl.addWidget(self.info)
        splitter.addWidget(right)
        splitter.setSizes([260, 500])
        layout.addWidget(splitter)

        self._all_items = []
        self._populate("TypeLibs")

    def _populate(self, mode=None):
        if mode is None:
            mode = self.mode_combo.currentText()
        base = TYPELIBS_DIR if mode == "TypeLibs" else SIGLIBS_DIR
        self._all_items = []
        if base.exists():
            for f in sorted(base.rglob("*")):
                if f.is_file():
                    self._all_items.append(f)
        self._filter(self.search.text())

    def _filter(self, text):
        self.list.clear()
        for f in self._all_items:
            if text.lower() in f.name.lower():
                item = QListWidgetItem(f.name)
                item.setData(Qt.ItemDataRole.UserRole, str(f))
                self.list.addItem(item)

    def _show_info(self, item):
        path = Path(item.data(Qt.ItemDataRole.UserRole))
        size = path.stat().st_size
        info = (
            f"Name:      {path.name}\n"
            f"Path:      {path}\n"
            f"Size:      {size:,} bytes\n"
            f"Extension: {path.suffix}\n"
        )
        # Try to read first few bytes for text files
        if path.suffix in (".txt", ".md", ".TXT", ".py"):
            try:
                info += "\n--- Preview ---\n" + path.read_text(errors="replace")[:2000]
            except Exception:
                pass
        self.info.setPlainText(info)


# ---------------------------------------------------------------------------
# Main Plugin Widget (tabbed)
# ---------------------------------------------------------------------------
class REToolkitWidget(QWidget):
    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        tabs = QTabWidget()
        tabs.addTab(AdbConsoleTab(),      "Terminal")
        tabs.addTab(CommandReferenceTab(),"📖 Command Reference")
        tabs.addTab(BatchOpsTab(),        "⚙️  Batch Ops")
        tabs.addTab(ScriptBrowserTab(),   "🐍 Script Browser")
        tabs.addTab(LibsBrowserTab(),     "📚 TypeLibs / SigLibs")
        layout.addWidget(tabs)


# ---------------------------------------------------------------------------
# Plugin Registration
# ---------------------------------------------------------------------------
class REToolkitPlugin(BasePlugin):
    def __init__(self):
        super().__init__()
        self.name = "RE Toolkit"
        self.description = "ADB console, command refs, batch ops, script browser, typelibs/siglibs."
        self.widget = None

    def initialize(self, main_window):
        self.widget = REToolkitWidget()
        main_window.add_plugin_dock(
            "RE Toolkit", self.widget
        )
        logger.info("RE Toolkit plugin initialized.")

    def shutdown(self):
        self.widget = None
