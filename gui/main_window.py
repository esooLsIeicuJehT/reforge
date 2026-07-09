"""
ReForge Main Window — full dock layout with menu integration.
"""
import logging

from PyQt6.QtWidgets import (
    QMainWindow, QDockWidget, QTextEdit, QMenu,
    QStatusBar, QLabel
)
from PyQt6.QtGui import QAction
from PyQt6.QtCore import Qt, QObject, pyqtSignal
from PyQt6.QtGui import QFont
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

    def emit(self, record: logging.LogRecord):
        self._emitter.message.emit(self.format(record))


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("ReForge  ░  Modular RE Toolkit")
        self.resize(1440, 900)
        self.setDockOptions(
            QMainWindow.DockOption.AllowTabbedDocks |
            QMainWindow.DockOption.AnimatedDocks
        )

        # Central welcome area
        self.central_text = QTextEdit()
        self.central_text.setReadOnly(True)
        self.central_text.setFont(QFont("Monospace", 10))
        self.central_text.setHtml(
            "<h2 style='color:#82aaff'>ReForge — Modular Reverse Engineering Framework</h2>"
            "<p style='color:#c3e88d'>Plugins are loading into the dock panels…</p>"
            "<p style='color:#546e7a'>Use the <b>Plugins</b> menu to show/hide panels.</p>"
        )
        self.setCentralWidget(self.central_text)

        # Bottom log dock
        self.log_dock   = QDockWidget("System Logs", self)
        self.log_widget = QTextEdit()
        self.log_widget.setReadOnly(True)
        self.log_widget.setFont(QFont("Monospace", 8))
        self.log_dock.setWidget(self.log_widget)
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, self.log_dock)
        self._install_log_handler()

        # Status bar
        self._status = QStatusBar()
        self.setStatusBar(self._status)
        self._device_label = QLabel("No device")
        self._status.addPermanentWidget(self._device_label)

        # Menu bar
        mb = self.menuBar()
        self.plugins_menu = mb.addMenu("Plugins")
        view_menu = mb.addMenu("View")
        log_action = QAction("System Logs", self, checkable=True, checked=True)
        log_action.toggled.connect(self.log_dock.setVisible)
        view_menu.addAction(log_action)

        self._docks: dict[str, QDockWidget] = {}

        # Subscribe to device events for status bar
        bus.subscribe("device.connected",    self._on_device_connected)
        bus.subscribe("device.disconnected", self._on_device_disconnected)
        bus.subscribe("loader.complete",     self._on_loader_complete)
        log.info("[GUI] main window initialized")

    # ── Public API used by plugins ────────────────────────────────────
    def add_plugin_dock(self, title: str, widget,
                        area=Qt.DockWidgetArea.RightDockWidgetArea) -> QDockWidget:
        dock = QDockWidget(title, self)
        dock.setObjectName(f"dock_{title.replace(' ', '_')}")
        dock.setWidget(widget)
        self.addDockWidget(area, dock)

        # Tabify with existing docks in the same area
        same_area = [d for d in self._docks.values()
                     if self.dockWidgetArea(d) == area]
        if same_area:
            self.tabifyDockWidget(same_area[-1], dock)

        self._docks[title] = dock

        # Add toggle action to Plugins menu
        action = dock.toggleViewAction()
        action.setText(title)
        self.plugins_menu.addAction(action)

        log.info("[GUI] dock added: %s  area=%s", title, area)
        return dock

    def log(self, message: str):
        self.log_widget.append(message)

    def _install_log_handler(self):
        formatter = logging.Formatter(
            "%(asctime)s %(levelname)-8s %(name)-35s %(message)s",
            datefmt="%H:%M:%S",
        )
        handler = _GuiLogHandler(self.log_widget)
        handler.setFormatter(formatter)
        logging.getLogger("reforge").addHandler(handler)
        self._gui_log_handler = handler

    # ── Bus handlers ─────────────────────────────────────────────────
    def _on_device_connected(self, event):
        serial = event.payload.get("serial", "?")
        self._device_label.setText(f"Device: {serial}")
        self.statusBar().showMessage(f"Device connected: {serial}", 4000)
        log.info("[GUI] device connected status updated: %s", serial)

    def _on_device_disconnected(self, event):
        self._device_label.setText("No device")
        self.statusBar().showMessage("Device disconnected", 3000)
        log.info("[GUI] device disconnected status updated")

    def _on_loader_complete(self, event):
        count = event.payload.get("count", 0)
        self.statusBar().showMessage(f"✔  {count} plugin(s) loaded", 5000)
        log.info("[GUI] loader complete: %d plugin(s)", count)
