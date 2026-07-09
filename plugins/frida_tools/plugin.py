"""
Frida Tools Plugin — Script generation, process attachment, dynamic hooks.
Requires: frida-tools (pip), frida server on device.
"""
import subprocess, shutil, re
from pathlib import Path
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QComboBox,
    QPlainTextEdit, QLineEdit, QGroupBox, QFileDialog, QCheckBox
)
from PyQt6.QtCore import QThread, pyqtSignal
from PyQt6.QtGui import QFont
from core.plugin_manager import BasePlugin
from core.event_bus import bus
from core.logger import get_logger

log = get_logger("plugin.frida_tools")

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
ADB_DIR  = ROOT_DIR / "adb"
_adb_bin = ADB_DIR / "adb"
ADB      = str(_adb_bin) if _adb_bin.exists() else "adb"

FRIDA_AVAILABLE = bool(shutil.which("frida") or shutil.which("frida-ps"))

# ── Boilerplate hook templates ─────────────────────────────────────
TEMPLATES = {
    "SSL Unpin (Java)": """\
Java.perform(function() {
    var TrustManager = Java.use('javax.net.ssl.X509TrustManager');
    var SSLContext = Java.use('javax.net.ssl.SSLContext');
    var TrustManagerImpl = Java.registerClass({
        name: 'com.reforge.TrustManager',
        implements: [TrustManager],
        methods: {
            checkClientTrusted: function(chain, authType) {},
            checkServerTrusted: function(chain, authType) {},
            getAcceptedIssuers: function() { return []; }
        }
    });
    var ctx = SSLContext.getInstance('TLS');
    ctx.init(null, [TrustManagerImpl.$new()], null);
    SSLContext.getDefault.implementation = function() { return ctx; };
    console.log('[+] SSL pinning bypassed');
});
""",
    "Root Detection Bypass": """\
Java.perform(function() {
    var RootBeer = null;
    try { RootBeer = Java.use('com.scottyab.rootbeer.RootBeer'); } catch(e) {}
    if (RootBeer) {
        RootBeer.isRooted.implementation = function() {
            console.log('[+] RootBeer.isRooted -> false'); return false;
        };
    }
    var Build = Java.use('android.os.Build.Tags');
    // Patches common root file checks
    var File = Java.use('java.io.File');
    File.exists.implementation = function() {
        var path = this.getAbsolutePath();
        if (path.indexOf('su') !== -1 || path.indexOf('superuser') !== -1) {
            console.log('[+] Blocked file check: ' + path); return false;
        }
        return this.exists();
    };
});
""",
    "Method Tracer": """\
// Replace com.example.ClassName with your target
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
        } catch(e) {}
    });
    console.log('[+] All methods in ' + TargetClass + ' traced');
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
    "Blank Script": "// Your Frida script here\nJava.perform(function() {\n\n});\n",
}


class _FridaWorker(QThread):
    line = pyqtSignal(str)
    done = pyqtSignal(int)

    def __init__(self, cmd):
        super().__init__()
        self.cmd  = cmd
        self._proc = None

    def run(self):
        try:
            self._proc = subprocess.Popen(
                self.cmd, shell=True, stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT, text=True
            )
            for ln in self._proc.stdout:
                self.line.emit(ln.rstrip())
            self._proc.wait()
            self.done.emit(self._proc.returncode)
        except Exception as e:
            self.line.emit(f"[ERR] {e}")
            self.done.emit(1)

    def stop(self):
        if self._proc:
            try:
                self._proc.terminate()
            except Exception:
                pass


class FridaToolsWidget(QWidget):
    def __init__(self):
        super().__init__()
        vbox = QVBoxLayout(self)

        if not FRIDA_AVAILABLE:
            warn = QLabel("⚠  frida-tools not found on PATH.\n"
                          "Install: pip install frida-tools\n"
                          "Also push frida-server to device /data/local/tmp/")
            warn.setStyleSheet("color: #ff9800; padding: 8px;")
            vbox.addWidget(warn)

        # ── Device / process selection ─────────────────────────────
        dev_grp = QGroupBox("Target")
        dv = QVBoxLayout(dev_grp)

        r1 = QHBoxLayout()
        r1.addWidget(QLabel("Device serial (blank=USB):"))
        self.serial = QLineEdit(); self.serial.setPlaceholderText("emulator-5554")
        r1.addWidget(self.serial)
        dv.addLayout(r1)

        r2 = QHBoxLayout()
        r2.addWidget(QLabel("Package / PID:"))
        self.pkg = QLineEdit(); self.pkg.setPlaceholderText("com.example.app")
        r2.addWidget(self.pkg)
        self.spawn_chk = QCheckBox("Spawn (not attach)")
        self.spawn_chk.setChecked(True)
        r2.addWidget(self.spawn_chk)
        dv.addLayout(r2)

        list_btn = QPushButton("🔍 List Processes")
        list_btn.clicked.connect(self._list_procs)
        dv.addWidget(list_btn)
        vbox.addWidget(dev_grp)

        # ── Script editor ──────────────────────────────────────────
        script_grp = QGroupBox("Frida Script")
        sv = QVBoxLayout(script_grp)

        tmpl_row = QHBoxLayout()
        tmpl_row.addWidget(QLabel("Template:"))
        self.tmpl_combo = QComboBox()
        self.tmpl_combo.addItems(list(TEMPLATES.keys()))
        self.tmpl_combo.currentTextChanged.connect(self._load_template)
        tmpl_row.addWidget(self.tmpl_combo)
        load_file_btn = QPushButton("📂 Load .js")
        load_file_btn.clicked.connect(self._load_file)
        tmpl_row.addWidget(load_file_btn)
        save_btn = QPushButton("💾 Save .js")
        save_btn.clicked.connect(self._save_file)
        tmpl_row.addWidget(save_btn)
        sv.addLayout(tmpl_row)

        self.editor = QPlainTextEdit()
        self.editor.setFont(QFont("Monospace", 9))
        self.editor.setMinimumHeight(200)
        sv.addLayout(tmpl_row)
        sv.addWidget(self.editor)
        vbox.addWidget(script_grp)

        # ── Run controls ───────────────────────────────────────────
        ctrl = QHBoxLayout()
        self.run_btn  = QPushButton("▶  Inject Script")
        self.run_btn.clicked.connect(self._inject)
        ctrl.addWidget(self.run_btn)
        self.stop_btn = QPushButton("■  Stop")
        self.stop_btn.clicked.connect(self._stop)
        self.stop_btn.setEnabled(False)
        ctrl.addWidget(self.stop_btn)
        clr = QPushButton("✖  Clear")
        clr.clicked.connect(lambda: self.console.clear())
        ctrl.addWidget(clr)
        vbox.addLayout(ctrl)

        # ── Output ─────────────────────────────────────────────────
        self.console = QPlainTextEdit()
        self.console.setReadOnly(True)
        self.console.setFont(QFont("Monospace", 9))
        vbox.addWidget(self.console)

        self._worker = None
        self._load_template(self.tmpl_combo.currentText())

    def _load_template(self, name: str):
        self.editor.setPlainText(TEMPLATES.get(name, ""))

    def _load_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Load script", str(ROOT_DIR), "JS (*.js);;All (*)"
        )
        if path:
            self.editor.setPlainText(Path(path).read_text(errors="replace"))

    def _save_file(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Save script", str(ROOT_DIR / "frida_hook.js"), "JS (*.js)"
        )
        if path:
            Path(path).write_text(self.editor.toPlainText())
            log.info("[FRIDA] script saved: %s", path)

    def _list_procs(self):
        s = self.serial.text().strip()
        dev_flag = f"-D {s}" if s else "-U"
        self._run_cmd(f"frida-ps {dev_flag} -a")

    def _inject(self):
        pkg    = self.pkg.text().strip()
        if not pkg:
            self.console.appendPlainText("[!] No package/PID specified"); return

        # Write script to temp file
        import tempfile
        tmp = Path(tempfile.mktemp(suffix=".js", dir=ROOT_DIR / "work_dirs"))
        (ROOT_DIR / "work_dirs").mkdir(exist_ok=True)
        tmp.write_text(self.editor.toPlainText())

        s       = self.serial.text().strip()
        dev_flag = f"-D {s}" if s else "-U"
        mode     = "-f" if self.spawn_chk.isChecked() else "-n"
        cmd      = f'frida {dev_flag} {mode} "{pkg}" -l "{tmp}" --no-pause'

        self.console.appendPlainText(f"\n$ {cmd}")
        log.info("[FRIDA] injecting: %s", cmd)
        bus.emit("frida.inject", {"pkg": pkg, "script": str(tmp)}, source="frida_tools")

        self._worker = _FridaWorker(cmd)
        self._worker.line.connect(self.console.appendPlainText)
        self._worker.done.connect(self._on_done)
        self.run_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self._worker.start()

    def _stop(self):
        if self._worker:
            self._worker.stop()
        self.run_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)

    def _on_done(self, rc: int):
        self.console.appendPlainText(f"[exit {rc}]")
        self.run_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)

    def _run_cmd(self, cmd: str):
        self.console.appendPlainText(f"\n$ {cmd}")
        w = _FridaWorker(cmd)
        w.line.connect(self.console.appendPlainText)
        w.done.connect(lambda rc: self.console.appendPlainText(f"[exit {rc}]"))
        w.start()


class FridaToolsPlugin(BasePlugin):
    def __init__(self):
        super().__init__()
        self.name        = "Frida Tools"
        self.description = "Dynamic hooks, script generation, SSL unpin, root bypass."
        self.widget      = None

    def initialize(self, main_window):
        self.widget = FridaToolsWidget()
        main_window.add_plugin_dock("Frida Tools", self.widget)
        log.info("Frida Tools plugin attached to GUI")

    def shutdown(self):
        if self.widget and self.widget._worker:
            self.widget._worker.stop()
        self.widget = None
