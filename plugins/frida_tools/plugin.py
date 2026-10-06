"""Frida integration for authorized dynamic instrumentation workflows."""
from __future__ import annotations

import shlex
import shutil
import subprocess
import tempfile
from pathlib import Path

from PyQt6.QtCore import QThread, pyqtSignal
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QCheckBox,
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

log = get_logger("plugin.frida_tools")

FRIDA_BIN = shutil.which("frida")
FRIDA_PS_BIN = shutil.which("frida-ps")
FRIDA_AVAILABLE = bool(FRIDA_BIN and FRIDA_PS_BIN)
WORK_DIR = Path.home() / ".reforge" / "work"

TEMPLATES = {
    "Method Tracer": """\
// Replace com.example.ClassName with a class in software you are authorized to inspect.
var TargetClass = 'com.example.ClassName';
Java.perform(function() {
    var Clazz = Java.use(TargetClass);
    Clazz.$methods.forEach(function(m) {
        try {
            Clazz[m.name].overloads.forEach(function(overload) {
                overload.implementation = function() {
                    var args = Array.prototype.slice.call(arguments);
                    console.log('[TRACE] ' + TargetClass + '.' + m.name + '(' + JSON.stringify(args) + ')');
                    return overload.apply(this, arguments);
                };
            });
        } catch (e) {}
    });
    console.log('[+] Tracing methods in ' + TargetClass);
});
""",
    "Intent Logger": """\
Java.perform(function() {
    var Activity = Java.use('android.app.Activity');
    Activity.startActivity.overload('android.content.Intent').implementation = function(intent) {
        console.log('[INTENT] action=' + intent.getAction() + ' data=' + intent.getDataString());
        return this.startActivity(intent);
    };
});
""",
    "Blank Script": "// Authorized Frida script\nJava.perform(function() {\n\n});\n",
}


class _FridaWorker(QThread):
    line = pyqtSignal(str)
    done = pyqtSignal(int)

    def __init__(self, args: list[str]):
        super().__init__()
        self.args = args
        self._proc: subprocess.Popen[str] | None = None

    def run(self) -> None:
        try:
            self._proc = subprocess.Popen(
                self.args,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )
            if self._proc.stdout is not None:
                for line in self._proc.stdout:
                    self.line.emit(line.rstrip())
            self._proc.wait()
            self.done.emit(self._proc.returncode)
        except Exception as exc:
            log.exception("Frida command failed: %s", self.args)
            self.line.emit(f"[ERR] {exc}")
            self.done.emit(1)

    def stop(self) -> None:
        proc = self._proc
        if proc is None or proc.poll() is not None:
            return
        try:
            proc.terminate()
            proc.wait(timeout=1.5)
        except subprocess.TimeoutExpired:
            proc.kill()
        except Exception:
            log.exception("Failed to stop Frida process")


class FridaToolsWidget(QWidget):
    def __init__(self):
        super().__init__()
        vbox = QVBoxLayout(self)

        if not FRIDA_AVAILABLE:
            warn = QLabel(
                "⚠ frida and frida-ps were not found on PATH.\n"
                "Install frida-tools and configure an authorized Frida target before use."
            )
            warn.setStyleSheet("color: #ff9800; padding: 8px;")
            vbox.addWidget(warn)

        dev_group = QGroupBox("Target")
        dev_layout = QVBoxLayout(dev_group)

        serial_row = QHBoxLayout()
        serial_row.addWidget(QLabel("Device serial (blank = USB):"))
        self.serial = QLineEdit()
        self.serial.setPlaceholderText("emulator-5554")
        serial_row.addWidget(self.serial)
        dev_layout.addLayout(serial_row)

        target_row = QHBoxLayout()
        target_row.addWidget(QLabel("Package / process name / PID:"))
        self.pkg = QLineEdit()
        self.pkg.setPlaceholderText("com.example.app")
        target_row.addWidget(self.pkg)
        self.spawn_chk = QCheckBox("Spawn")
        self.spawn_chk.setChecked(True)
        target_row.addWidget(self.spawn_chk)
        dev_layout.addLayout(target_row)

        list_btn = QPushButton("🔍 List Processes")
        list_btn.clicked.connect(self._list_procs)
        dev_layout.addWidget(list_btn)
        vbox.addWidget(dev_group)

        script_group = QGroupBox("Frida Script")
        script_layout = QVBoxLayout(script_group)

        template_row = QHBoxLayout()
        template_row.addWidget(QLabel("Template:"))
        self.tmpl_combo = QComboBox()
        self.tmpl_combo.addItems(list(TEMPLATES.keys()))
        self.tmpl_combo.currentTextChanged.connect(self._load_template)
        template_row.addWidget(self.tmpl_combo)

        load_file_btn = QPushButton("📂 Load .js")
        load_file_btn.clicked.connect(self._load_file)
        template_row.addWidget(load_file_btn)

        save_btn = QPushButton("💾 Save .js")
        save_btn.clicked.connect(self._save_file)
        template_row.addWidget(save_btn)
        script_layout.addLayout(template_row)

        self.editor = QPlainTextEdit()
        self.editor.setFont(QFont("Monospace", 9))
        self.editor.setMinimumHeight(200)
        script_layout.addWidget(self.editor)
        vbox.addWidget(script_group)

        controls = QHBoxLayout()
        self.run_btn = QPushButton("▶ Run Script")
        self.run_btn.clicked.connect(self._inject)
        controls.addWidget(self.run_btn)

        self.stop_btn = QPushButton("■ Stop")
        self.stop_btn.clicked.connect(self._stop)
        self.stop_btn.setEnabled(False)
        controls.addWidget(self.stop_btn)

        clear_btn = QPushButton("✖ Clear")
        clear_btn.clicked.connect(self.console_clear)
        controls.addWidget(clear_btn)
        vbox.addLayout(controls)

        self.console = QPlainTextEdit()
        self.console.setReadOnly(True)
        self.console.setFont(QFont("Monospace", 9))
        vbox.addWidget(self.console)

        self._worker: _FridaWorker | None = None
        self._background_workers: list[_FridaWorker] = []
        self._temp_script: Path | None = None
        self._load_template(self.tmpl_combo.currentText())
        self._set_availability_state()

    def _set_availability_state(self) -> None:
        self.run_btn.setEnabled(FRIDA_AVAILABLE)

    def console_clear(self) -> None:
        self.console.clear()

    def _device_args(self) -> list[str]:
        serial = self.serial.text().strip()
        return ["-D", serial] if serial else ["-U"]

    def _load_template(self, name: str) -> None:
        self.editor.setPlainText(TEMPLATES.get(name, ""))

    def _load_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Load script", str(Path.home()), "JS (*.js);;All (*)")
        if not path:
            return
        try:
            self.editor.setPlainText(Path(path).read_text(encoding="utf-8", errors="replace"))
        except OSError as exc:
            self.console.appendPlainText(f"[ERR] Could not load script: {exc}")

    def _save_file(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Save script", str(Path.home() / "frida_hook.js"), "JS (*.js)")
        if not path:
            return
        try:
            Path(path).write_text(self.editor.toPlainText(), encoding="utf-8")
            log.info("[FRIDA] script saved: %s", path)
        except OSError as exc:
            self.console.appendPlainText(f"[ERR] Could not save script: {exc}")

    def _list_procs(self) -> None:
        if FRIDA_PS_BIN is None:
            self.console.appendPlainText("[ERR] frida-ps is not available")
            return
        self._run_background([FRIDA_PS_BIN, *self._device_args(), "-a"])

    def _inject(self) -> None:
        if FRIDA_BIN is None:
            self.console.appendPlainText("[ERR] frida is not available")
            return

        target = self.pkg.text().strip()
        if not target:
            self.console.appendPlainText("[!] No package, process name, or PID specified")
            return

        WORK_DIR.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".js",
            prefix="reforge-frida-",
            dir=WORK_DIR,
            delete=False,
            encoding="utf-8",
        ) as handle:
            handle.write(self.editor.toPlainText())
            script_path = Path(handle.name)
        self._temp_script = script_path

        if self.spawn_chk.isChecked():
            target_args = ["-f", target]
        elif target.isdigit():
            target_args = ["-p", target]
        else:
            target_args = ["-n", target]

        args = [FRIDA_BIN, *self._device_args(), *target_args, "-l", str(script_path)]
        self._start_primary(args, target)

    def _start_primary(self, args: list[str], target: str) -> None:
        self.console.appendPlainText(f"\n$ {shlex.join(args)}")
        log.info("[FRIDA] starting: %s", shlex.join(args))
        bus.emit("frida.run", {"target": target}, source="frida_tools")

        self._worker = _FridaWorker(args)
        self._worker.line.connect(self.console.appendPlainText)
        self._worker.done.connect(self._on_primary_done)
        self.run_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self._worker.start()

    def _run_background(self, args: list[str]) -> None:
        self.console.appendPlainText(f"\n$ {shlex.join(args)}")
        worker = _FridaWorker(args)
        self._background_workers.append(worker)
        worker.line.connect(self.console.appendPlainText)
        worker.done.connect(lambda rc, w=worker: self._on_background_done(w, rc))
        worker.start()

    def _on_background_done(self, worker: _FridaWorker, rc: int) -> None:
        self.console.appendPlainText(f"[exit {rc}]")
        if worker in self._background_workers:
            self._background_workers.remove(worker)
        worker.deleteLater()

    def _stop(self) -> None:
        if self._worker is not None:
            self._worker.stop()

    def _on_primary_done(self, rc: int) -> None:
        self.console.appendPlainText(f"[exit {rc}]")
        self.stop_btn.setEnabled(False)
        self.run_btn.setEnabled(FRIDA_AVAILABLE)
        if self._worker is not None:
            self._worker.deleteLater()
            self._worker = None
        self._cleanup_temp_script()

    def _cleanup_temp_script(self) -> None:
        if self._temp_script is None:
            return
        try:
            self._temp_script.unlink(missing_ok=True)
        except OSError:
            log.warning("Could not remove temporary Frida script: %s", self._temp_script)
        self._temp_script = None

    def shutdown(self) -> None:
        if self._worker is not None:
            self._worker.stop()
            self._worker.wait(2000)
        for worker in list(self._background_workers):
            worker.stop()
            worker.wait(2000)
        self._background_workers.clear()
        self._cleanup_temp_script()


class FridaToolsPlugin(BasePlugin):
    def __init__(self):
        super().__init__()
        self.name = "Frida Tools"
        self.description = "Authorized dynamic instrumentation and script execution."
        self.widget: FridaToolsWidget | None = None

    def initialize(self, main_window) -> None:
        self.widget = FridaToolsWidget()
        main_window.add_plugin_dock("Frida Tools", self.widget)
        log.info("Frida Tools plugin attached to GUI")

    def shutdown(self) -> None:
        if self.widget is not None:
            self.widget.shutdown()
        self.widget = None
