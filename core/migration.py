"""
ReForge Migration Layer
————————————————————————————————————————————————
Provides a uniform API to execute or import legacy assets from:
  • batch/   — Windows .bat scripts (wrapped via wine or direct shell equiv.)
  • commands/ — Reference text files + key pairs
  • python scripts/samples/ — JEB/standalone Python scripts

All runners are bus-aware: they emit events on start/finish/error.
"""
from __future__ import annotations
import subprocess
import sys
import importlib.util
from pathlib import Path
from typing import Optional, Callable

from core.logger import get_logger
from core.event_bus import bus

log = get_logger("core.migration")

ROOT_DIR     = Path(__file__).resolve().parent.parent
BATCH_DIR    = ROOT_DIR / "batch"
CMD_DIR      = ROOT_DIR / "commands"
JAR_DIR      = ROOT_DIR / "jar"
PYSCRIPT_DIR = ROOT_DIR / "python scripts" / "samples"


# ─────────────────────────────────────────────
# Batch wrapper
# ─────────────────────────────────────────────
class BatchRunner:
    """
    Execute .bat scripts via cmd.exe (Wine) or convert them to
    equivalent java -jar invocations on Linux.

    Supported scripts and their Linux equivalents are mapped below.
    Unknown .bat files are run via `wine cmd /c <file>` if wine exists.
    """

    # Maps bat filename → callable that builds the Linux command
    _NATIVE_EQUIV: dict[str, Callable[[dict], str]] = {
        "decompile_apk.bat": lambda kw: (
            f'java -jar "{JAR_DIR / "apktool.jar"}" d -f '
            f'-o "{kw["out"]}" "{kw["apk"]}"'
        ),
        "compile_apk.bat": lambda kw: (
            f'java -jar "{JAR_DIR / "apktool.jar"}" b '
            f'"{kw["src"]}" -o "{kw["out"]}"'
        ),
        "decompile_jar.bat": lambda kw: (
            f'java -jar "{JAR_DIR / "jadx.jar" if (JAR_DIR / "jadx.jar").exists() else "jadx"}" '
            f'"{kw["jar"]}" -d "{kw["out"]}"'
        ),
        "compile_jar.bat": lambda kw: (
            f'java -jar "{JAR_DIR / "smali.jar"}" ass "{kw["src"]}" -o "{kw["out"]}"'
        ),
        "signapk.bat": lambda kw: (
            f'java -jar "{JAR_DIR / "signapk.jar"}" '
            f'"{CMD_DIR / "testkey.x509.pem"}" "{CMD_DIR / "testkey.pk8"}" '
            f'"{kw["apk"]}" "{kw["out"]}"'
        ),
    }

    @classmethod
    def run(cls, bat_name: str, kwargs: dict, on_output: Optional[Callable] = None) -> int:
        """
        Run a batch script by name.  kwargs fills placeholders.
        Returns the process exit code.
        """
        bat_path = BATCH_DIR / bat_name
        if not bat_path.exists():
            log.error("[BATCH] File not found: %s", bat_path)
            return 1

        if bat_name in cls._NATIVE_EQUIV:
            try:
                cmd = cls._NATIVE_EQUIV[bat_name](kwargs)
            except KeyError as e:
                log.error("[BATCH] Missing kwarg %s for %s", e, bat_name)
                return 1
            log.info("[BATCH] Native equiv for %s → %s", bat_name, cmd)
        else:
            # Fall back to wine
            cmd = f'wine cmd /c "{bat_path}"'
            log.warning("[BATCH] No native equiv — falling back to wine: %s", cmd)

        bus.emit("batch.start", {"bat": bat_name, "cmd": cmd}, source="migration")
        result = _stream_run(cmd, on_output)
        bus.emit("batch.done", {"bat": bat_name, "rc": result}, source="migration")
        return result

    @classmethod
    def available(cls) -> list[str]:
        if not BATCH_DIR.exists():
            return []
        return [f.name for f in BATCH_DIR.glob("*.bat")]


# ─────────────────────────────────────────────
# Command reference reader
# ─────────────────────────────────────────────
class CommandRef:
    """Load reference text from commands/ by tool name."""

    _MAP = {
        "adb":      "adb-commands-list.txt",
        "fastboot": "fastboot-commands-list.txt",
        "apktool":  "apktool-commands-list.txt",
        "smali":    "smali-commands-list.txt",
        "baksmali": "baksmali-commands-list.txt",
        "aapt":     "aapt-commands-list.txt",
        "zipalign": "zipalign-commands-list.txt",
        "signapk":  "signapk-commmands-list.txt",
    }

    @classmethod
    def get(cls, tool: str) -> str:
        fname = cls._MAP.get(tool.lower())
        if not fname:
            return f"No reference found for '{tool}'"
        path = CMD_DIR / fname
        if not path.exists():
            return f"File not found: {path}"
        return path.read_text(errors="replace")

    @classmethod
    def list_tools(cls) -> list[str]:
        return list(cls._MAP.keys())


# ─────────────────────────────────────────────
# Python script runner
# ─────────────────────────────────────────────
class PyScriptRunner:
    """
    Execute or import standalone Python scripts from python scripts/samples/.
    Scripts may be JEB-specific (require jeb runtime) — detected by
    the presence of `com.pnfsoftware` imports and skipped gracefully.
    """

    @classmethod
    def run(cls, script_name: str, on_output: Optional[Callable] = None) -> int:
        path = PYSCRIPT_DIR / script_name
        if not path.exists():
            log.error("[PYSCRIPT] Not found: %s", path)
            return 1
        src = path.read_text(errors="replace")
        if "com.pnfsoftware" in src:
            log.warning("[PYSCRIPT] %s requires JEB runtime — launching via JEB jar", script_name)
            jeb_jar = JAR_DIR / "jeb.jar"
            if jeb_jar.exists():
                cmd = f'java -jar "{jeb_jar}" --run-script="{path}"'
            else:
                log.error("[PYSCRIPT] jeb.jar not found")
                return 1
        else:
            cmd = f'{sys.executable} "{path}"'

        log.info("[PYSCRIPT] Running: %s", cmd)
        bus.emit("script.start", {"name": script_name}, source="migration")
        rc = _stream_run(cmd, on_output)
        bus.emit("script.done", {"name": script_name, "rc": rc}, source="migration")
        return rc

    @classmethod
    def list_scripts(cls) -> list[Path]:
        if not PYSCRIPT_DIR.exists():
            return []
        return sorted(PYSCRIPT_DIR.iterdir())


# ─────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────
def _stream_run(cmd: str, on_output: Optional[Callable] = None) -> int:
    try:
        proc = subprocess.Popen(
            cmd, shell=True, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, text=True
        )
        for line in proc.stdout:
            line = line.rstrip()
            log.debug("[OUT] %s", line)
            if on_output:
                on_output(line)
        proc.wait()
        return proc.returncode
    except Exception as exc:
        log.exception("[RUN] Exception: %s", exc)
        return 1
