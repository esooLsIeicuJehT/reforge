import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from core.config_manager import ConfigManager
from core.loader import Loader
from gui.main_window import MainWindow


def test_supported_plugins_initialize_offscreen(tmp_path):
    app = QApplication.instance() or QApplication([])
    config = ConfigManager(config_dir=tmp_path / "config")
    loader = Loader()

    records = loader.discover_and_load()
    failures = [record for record in records if not record.enabled]
    assert failures == []

    loaded_names = {record.module_name for record in records}
    assert loaded_names == {"adb_device", "analysis", "archiver", "frida_tools"}

    window = MainWindow(config)
    try:
        loader.initialize_all(window)
        init_failures = [record for record in records if not record.enabled]
        assert init_failures == []
        assert set(window._docks) == {"ADB Device", "Analysis", "Archiver", "Frida Tools"}
        app.processEvents()
    finally:
        loader.shutdown_all()
        window.close()
        app.processEvents()
