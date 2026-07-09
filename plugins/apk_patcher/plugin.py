import os, re, tempfile, subprocess, shutil
from pathlib import Path
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QCheckBox,
    QLineEdit, QFileDialog, QLabel, QGroupBox, QMessageBox, QComboBox
)
from PyQt6.QtCore import pyqtSignal, QThread
from core.plugin_manager import BasePlugin
from core.logger import get_logger

logger = get_logger(__name__)

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
JAR_DIR  = ROOT_DIR / "jar"
CMD_DIR  = ROOT_DIR / "commands"
ADB_DIR  = ROOT_DIR / "adb"

class PatcherWorker(QThread):
    status = pyqtSignal(str)
    finished = pyqtSignal(bool, str)

    def __init__(self, apk_path, options, keystore=None, signer="uber-apk-signer"):
        super().__init__()
        self.apk_path = apk_path
        self.options = options
        self.keystore = keystore
        self.signer = signer

    def run_cmd(self, cmd, desc=""):
        self.status.emit(f"[+] {desc}")
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        if result.returncode != 0:
            self.status.emit(f"[-] {desc} FAILED: {result.stderr.strip()}")
            return False
        return True

    def run(self):
        base_work_dir = ROOT_DIR / "work_dirs"
        base_work_dir.mkdir(parents=True, exist_ok=True)
        work_dir = tempfile.mkdtemp(prefix="reforge_apk_", dir=base_work_dir)
        
        extract_dir = Path(work_dir) / "extracted"
        patched_apk = Path(work_dir) / "patched.apk"
        success = False

        apktool_jar = JAR_DIR / "apktool.jar"
        if not apktool_jar.exists():
            self.finished.emit(False, "apktool.jar not found in jar folder.")
            return

        try:
            self.status.emit("Decompiling APK...")
            cmd = f'java -jar "{apktool_jar}" d -f -o "{extract_dir}" "{self.apk_path}"'
            if not self.run_cmd(cmd, "Decompilation"):
                self.finished.emit(False, "Decompilation failed")
                return

            self._patch_smali(extract_dir)

            rebuilt = Path(work_dir) / "unsigned.apk"
            cmd = f'java -jar "{apktool_jar}" b "{extract_dir}" -o "{rebuilt}"'
            if not self.run_cmd(cmd, "Rebuilding APK"):
                self.finished.emit(False, "Rebuild failed")
                return

            # Signing process
            self.status.emit(f"Signing APK using {self.signer}...")
            if self.signer == "uber-apk-signer":
                uber_jar = JAR_DIR / "uber-apk-signer.jar"
                if not uber_jar.exists():
                    self.finished.emit(False, "uber-apk-signer.jar not found.")
                    return
                cmd = f'java -jar "{uber_jar}" --apks "{rebuilt}" -o "{work_dir}"'
                if not self.run_cmd(cmd, "Signing with uber-apk-signer"):
                    self.finished.emit(False, "uber-apk-signer failed")
                    return
                
                signed_files = list(Path(work_dir).glob("*-signed.apk")) + list(Path(work_dir).glob("*-aligned-debugSigned.apk"))
                if signed_files:
                    shutil.move(str(signed_files[0]), patched_apk)
                else:
                    self.finished.emit(False, "Could not find output from uber-apk-signer.")
                    return
            
            elif self.signer == "apksigner":
                apksigner_jar = JAR_DIR / "apksigner-0.9.jar"
                if not apksigner_jar.exists():
                    self.finished.emit(False, "apksigner-0.9.jar not found.")
                    return
                keystore = self.keystore or self._generate_debug_keystore(work_dir)
                cmd = (
                    f'java -jar "{apksigner_jar}" sign --ks "{keystore}" --ks-pass pass:android '
                    f'--ks-key-alias debug --out "{patched_apk}" "{rebuilt}"'
                )
                if not self.run_cmd(cmd, "Signing with apksigner"):
                    self.finished.emit(False, "apksigner failed")
                    return

            elif self.signer == "signapk":
                signapk_jar = JAR_DIR / "signapk.jar"
                if not signapk_jar.exists():
                    self.finished.emit(False, "signapk.jar not found.")
                    return
                
                pem_key = CMD_DIR / "testkey.x509.pem"
                pk8_key = CMD_DIR / "testkey.pk8"
                if not (pem_key.exists() and pk8_key.exists()):
                    self.status.emit("[!] Warning: testkey files missing from commands/ — signapk may fail.")
                
                cmd = f'java -jar "{signapk_jar}" "{pem_key}" "{pk8_key}" "{rebuilt}" "{patched_apk}"'
                if not self.run_cmd(cmd, "Signing with signapk"):
                    self.finished.emit(False, "signapk failed")
                    return

            success = True
            self.finished.emit(True, str(patched_apk))

        except Exception as e:
            logger.exception(f"An error occurred during APK patching: {e}")
            self.finished.emit(False, f"Exception occurred: {e}")
        finally:
            if not success:
                self.status.emit("Cleaning up failed work directory...")
                shutil.rmtree(work_dir, ignore_errors=True)

    def _patch_smali(self, extract_dir):
        smali_files = list(Path(extract_dir).rglob("*.smali"))
        if self.options.get("patch_lvl", False):
            self._patch_google_lvl(smali_files)
        if self.options.get("patch_pro", False):
            self._force_premium_flags(smali_files)
        if self.options.get("patch_ssl", False):
            self._bypass_ssl_pinning(smali_files)
        if self.options.get("kill_sig", False):
            self._kill_signature_check(smali_files)
        if self.options.get("no_internet", False):
            self._remove_internet_permission(extract_dir)

    def _patch_google_lvl(self, smali_files):
        for sf in smali_files:
            with open(sf, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
            if "LicenseClient" in sf.name or ("processResponse" in content and "ILicensingService" in content):
                content = re.sub(
                    r'(\.method static constructor <clinit>\(\)V.*?)(\n    return-void)',
                    r'\1\n    const/4 v0, 0x1\n    sput v0, L' +
                    sf.stem.split('$')[0] + ';->licenseCheckState:I\n\2',
                    content, flags=re.DOTALL)
                content = re.sub(
                    r'(\.method .* processResponse\(I.*?V.*?)(?:\.locals\s+\d+|\.registers\s+\d+)',
                    r'\g<0>\n    const/4 p0, 0x0\n    return-void',
                    content, flags=re.DOTALL
                )
                with open(sf, "w", encoding="utf-8") as f:
                    f.write(content)
                self.status.emit(f"[+] Patched LVL: {sf.name}")
                return
        self.status.emit("[!] LVL class not found, trying generic license override.")
        self._generic_license_override(smali_files)

    def _generic_license_override(self, smali_files):
        count = 0
        for sf in smali_files:
            with open(sf, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
            if re.search(r'(license|verify|premium|trial|activation)', content, re.IGNORECASE):
                new_content = re.sub(
                    r'(sget-boolean\s+(v\d+),\s+(\S+)->[^,]+:Z)',
                    r'    const/4 \2, 0x1    # forced true',
                    content
                )
                new_content = re.sub(
                    r'invoke-(?:direct|static).*verify.*',
                    r'    # NOP license check',
                    new_content
                )
                if new_content != content:
                    with open(sf, "w", encoding="utf-8") as f:
                        f.write(new_content)
                    count += 1
        self.status.emit(f"[+] Generic license patching modified {count} files.")

    def _force_premium_flags(self, smali_files):
        flags = ["isPro", "isPremium", "isVip", "isPaid", "isLicensed", "isGold"]
        for sf in smali_files:
            with open(sf, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
            modified = False
            for flag in flags:
                pattern = rf'(sget-boolean\s+(v\d+),\s+(\S+)->{flag}:Z)'
                repl = r'    const/4 \2, 0x1    # forced \3'
                new = re.sub(pattern, repl, content)
                if new != content:
                    modified = True
                    content = new
            if modified:
                with open(sf, "w", encoding="utf-8") as f:
                    f.write(content)
        self.status.emit("[+] Premium/Pro flags forced to true.")

    def _bypass_ssl_pinning(self, smali_files):
        for sf in smali_files:
            with open(sf, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
            if "X509TrustManager" in content:
                content = re.sub(
                    r'(\.method public checkServerTrusted\(\[Ljava/security/cert/X509Certificate;Ljava/lang/String;\)V.*?)(?:\.locals\s+\d+|\.registers\s+\d+)',
                    r'\g<0>\n    return-void',
                    content, flags=re.DOTALL
                )
                content = re.sub(
                    r'(\.method public checkClientTrusted\(\[Ljava/security/cert/X509Certificate;Ljava/lang/String;\)V.*?)(?:\.locals\s+\d+|\.registers\s+\d+)',
                    r'\g<0>\n    return-void',
                    content, flags=re.DOTALL
                )
                with open(sf, "w", encoding="utf-8") as f:
                    f.write(content)
                self.status.emit(f"[+] SSL pinning removed in {sf.name}")

    def _kill_signature_check(self, smali_files):
        for sf in smali_files:
            with open(sf, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
            if "getPackageInfo" in content:
                content = re.sub(
                    r'invoke-virtual.*PackageManager;->getPackageInfo.*',
                    r'    # NOP signature check',
                    content
                )
                with open(sf, "w", encoding="utf-8") as f:
                    f.write(content)
        self.status.emit("[+] Signature verification calls removed.")

    def _remove_internet_permission(self, extract_dir):
        manifest = Path(extract_dir) / "AndroidManifest.xml"
        if manifest.exists():
            with open(manifest, "r", encoding="utf-8") as f:
                content = f.read()
            content = re.sub(
                r'<uses-permission\s+android:name="android\.permission\.INTERNET"\s*/>',
                '', content)
            with open(manifest, "w", encoding="utf-8") as f:
                f.write(content)
            self.status.emit("[+] INTERNET permission removed.")

    def _generate_debug_keystore(self, work_dir):
        ks = Path(work_dir) / "debug.keystore"
        cmd = (
            f'keytool -genkey -v -keystore "{ks}" -alias debug -keyalg RSA '
            f'-keysize 2048 -validity 10000 -storepass android -keypass android '
            f'-dname "CN=Debug, OU=Dev, O=Debug, L=City, S=State, C=US"'
        )
        subprocess.run(cmd, shell=True, capture_output=True)
        return ks


class ApkPatcherWidget(QWidget):
    def __init__(self):
        super().__init__()
        layout = QVBoxLayout()

        file_box = QHBoxLayout()
        self.apk_path_edit = QLineEdit()
        self.apk_path_edit.setPlaceholderText("Select target APK...")
        browse_btn = QPushButton("Browse")
        browse_btn.clicked.connect(self.browse_apk)
        file_box.addWidget(self.apk_path_edit)
        file_box.addWidget(browse_btn)
        layout.addLayout(file_box)

        # External Analysis Tools Group
        tools_group = QGroupBox("External Analysis Tools")
        tools_layout = QHBoxLayout()
        
        self.btn_bcv = QPushButton("Bytecode Viewer")
        self.btn_bcv.clicked.connect(self.launch_bytecode_viewer)
        tools_layout.addWidget(self.btn_bcv)
        
        self.btn_jeb = QPushButton("JEB Decompiler")
        self.btn_jeb.clicked.connect(self.launch_jeb)
        tools_layout.addWidget(self.btn_jeb)
        
        tools_group.setLayout(tools_layout)
        layout.addWidget(tools_group)

        opt_group = QGroupBox("Patch Options")
        opt_layout = QVBoxLayout()
        self.chk_lvl = QCheckBox("Google LVL / Pairip bypass")
        self.chk_pro = QCheckBox("Force Pro/Premium features")
        self.chk_ssl = QCheckBox("SSL Pinning bypass (static)")
        self.chk_killsig = QCheckBox("Kill signature checks")
        self.chk_noinet = QCheckBox("Remove INTERNET permission")
        for chk in [self.chk_lvl, self.chk_pro, self.chk_ssl, self.chk_killsig, self.chk_noinet]:
            chk.setChecked(True)
            opt_layout.addWidget(chk)
        opt_group.setLayout(opt_layout)
        layout.addWidget(opt_group)

        sign_group = QGroupBox("Signing Configuration")
        sign_layout = QVBoxLayout()
        
        combo_layout = QHBoxLayout()
        combo_layout.addWidget(QLabel("Signer Tool:"))
        self.signer_combo = QComboBox()
        self.signer_combo.addItems(["uber-apk-signer", "apksigner", "signapk"])
        combo_layout.addWidget(self.signer_combo)
        sign_layout.addLayout(combo_layout)

        ks_box = QHBoxLayout()
        ks_box.addWidget(QLabel("Custom Keystore:"))
        self.ks_edit = QLineEdit()
        self.ks_edit.setPlaceholderText("Optional")
        self.ks_edit.setReadOnly(True)
        ks_browse = QPushButton("Browse")
        ks_browse.clicked.connect(self.browse_keystore)
        ks_box.addWidget(self.ks_edit)
        ks_box.addWidget(ks_browse)
        sign_layout.addLayout(ks_box)
        sign_group.setLayout(sign_layout)
        layout.addWidget(sign_group)

        self.start_btn = QPushButton("Start Patching")
        self.start_btn.clicked.connect(self.start_patching)
        layout.addWidget(self.start_btn)

        self.status_label = QLabel("")
        layout.addWidget(self.status_label)
        layout.addStretch()
        self.setLayout(layout)

    def browse_apk(self):
        default_dir = str(ROOT_DIR / "apks")
        path, _ = QFileDialog.getOpenFileName(self, "Select APK", default_dir, "APK files (*.apk)")
        if path:
            self.apk_path_edit.setText(path)

    def browse_keystore(self):
        path, _ = QFileDialog.getOpenFileName(self, "Select Keystore", "", "Keystore (*.keystore *.jks)")
        if path:
            self.ks_edit.setText(path)

    def launch_bytecode_viewer(self):
        apk = self.apk_path_edit.text().strip()
        bcv_jar = JAR_DIR / "Bytecode-Viewer.jar"
        if not bcv_jar.exists():
            QMessageBox.warning(self, "Error", "Bytecode-Viewer.jar not found in jar directory.")
            return
        cmd = f'java -jar "{bcv_jar}"'
        if apk:
            cmd += f' "{apk}"'
        subprocess.Popen(cmd, shell=True)
        self.status_label.setText("Launched Bytecode Viewer.")

    def launch_jeb(self):
        apk = self.apk_path_edit.text().strip()
        jeb_jar = JAR_DIR / "jeb.jar"
        if not jeb_jar.exists():
            QMessageBox.warning(self, "Error", "jeb.jar not found in jar directory.")
            return
        cmd = f'java -jar "{jeb_jar}"'
        if apk:
            # Although JEB has different args, usually passing the apk opens it
            cmd += f' "{apk}"'
        subprocess.Popen(cmd, shell=True)
        self.status_label.setText("Launched JEB Decompiler.")

    def start_patching(self):
        apk = self.apk_path_edit.text().strip()
        if not apk:
            QMessageBox.warning(self, "Error", "No APK selected.")
            return
        options = {
            "patch_lvl": self.chk_lvl.isChecked(),
            "patch_pro": self.chk_pro.isChecked(),
            "patch_ssl": self.chk_ssl.isChecked(),
            "kill_sig": self.chk_killsig.isChecked(),
            "no_internet": self.chk_noinet.isChecked()
        }
        self.worker = PatcherWorker(apk, options, self.ks_edit.text() or None, self.signer_combo.currentText())
        self.worker.status.connect(self.update_status)
        self.worker.finished.connect(self.patching_finished)
        self.start_btn.setEnabled(False)
        self.worker.start()

    def update_status(self, message):
        self.status_label.setText(message)

    def patching_finished(self, success, message):
        self.start_btn.setEnabled(True)
        if success:
            QMessageBox.information(self, "Success", f"Patched APK saved to:\n{message}")
        else:
            QMessageBox.critical(self, "Error", message)

class APKPatcherPlugin(BasePlugin):
    def __init__(self):
        super().__init__()
        self.name = "APK Patcher"
        self.description = "Automated APK license removal and feature forcing with integrated analysis tools."
        self.widget = None

    def initialize(self, main_window):
        self.widget = ApkPatcherWidget()
        main_window.add_plugin_dock("APK Patcher", self.widget)
        logger.info("APK Patcher plugin initialized.")

    def shutdown(self):
        self.widget = None