"""ReForge application entry point."""
from __future__ import annotations

import sys

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from core.config_manager import ConfigManager
from core.loader import Loader
from core.logger import get_logger, install_global_except_hook
from gui.main_window import MainWindow
from gui.theme import DARK_THEME

log = get_logger("main")


def main() -> int:
    install_global_except_hook()
    log.info("ReForge starting up")

    smoke_test = "--smoke-test" in sys.argv
    qt_args = [arg for arg in sys.argv if arg != "--smoke-test"]

    config = ConfigManager()
    app = QApplication(qt_args)
    app.setApplicationName("ReForge")
    app.setOrganizationName("ReForge")
    app.setStyle("Fusion")
    app.setStyleSheet(DARK_THEME)

    # Production builds use the explicit trusted plugin registry. This avoids
    # filesystem scanning assumptions and keeps frozen bundles deterministic.
    loader = Loader()
    exit_code = 1

    try:
        loader.discover_and_load()
        main_window = MainWindow(config)
        main_window.show()
        loader.initialize_all(main_window)

        if smoke_test:
            log.info("Smoke-test mode enabled; scheduling clean shutdown")
            QTimer.singleShot(750, app.quit)

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
