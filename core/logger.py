"""Central logging configuration for ReForge."""
from __future__ import annotations

import logging
import logging.handlers
import os
import sys
import tempfile
import traceback
from pathlib import Path

DEFAULT_LOG_DIR = Path.home() / ".reforge" / "logs"

_RESET = "\033[0m"
_BOLD = "\033[1m"
_DIM = "\033[2m"

LEVEL_COLOURS = {
    "DEBUG": "\033[38;5;244m",
    "INFO": "\033[38;5;82m",
    "WARNING": "\033[38;5;226m",
    "ERROR": "\033[38;5;196m",
    "CRITICAL": "\033[38;5;201m",
}


class _NeonFormatter(logging.Formatter):
    TAG = {
        "DEBUG": "[DBG]",
        "INFO": "[INF]",
        "WARNING": "[WRN]",
        "ERROR": "[ERR]",
        "CRITICAL": "[!!!]",
    }

    def format(self, record: logging.LogRecord) -> str:
        level = record.levelname
        colour = LEVEL_COLOURS.get(level, "")
        tag = self.TAG.get(level, f"[{level}]")
        name = record.name.removeprefix("reforge.")
        timestamp = self.formatTime(record, self.datefmt)
        return (
            f"{_DIM}{timestamp}{_RESET} "
            f"{colour}{_BOLD}{tag}{_RESET} "
            f"{_DIM}{name:<28}{_RESET} "
            f"{colour}{record.getMessage()}{_RESET}"
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

    console = logging.StreamHandler(sys.stdout)
    console.setLevel(logging.INFO)
    if sys.stdout.isatty() and os.environ.get("NO_COLOR") is None:
        console.setFormatter(_NeonFormatter(datefmt="%H:%M:%S"))
    else:
        console.setFormatter(logging.Formatter("%(levelname)-8s %(name)s: %(message)s"))
    root.addHandler(console)

    log_dir = DEFAULT_LOG_DIR
    try:
        _add_file_handlers(root, log_dir, plain_fmt)
    except OSError as exc:
        log_dir = Path(tempfile.gettempdir()) / "reforge" / "logs"
        _add_file_handlers(root, log_dir, plain_fmt)
        root.warning(
            "Cannot write to %s (%s); logging to %s instead",
            DEFAULT_LOG_DIR,
            exc,
            log_dir,
        )

    root._reforge_configured = True
    root._reforge_log_dir = log_dir
    return root


def _add_file_handlers(
    root: logging.Logger, log_dir: Path, formatter: logging.Formatter
) -> None:
    log_dir.mkdir(parents=True, exist_ok=True)
    handlers = (
        (log_dir / "reforge.log", logging.DEBUG),
        (log_dir / "error.log", logging.ERROR),
    )
    for path, level in handlers:
        file_handler = logging.handlers.RotatingFileHandler(
            path,
            maxBytes=5 * 1024 * 1024,
            backupCount=3,
            encoding="utf-8",
        )
        file_handler.setLevel(level)
        file_handler.setFormatter(formatter)
        root.addHandler(file_handler)


_logger = None


def logger() -> logging.Logger:
    global _logger
    if _logger is None:
        _logger = setup_logger()
    return _logger


def global_exception_hook(exc_type, exc_value, exc_tb) -> None:
    tb_str = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
    active_logger = logger()
    active_logger.critical("Unhandled exception:\n%s", tb_str)

    try:
        from PyQt6.QtWidgets import QApplication, QMessageBox

        if QApplication.instance():
            log_dir = getattr(active_logger, "_reforge_log_dir", DEFAULT_LOG_DIR)
            QMessageBox.critical(
                None,
                "ReForge - Fatal Error",
                "An unexpected error occurred. "
                f"Details were written to {Path(log_dir) / 'error.log'}.",
            )
    except Exception:
        active_logger.exception("Failed to display fatal-error dialog")

    sys.__excepthook__(exc_type, exc_value, exc_tb)


def install_global_except_hook() -> None:
    sys.excepthook = global_exception_hook


def get_logger(name: str) -> logging.Logger:
    setup_logger()
    return logging.getLogger(f"reforge.{name}")
