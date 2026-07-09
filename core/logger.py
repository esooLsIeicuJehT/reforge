"""
ReForge Logger — Hacker-noir styled, rotating log files + coloured console.
"""
import logging
import logging.handlers
import sys
import tempfile
import traceback
from pathlib import Path

LOG_DIR = Path(__file__).resolve().parent.parent / "logs"

# ── ANSI palette ──────────────────────────────────────────────────────────────
_RESET  = "\\033[0m"
_BOLD   = "\\033[1m"
_DIM    = "\\033[2m"

LEVEL_COLOURS = {
    "DEBUG"    : "\\033[38;5;244m",   # grey
    "INFO"     : "\\033[38;5;82m",    # neon green
    "WARNING"  : "\\033[38;5;226m",   # neon yellow
    "ERROR"    : "\\033[38;5;196m",   # neon red
    "CRITICAL" : "\\033[38;5;201m",   # neon magenta
}

class _NeonFormatter(logging.Formatter):
    """Coloured console formatter with hacker-noir prefix tags."""

    TAG = {
        "DEBUG"    : "[DBG]",
        "INFO"     : "[INF]",
        "WARNING"  : "[WRN]",
        "ERROR"    : "[ERR]",
        "CRITICAL" : "[!!!]",
    }

    def format(self, record: logging.LogRecord) -> str:
        lvl   = record.levelname
        col   = LEVEL_COLOURS.get(lvl, "")
        tag   = self.TAG.get(lvl, f"[{lvl}]")
        name  = record.name.replace("reforge.", "")
        msg   = super().format(record)
        # Strip the base formatted string and rebuild with colour
        ts    = self.formatTime(record, self.datefmt)
        return (
            f"{_DIM}{ts}{_RESET} "
            f"{col}{_BOLD}{tag}{_RESET} "
            f"{_DIM}{name:<28}{_RESET} "
            f"{col}{record.getMessage()}{_RESET}"
        )


def setup_logger() -> logging.Logger:
    root = logging.getLogger("reforge")
    if getattr(root, "_reforge_configured", False):
        return root

    root.setLevel(logging.DEBUG)
    root.propagate = False

    plain_fmt = logging.Formatter(
        "%(asctime)s %(levelname)-8s %(name)-35s %(message)s"
    )

    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.INFO)
    ch.setFormatter(_NeonFormatter(datefmt="%H:%M:%S"))
    root.addHandler(ch)

    log_dir = LOG_DIR
    try:
        _add_file_handlers(root, log_dir, plain_fmt)
    except PermissionError as exc:
        log_dir = Path(tempfile.gettempdir()) / "reforge" / "logs"
        _add_file_handlers(root, log_dir, plain_fmt)
        root.warning(
            "Cannot write to %s (%s); logging to %s instead",
            LOG_DIR, exc, log_dir
        )

    root._reforge_configured = True
    root._reforge_log_dir = log_dir
    return root


def _add_file_handlers(root: logging.Logger, log_dir: Path, formatter: logging.Formatter):
    log_dir.mkdir(parents=True, exist_ok=True)
    handlers = [
        (log_dir / "reforge.log", logging.DEBUG),
        (log_dir / "error.log", logging.ERROR),
    ]
    for path, level in handlers:
        file_handler = logging.handlers.RotatingFileHandler(
            path, maxBytes=5 * 1024 * 1024, backupCount=3
        )
        file_handler.setLevel(level)
        file_handler.setFormatter(formatter)
        root.addHandler(file_handler)

# Module-level logger - initialized lazily
_logger = None
def logger():
    """Get the module-level logger (lazy initialization)"""
    global _logger
    if _logger is None:
        _logger = setup_logger()
    return _logger


def global_exception_hook(exc_type, exc_value, exc_tb):
    tb_str = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
    logger().critical("Unhandled exception:\n%s", tb_str)
    try:
        from PyQt6.QtWidgets import QApplication, QMessageBox
        if QApplication.instance():
            QMessageBox.critical(
                None, "ReForge — Fatal Error",
                f"An unexpected error occurred:\n\n{tb_str}\n\nCheck logs/error.log."
            )
    except Exception:
        pass
    sys.__excepthook__(exc_type, exc_value, exc_tb)


def install_global_except_hook():
    sys.excepthook = global_exception_hook


def get_logger(name: str) -> logging.Logger:
    setup_logger()
    return logging.getLogger(f"reforge.{name}")
