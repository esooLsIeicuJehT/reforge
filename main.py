"""ReForge application entry point."""
from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication

from core.config_manager import ConfigManager
from core.loader import Loader
from core.logger import get_logger, install_global_except_hook
from gui.main_window import MainWindow

APP_ROOT = Path(__file__).resolve().parent
log = get_logger("main")


def main() -> int:
    install_global_except_hook()
    log.info("ReForge starting up")

    config = ConfigManager()
    app = QApplication(sys.argv)
    app.setApplicationName("ReForge")
    app.setOrganizationName("ReForge")
    app.setStyle("Fusion")

    stylesheet = APP_ROOT / "gui" / "dark_theme.qss"
    try:
        app.setStyleSheet(stylesheet.read_text(encoding="utf-8"))
    except OSError as exc:
        log.warning("Could not load %s: %s", stylesheet, exc)

    loader = Loader(plugin_dir=APP_ROOT / "plugins")
    exit_code = 1

    try:
        loader.discover_and_load()
        main_window = MainWindow(config)
        main_window.show()
        loader.initialize_all(main_window)
        exit_code = app.exec()
        return exit_code
    finally:
        loader.shutdown_all()
        try:
            config.save()
        except OSError:
            log.exception("Failed to save configuration")
        log.info("ReForge exited (code %d)", exit_code)


if __name__ == "__main__":
    raise SystemExit(main())
