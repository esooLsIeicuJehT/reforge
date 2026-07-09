"""
ADB Device Plugin
—————————————————
Full-featured ADB/Fastboot GUI panel.
Publishes bus events:  device.connected, device.disconnected, adb.command
Subscribes to:         adb.run_command
"""
import subprocess, threading
from pathlib import Path
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QComboBox,
    QPlainTextEdit, QLineEdit, QGroupBox, QTabWidget
)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QThread, QObject
from PyQt6.QtGui import QFont
from core.plugin_manager import BasePlugin
from core.event_bus import bus
from core.logger import get_logger

log = get_logger("plugin.adb_device")

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
ADB_DIR  = ROOT_DIR / "adb"
_adb_bin = ADB_DIR / "adb"
ADB      = str(_adb_bin) if _adb_bin.exists() else "adb"


# ── Async runner ──────────────────────────────────────────────────────
class _CmdWorker(QThread):
    line  = pyqtSignal(str)
    done  = pyqtSignal(int)

    def __init__(self, cmd): super().__init__(); self.cmd = cmd
    def run(self):
        try:
            log.info("[TERMINAL] command started: %s", self.cmd)
            p = subprocess.Popen(self.cmd, shell=True, stdout=subprocess.PIPE,
                                 stderr=subprocess.STDOUT, text=True)
            for ln in p.stdout: self.line.emit(ln.rstrip())
            p.wait()
            log.info("[TERMINAL] command finished rc=%d: %s", p.returncode, self.cmd)
            self.done.emit(p.returncode)
        except Exception as e:
            log.exception("[TERMINAL] command failed: %s", self.cmd)
            self.line.emit(f"[ERR] {e}"); self.done.emit(1)


# ── Main widget ───────────────────────────────────────────────────────
class AdbDeviceWidget(QWidget):
    def __init__(self):
        super().__init__()
        vbox = QVBoxLayout(self)

        # Header / device selector
        hdr = QHBoxLayout()
        hdr.addWidget(QLabel("Device:"))
        self.dev_combo = QComboBox(); self.dev_combo.setMinimumWidth(230)
        hdr.addWidget(self.dev_combo)
        ref = QPushButton("⟳ Refresh"); ref.clicked.connect(self.refresh)
        hdr.addWidget(ref); hdr.addStretch()
        vbox.addLayout(hdr)

        # Tabs: terminal actions
        tabs = QTabWidget()
        tabs.addTab(self._adb_tab(),      "ADB")
        tabs.addTab(self._fastboot_tab(), "Fastboot")
        vbox.addWidget(tabs)

        # Shared output console
        self.console = QPlainTextEdit()
        self.console.setReadOnly(True)
        self.console.setFont(QFont("Monospace", 9))
        vbox.addWidget(self.console)

        # Custom command bar
        row = QHBoxLayout()
        self.mode  = QComboBox(); self.mode.addItems(["adb", "fastboot"])
        self.entry = QLineEdit(); self.entry.setPlaceholderText("shell ls /sdcard")
        self.entry.returnPressed.connect(self.run_custom)
        run = QPushButton("▶ Run"); run.clicked.connect(self.run_custom)
        clr = QPushButton("Clear"); clr.clicked.connect(self.clear_console)
        for w in [self.mode, self.entry, run, clr]: row.addWidget(w)
        vbox.addLayout(row)

        self._workers = []
        self.refresh()

        # Poll devices every 5 s
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._poll_devices)
        self._timer.start(5000)
        self._known = set()

        # Subscribe to bus command requests
        bus.subscribe("adb.run_command", self._on_bus_command)

    # ── Tabs ──────────────────────────────────────────────────────────
    def _adb_tab(self):
        w = QWidget(); v = QVBoxLayout(w)
        grp = QGroupBox("Quick Actions"); g = QHBoxLayout(grp)
        for label, sub in [
            ("Devices",          "devices"),
            ("Logcat (dump)",    "logcat -d"),
            ("Package list",     "shell pm list packages"),
            ("Get props",        "shell getprop"),
            ("Reboot",           "reboot"),
            ("Reboot Recovery",  "reboot recovery"),
            ("Reboot Bootloader","reboot bootloader"),
            ("Install APK",      None),
        ]:
            btn = QPushButton(label)
            if sub:
                btn.clicked.connect(lambda _, s=sub: self._adb(s))
            else:
                btn.clicked.connect(self._install_apk)
            g.addWidget(btn)
        v.addWidget(grp)
        return w

    def _fastboot_tab(self):
        w = QWidget(); v = QVBoxLayout(w)
        grp = QGroupBox("Fastboot Actions"); g = QHBoxLayout(grp)
        for label, sub in [
            ("Devices",           "fastboot devices"),
            ("Get Var all",       "fastboot getvar all"),
            ("OEM Unlock",        "fastboot oem unlock"),
            ("OEM Lock",          "fastboot oem lock"),
            ("Get Unlock Ability","fastboot flashing get_unlock_ability"),
            ("Reboot",            "fastboot reboot"),
        ]:
            btn = QPushButton(label)
            btn.clicked.connect(lambda _, c=sub: self._run(c))
            g.addWidget(btn)
        v.addWidget(grp)
        return w

    # ── ADB helpers ───────────────────────────────────────────────────
    def _serial(self):
        txt = self.dev_combo.currentText().strip()
        if txt and txt != "No devices found":
            return txt.split()[0]
        return None

    def _adb(self, sub: str):
        s = self._serial()
        prefix = f'"{ADB}" -s {s}' if s else f'"{ADB}"'
        self._run(f"{prefix} {sub}")

    def _run(self, cmd: str):
        self.console.appendPlainText(f"\n$ {cmd}")
        log.info("[TERMINAL] run: %s", cmd)
        bus.emit("adb.command", {"cmd": cmd}, source="adb_device")
        w = _CmdWorker(cmd)
        w.line.connect(self.console.appendPlainText)
        w.done.connect(lambda rc, command=cmd: self._command_done(command, rc))
        self._workers.append(w); w.start()

    def _command_done(self, cmd: str, rc: int):
        self.console.appendPlainText(f"[exit {rc}]")
        if rc:
            log.error("[TERMINAL] command exited rc=%d: %s", rc, cmd)
        else:
            log.info("[TERMINAL] command exited rc=%d: %s", rc, cmd)

    def clear_console(self):
        log.info("[TERMINAL] console cleared")
        self.console.clear()

    def _install_apk(self):
        from PyQt6.QtWidgets import QFileDialog
        log.info("[TERMINAL] install APK dialog opened")
        path, _ = QFileDialog.getOpenFileName(self, "Select APK",
                                              str(ROOT_DIR / "apks"), "APK (*.apk)")
        if path:
            log.info("[TERMINAL] install APK selected: %s", path)
            self._adb(f'install -r "{path}"')
        else:
            log.info("[TERMINAL] install APK cancelled")

    def run_custom(self):
        txt = self.entry.text().strip()
        if not txt: return
        if self.mode.currentText() == "adb":
            self._adb(txt)
        else:
            self._run(f"fastboot {txt}")
        self.entry.clear()

    def refresh(self):
        log.info("[TERMINAL] refreshing adb devices")
        self.dev_combo.clear()
        try:
            out = subprocess.check_output(f'"{ADB}" devices', shell=True, text=True,
                                          stderr=subprocess.STDOUT, timeout=5)
            devs = [l for l in out.splitlines()[1:] if l.strip()]
            if devs:
                self.dev_combo.addItems(devs)
            else:
                self.dev_combo.addItem("No devices found")
        except Exception:
            log.exception("[TERMINAL] failed to refresh adb devices")
            self.dev_combo.addItem("adb unavailable")

    def _poll_devices(self):
        try:
            out = subprocess.check_output(f'"{ADB}" devices', shell=True,
                                          text=True, stderr=subprocess.DEVNULL, timeout=3)
            now = {l.split()[0] for l in out.splitlines()[1:] if l.strip()}
            for s in now - self._known:
                bus.emit("device.connected", {"serial": s}, source="adb_device")
                log.info("[ADB] device connected: %s", s)
            for s in self._known - now:
                bus.emit("device.disconnected", {"serial": s}, source="adb_device")
                log.info("[ADB] device disconnected: %s", s)
            self._known = now
        except Exception:
            pass

    def _on_bus_command(self, event):
        cmd = event.payload.get("cmd", "")
        if cmd: self._adb(cmd)


# ── Plugin class ──────────────────────────────────────────────────────
class ADBDevicePlugin(BasePlugin):
    def __init__(self):
        super().__init__()
        self.name        = "ADB Device"
        self.description = "ADB & Fastboot device manager with live polling."
        self.widget      = None

    def initialize(self, main_window):
        self.widget = AdbDeviceWidget()
        main_window.add_plugin_dock("ADB Device", self.widget,
                                    area=__import__("PyQt6.QtCore", fromlist=["Qt"]).Qt.DockWidgetArea.LeftDockWidgetArea)
        log.info("ADB Device plugin attached to GUI")

    def shutdown(self):
        if self.widget and hasattr(self.widget, "_timer"):
            self.widget._timer.stop()
        self.widget = None
