"""ReForge main application window."""
from __future__ import annotations

import logging

from PyQt6.QtCore import QByteArray, QObject, Qt, pyqtSignal
from PyQt6.QtGui import QAction, QCloseEvent, QFont
from PyQt6.QtWidgets import QDockWidget, QLabel, QMainWindow, QStatusBar, QTextEdit

from core.config_manager import ConfigManager
from core.event_bus import bus
from core.logger import get_logger

log = get_logger("gui.main_window")


class _LogEmitter(QObject):
    message = pyqtSignal(str)


class _GuiLogHandler(logging.Handler):
    def __init__(self, target: QTextEdit):
        super().__init__(logging.DEBUG)
        self._emitter = _LogEmitter()
        self._emitter.message.connect(target.append)

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self._emitter.message.emit(self.format(record))
        except RuntimeError:
            return


class MainWindow(QMainWindow):
    def __init__(self, config: ConfigManager | None = None):
        super().__init__()
        self._config = config

        self.setWindowTitle("ReForge • Modular RE Toolkit")
        self.resize(1440, 900)
        self.setDockOptions(
            QMainWindow.DockOption.AllowTabbedDocks
            | QMainWindow.DockOption.AnimatedDocks
        )
        self._restore_geometry()

        self.central_text = QTextEdit()
        self.central_text.setReadOnly(True)
        self.central_text.setFont(QFont("Monospace", 10))
        self.central_text.setHtml(
            "<h2 style='color:#82aaff'>ReForge</h2>"
            "<p style='color:#c3e88d'>Modular reverse-engineering workspace.</p>"
            "<p style='color:#546e7a'>Use the <b>Plugins</b> menu to show or hide panels.</p>"
        )
        self.setCentralWidget(self.central_text)

        self.log_dock = QDockWidget("System Logs", self)
        self.log_widget = QTextEdit()
        self.log_widget.setReadOnly(True)
        self.log_widget.setFont(QFont("Monospace", 8))
        self.log_dock.setWidget(self.log_widget)
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, self.log_dock)
        self._install_log_handler()

        self._status = QStatusBar()
        self.setStatusBar(self._status)
        self._device_label = QLabel("No device")
        self._status.addPermanentWidget(self._device_label)

        menu_bar = self.menuBar()
        self.plugins_menu = menu_bar.addMenu("Plugins")
        view_menu = menu_bar.addMenu("View")
        log_action = QAction("System Logs", self, checkable=True, checked=True)
        log_action.toggled.connect(self.log_dock.setVisible)
        view_menu.addAction(log_action)

        self._docks: dict[str, QDockWidget] = {}

        bus.subscribe("device.connected", self._on_device_connected)
        bus.subscribe("device.disconnected", self._on_device_disconnected)
        bus.subscribe("loader.complete", self._on_loader_complete)
        log.info("[GUI] main window initialized")

    def add_plugin_dock(
        self,
        title: str,
        widget,
        area=Qt.DockWidgetArea.RightDockWidgetArea,
    ) -> QDockWidget:
        dock = QDockWidget(title, self)
        dock.setObjectName(f"dock_{title.replace(' ', '_')}")
        dock.setWidget(widget)
        self.addDockWidget(area, dock)

        same_area = [
            existing
            for existing in self._docks.values()
            if self.dockWidgetArea(existing) == area
        ]
        if same_area:
            self.tabifyDockWidget(same_area[-1], dock)

        self._docks[title] = dock
        action = dock.toggleViewAction()
        action.setText(title)
        self.plugins_menu.addAction(action)
        log.info("[GUI] dock added: %s area=%s", title, area)
        return dock

    def log(self, message: str) -> None:
        self.log_widget.append(message)

    def _install_log_handler(self) -> None:
        formatter = logging.Formatter(
            "%(asctime)s %(levelname)-8s %(name)-35s %(message)s",
            datefmt="%H:%M:%S",
        )
        handler = _GuiLogHandler(self.log_widget)
        handler.setFormatter(formatter)
        logging.getLogger("reforge").addHandler(handler)
        self._gui_log_handler = handler

    def _restore_geometry(self) -> None:
        if self._config is None:
            return
        value = self._config.config.get("window_geometry")
        if not isinstance(value, str) or not value:
            return
        try:
            self.restoreGeometry(QByteArray.fromHex(value.encode("ascii")))
        except (ValueError, TypeError):
            log.warning("Ignoring invalid saved window geometry")

    def _persist_geometry(self) -> None:
        if self._config is not None:
            self._config.config["window_geometry"] = bytes(
                self.saveGeometry().toHex()
            ).decode("ascii")

    def _on_device_connected(self, event) -> None:
        serial = event.payload.get("serial", "?")
        self._device_label.setText(f"Device: {serial}")
        self.statusBar().showMessage(f"Device connected: {serial}", 4000)

    def _on_device_disconnected(self, event) -> None:
        self._device_label.setText("No device")
        self.statusBar().showMessage("Device disconnected", 3000)

    def _on_loader_complete(self, event) -> None:
        count = event.payload.get("count", 0)
        failed = event.payload.get("failed", 0)
        message = f"{count} plugin(s) loaded"
        if failed:
            message += f", {failed} failed"
        self.statusBar().showMessage(message, 5000)

    def closeEvent(self, event: QCloseEvent) -> None:
        self._persist_geometry()
        bus.unsubscribe("device.connected", self._on_device_connected)
        bus.unsubscribe("device.disconnected", self._on_device_disconnected)
        bus.unsubscribe("loader.complete", self._on_loader_complete)

        root_logger = logging.getLogger("reforge")
        root_logger.removeHandler(self._gui_log_handler)
        self._gui_log_handler.close()

        super().closeEvent(event)
