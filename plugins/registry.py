"""Explicit allowlist of plugins shipped in production ReForge builds.

Keeping production discovery static makes frozen desktop builds deterministic
and prevents arbitrary packages dropped beside the executable from being
loaded as trusted application plugins.
"""
from __future__ import annotations

from core.plugin_manager import BasePlugin
from plugins.adb_device.plugin import ADBDevicePlugin
from plugins.analysis.plugin import AnalysisPlugin
from plugins.archiver.plugin import ArchiverPlugin
from plugins.frida_tools.plugin import FridaToolsPlugin

PLUGIN_CLASSES: tuple[tuple[str, type[BasePlugin]], ...] = (
    ("adb_device", ADBDevicePlugin),
    ("analysis", AnalysisPlugin),
    ("archiver", ArchiverPlugin),
    ("frida_tools", FridaToolsPlugin),
)
