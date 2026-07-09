"""
ReForge — Main entry point.
Boots the framework, runs the central plugin Loader, launches the GUI.
"""
import sys
from PyQt6.QtWidgets import QApplication
from core.logger import install_global_except_hook, get_logger
from core.config_manager import ConfigManager
from core.loader import Loader          # ← new central loader
from gui.main_window import MainWindow

log = get_logger("main")


def main():
    install_global_except_hook()
    log.info("ReForge starting up…")

    config = ConfigManager()

    app = QApplication(sys.argv)
    app.setApplicationName("ReForge")
    app.setStyle("Fusion")

    try:
        with open("gui/dark_theme.qss") as f:
            app.setStyleSheet(f.read())
    except FileNotFoundError:
        log.warning("dark_theme.qss not found — running without custom styles")

    # ── Core loader
    loader = Loader(plugin_dir="plugins")
    loader.discover_and_load()

    # ── GUI
    main_window = MainWindow()
    main_window.show()

    loader.initialize_all(main_window)

    exit_code = app.exec()

    loader.shutdown_all()
    config.save()
    log.info("ReForge exited cleanly (code %d)", exit_code)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
