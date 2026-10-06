"""ADB and Fastboot device-management plugin."""
from __future__ import annotations

import os
import shlex
import shutil
import subprocess
from pathlib import Path

from PySide6.QtCore import QThread, QTimer, Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from core.event_bus import bus
from core.logger import get_logger
from core.plugin_manager import BasePlugin

log = get_logger("plugin.adb_device")

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
ADB_DIR = ROOT_DIR / "adb"
_adb_bin = ADB_DIR / ("adb.exe" if os.name == "nt" else "adb")
ADB = str(_adb_bin) if _adb_bin.exists() else (shutil.which("adb") or "adb")
FASTBOOT = shutil.which("fastboot") or "fastboot"


def _split_args(text: str) -> list[str]:
    return shlex.split(text, posix=os.name != "nt")


def _display_cmd(args: list[str]) -> str:
    if os.name == "nt":
        return subprocess.list2cmdline(args)
    return shlex.join(args)


class _CmdWorker(QThread):
    line = Signal(str)
    done = Signal(int)

    def __init__(self, args: list[str]):
        super().__init__()
        self.args = args

    def run(self) -> None:
        try:
            log.info("[TERMINAL] command started: %s", _display_cmd(self.args))
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
            log.exception("[TERMINAL] command failed")
            self.line.emit(f"[ERR] {exc}")
            self.done.emit(1)


class AdbDeviceWidget(QWidget):
    def __init__(self):
        super().__init__()
        vbox = QVBoxLayout(self)

        header = QHBoxLayout()
        header.addWidget(QLabel("Device:"))
        self.dev_combo = QComboBox()
        self.dev_combo.setMinimumWidth(230)
        header.addWidget(self.dev_combo)
        refresh_button = QPushButton("Refresh")
        refresh_button.clicked.connect(self.refresh)
        header.addWidget(refresh_button)
        header.addStretch()
        vbox.addLayout(header)

        tabs = QTabWidget()
        tabs.addTab(self._adb_tab(), "ADB")
        tabs.addTab(self._fastboot_tab(), "Fastboot")
        vbox.addWidget(tabs)

        self.console = QPlainTextEdit()
        self.console.setReadOnly(True)
        self.console.setFont(QFont("Monospace", 9))
        vbox.addWidget(self.console)

        row = QHBoxLayout()
        self.mode = QComboBox()
        self.mode.addItems(["adb", "fastboot"])
        self.entry = QLineEdit()
        self.entry.setPlaceholderText("shell ls /sdcard")
        self.entry.returnPressed.connect(self.run_custom)
        run_button = QPushButton("Run")
        run_button.clicked.connect(self.run_custom)
        clear_button = QPushButton("Clear")
        clear_button.clicked.connect(self.console.clear)
        for widget in (self.mode, self.entry, run_button, clear_button):
            row.addWidget(widget)
        vbox.addLayout(row)

        self._workers: list[_CmdWorker] = []
        self._known: set[str] = set()
        self.refresh()

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._poll_devices)
        self._timer.start(5000)
        bus.subscribe("adb.run_command", self._on_bus_command)

    def _adb_tab(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        group = QGroupBox("Quick Actions")
        group_layout = QHBoxLayout(group)
        actions = [
            ("Devices", "devices"),
            ("Logcat (dump)", "logcat -d"),
            ("Package list", "shell pm list packages"),
            ("Get props", "shell getprop"),
            ("Reboot", "reboot"),
            ("Reboot Recovery", "reboot recovery"),
            ("Reboot Bootloader", "reboot bootloader"),
            ("Install APK", None),
        ]
        for label, command in actions:
            button = QPushButton(label)
            if command:
                button.clicked.connect(lambda _, value=command: self._adb(value))
            else:
                button.clicked.connect(self._install_apk)
            group_layout.addWidget(button)
        layout.addWidget(group)
        return widget

    def _fastboot_tab(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        group = QGroupBox("Fastboot Actions")
        group_layout = QHBoxLayout(group)
        actions = [
            ("Devices", "devices"),
            ("Get Var all", "getvar all"),
            ("OEM Unlock", "oem unlock"),
            ("OEM Lock", "oem lock"),
            ("Get Unlock Ability", "flashing get_unlock_ability"),
            ("Reboot", "reboot"),
        ]
        for label, command in actions:
            button = QPushButton(label)
            button.clicked.connect(
                lambda _, value=command, title=label: self._fastboot(value, title)
            )
            group_layout.addWidget(button)
        layout.addWidget(group)
        return widget

    def _serial(self) -> str | None:
        text = self.dev_combo.currentText().strip()
        if text and text not in {"No devices found", "adb unavailable"}:
            return text.split()[0]
        return None

    def _adb_args(self, subcommand: str) -> list[str]:
        args = [ADB]
        serial = self._serial()
        if serial:
            args.extend(["-s", serial])
        args.extend(_split_args(subcommand))
        return args

    def _adb(self, subcommand: str) -> None:
        self._run(self._adb_args(subcommand))

    def _fastboot(self, subcommand: str, label: str = "Fastboot") -> None:
        if subcommand in {"oem unlock", "oem lock"}:
            result = QMessageBox.question(
                self,
                "Confirm device state change",
                f"{label} can erase data or change boot security. Continue?",
            )
            if result != QMessageBox.StandardButton.Yes:
                return
        self._run([FASTBOOT, *_split_args(subcommand)])

    def _run(self, args: list[str]) -> None:
        display = _display_cmd(args)
        self.console.appendPlainText(f"\n$ {display}")
        bus.emit("adb.command", {"cmd": display}, source="adb_device")

        worker = _CmdWorker(args)
        worker.line.connect(self.console.appendPlainText)

        def on_done(return_code: int) -> None:
            self.console.appendPlainText(f"[exit {return_code}]")
            if return_code:
                log.error("[TERMINAL] command exited rc=%d: %s", return_code, display)
            try:
                self._workers.remove(worker)
            except ValueError:
                pass
            worker.deleteLater()

        worker.done.connect(on_done)
        self._workers.append(worker)
        worker.start()

    def _install_apk(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Select APK", str(ROOT_DIR), "APK (*.apk)")
        if path:
            args = [ADB]
            serial = self._serial()
            if serial:
                args.extend(["-s", serial])
            args.extend(["install", "-r", path])
            self._run(args)

    def run_custom(self) -> None:
        text = self.entry.text().strip()
        if not text:
            return
        try:
            if self.mode.currentText() == "adb":
                self._run(self._adb_args(text))
            else:
                self._run([FASTBOOT, *_split_args(text)])
        except ValueError as exc:
            self.console.appendPlainText(f"[ERR] Could not parse command: {exc}")
            return
        self.entry.clear()

    def refresh(self) -> None:
        self.dev_combo.clear()
        try:
            output = subprocess.check_output(
                [ADB, "devices"],
                shell=False,
                text=True,
                stderr=subprocess.STDOUT,
                timeout=5,
            )
            devices = [line for line in output.splitlines()[1:] if line.strip()]
            self.dev_combo.addItems(devices or ["No devices found"])
        except (OSError, subprocess.SubprocessError):
            log.exception("Failed to refresh ADB devices")
            self.dev_combo.addItem("adb unavailable")

    def _poll_devices(self) -> None:
        try:
            output = subprocess.check_output(
                [ADB, "devices"],
                shell=False,
                text=True,
                stderr=subprocess.DEVNULL,
                timeout=3,
            )
            current = {
                line.split()[0]
                for line in output.splitlines()[1:]
                if line.strip() and len(line.split()) >= 2
            }
        except (OSError, subprocess.SubprocessError):
            return

        for serial in current - self._known:
            bus.emit("device.connected", {"serial": serial}, source="adb_device")
        for serial in self._known - current:
            bus.emit("device.disconnected", {"serial": serial}, source="adb_device")
        self._known = current

    def _on_bus_command(self, event) -> None:
        command = event.payload.get("cmd", "")
        if command:
            self._adb(command)


class ADBDevicePlugin(BasePlugin):
    def __init__(self):
        super().__init__()
        self.name = "ADB Device"
        self.description = "ADB and Fastboot device manager."
        self.widget = None

    def initialize(self, main_window) -> None:
        self.widget = AdbDeviceWidget()
        main_window.add_plugin_dock(
            "ADB Device",
            self.widget,
            area=Qt.DockWidgetArea.LeftDockWidgetArea,
        )

    def shutdown(self) -> None:
        if self.widget:
            bus.unsubscribe("adb.run_command", self.widget._on_bus_command)
            self.widget._timer.stop()
        self.widget = None
