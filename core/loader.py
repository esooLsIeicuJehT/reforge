"""Central plugin discovery and lifecycle management for ReForge."""
from __future__ import annotations

import importlib
import inspect
import pkgutil
from pathlib import Path
from typing import Iterable, List, Optional

from core.event_bus import bus
from core.logger import get_logger
from core.plugin_manager import BasePlugin
from plugins.registry import PLUGIN_CLASSES

log = get_logger("core.loader")

_GRN = "\033[38;5;82m"
_RED = "\033[38;5;196m"
_CYN = "\033[38;5;51m"
_YEL = "\033[38;5;226m"
_DIM = "\033[2m"
_RST = "\033[0m"
_BLD = "\033[1m"


def _banner(msg: str, colour: str = _CYN) -> None:
    print(f"{colour}{_BLD}{msg}{_RST}")


class PluginRecord:
    """Lifecycle metadata for one plugin class."""

    def __init__(
        self,
        module_name: str,
        instance: BasePlugin | None = None,
        *,
        enabled: bool = True,
        error: str | None = None,
        stage: str | None = None,
    ) -> None:
        self.module_name = module_name
        self.instance = instance
        self.enabled = enabled and instance is not None
        self.error = error
        self.stage = stage

    def __repr__(self) -> str:
        if self.enabled and not self.error:
            state = "OK"
        else:
            stage = f"@{self.stage}" if self.stage else ""
            state = f"ERR{stage}:{self.error}"
        return f"<Plugin {self.module_name!r} [{state}]>"


class Loader:
    """Activate, initialize, and shut down ReForge plugins.

    Production builds use the explicit registry in :mod:`plugins.registry`.
    ``plugin_dir`` remains available for development/tests that intentionally
    exercise package discovery from a source tree.
    """

    def __init__(
        self,
        plugin_dir: str | Path | None = None,
        plugin_classes: Iterable[tuple[str, type[BasePlugin]]] | None = None,
    ) -> None:
        self.plugin_dir = Path(plugin_dir) if plugin_dir is not None else None
        self.plugin_classes = tuple(plugin_classes) if plugin_classes is not None else None
        self.records: List[PluginRecord] = []
        self._name_map: dict[str, PluginRecord] = {}

    def discover_and_load(self) -> List[PluginRecord]:
        """Load the trusted registry or an explicit development plugin path."""
        self.records.clear()
        self._name_map.clear()

        _banner(f"\n{'━' * 58}", _DIM)
        _banner("  ReForge Modular RE Framework — Plugin Loader v2.2", _CYN)
        _banner(f"{'━' * 58}\n", _DIM)

        if self.plugin_classes is not None:
            candidates = self.plugin_classes
            log.info("Loading %d explicitly supplied plugin class(es)", len(candidates))
            for name, plugin_class in candidates:
                bus.emit("plugin.discovered", {"name": name}, source="loader")
                self._activate_class(name, plugin_class)
        elif self.plugin_dir is not None:
            self._discover_source_plugins()
        else:
            log.info("Loading trusted production plugin registry")
            for name, plugin_class in PLUGIN_CLASSES:
                bus.emit("plugin.discovered", {"name": name}, source="loader")
                self._activate_class(name, plugin_class)

        ok_count = sum(1 for record in self.records if record.enabled)
        err_count = len(self.records) - ok_count
        _banner(f"\n  ✔  {ok_count} plugin(s) loaded  |  ✖  {err_count} failed\n", _GRN)
        bus.emit(
            "loader.complete",
            {"count": ok_count, "failed": err_count},
            source="loader",
        )
        return self.records

    def initialize_all(self, main_window) -> None:
        """Attach every successfully activated plugin to the GUI."""
        for record in self.records:
            plugin = record.instance
            if not record.enabled or plugin is None:
                continue
            if not hasattr(plugin, "initialize"):
                continue

            try:
                plugin.initialize(main_window)
                log.info("%s[INIT]%s  %-30s -> GUI attached", _GRN, _RST, record.module_name)
            except Exception as exc:
                record.error = str(exc)
                record.stage = "initialize"
                record.enabled = False
                log.exception("%s[FAIL]%s  %-30s -> %s", _RED, _RST, record.module_name, exc)
                self._emit_failure(record.module_name, exc, "initialize")
                self._cleanup_instance(plugin, record.module_name, "initialize-cleanup")

    def shutdown_all(self) -> None:
        """Shut down live plugins without allowing one failure to stop the rest."""
        for record in reversed(self.records):
            plugin = record.instance
            if not record.enabled or plugin is None:
                continue

            try:
                if hasattr(plugin, "shutdown"):
                    plugin.shutdown()
                elif hasattr(plugin, "deactivate"):
                    plugin.deactivate()
                record.enabled = False
                record.stage = "shutdown"
                bus.emit("plugin.shutdown", {"name": record.module_name}, source="loader")
                log.info("%s[DOWN]%s  %s", _YEL, _RST, record.module_name)
            except Exception as exc:
                record.error = str(exc)
                record.stage = "shutdown"
                record.enabled = False
                log.exception("Error shutting down %s: %s", record.module_name, exc)
                self._emit_failure(record.module_name, exc, "shutdown")

    def get(self, name: str) -> Optional[PluginRecord]:
        return self._name_map.get(name)

    @property
    def plugins(self) -> list[BasePlugin]:
        return [
            record.instance
            for record in self.records
            if record.enabled and record.instance is not None
        ]

    def _discover_source_plugins(self) -> None:
        """Development-only filesystem discovery used by focused tests/tools."""
        assert self.plugin_dir is not None
        if not self.plugin_dir.exists():
            log.warning("Plugin directory does not exist: %s", self.plugin_dir)
            return

        log.info("Scanning explicit plugin directory: %s", self.plugin_dir.resolve())
        for _, name, is_pkg in pkgutil.iter_modules([str(self.plugin_dir)]):
            if not is_pkg or name == "registry":
                continue
            bus.emit("plugin.discovered", {"name": name}, source="loader")
            self._load_package(name)

    def _load_package(self, name: str) -> None:
        """Import one source-tree plugin package for development/testing."""
        module_path = f"plugins.{name}.plugin"
        try:
            module = importlib.import_module(module_path)
        except Exception as exc:
            log.exception("%s[SKIP]%s  %s -> cannot import: %s", _RED, _RST, name, exc)
            self._record_failure(name, exc, "import")
            return

        plugin_classes = [
            obj
            for _, obj in inspect.getmembers(module, inspect.isclass)
            if obj is not BasePlugin and issubclass(obj, BasePlugin)
        ]
        if not plugin_classes:
            log.warning("%s[WARN]%s  %s -> no BasePlugin subclass found", _YEL, _RST, name)
            return

        for plugin_class in plugin_classes:
            self._activate_class(name, plugin_class)

    def _activate_class(self, name: str, plugin_class: type[BasePlugin]) -> None:
        try:
            instance = plugin_class()
        except Exception as exc:
            log.exception("%s[FAIL]%s  %s -> construction failed: %s", _RED, _RST, name, exc)
            self._record_failure(name, exc, "construct")
            return

        instance.event_bus = bus
        try:
            instance.activate()
        except Exception as exc:
            log.exception("%s[FAIL]%s  %s -> activation failed: %s", _RED, _RST, name, exc)
            self._cleanup_instance(instance, name, "activation-cleanup")
            self._record_failure(name, exc, "activate")
            return

        record = PluginRecord(name, instance, enabled=True)
        self.records.append(record)
        self._name_map[name] = record
        _banner(f"  {_GRN}✔{_RST}  {name:<28} {_DIM}{plugin_class.__name__}{_RST}")
        log.info("%s[LOAD]%s  %-28s class=%s", _GRN, _RST, name, plugin_class.__name__)
        bus.emit(
            "plugin.loaded",
            {"name": name, "instance": instance},
            source="loader",
        )

    def _record_failure(self, name: str, exc: Exception, stage: str) -> PluginRecord:
        record = PluginRecord(
            name,
            None,
            enabled=False,
            error=str(exc),
            stage=stage,
        )
        self.records.append(record)
        self._name_map[name] = record
        self._emit_failure(name, exc, stage)
        return record

    @staticmethod
    def _emit_failure(name: str, exc: Exception, stage: str) -> None:
        bus.emit(
            "plugin.failed",
            {"name": name, "error": str(exc), "stage": stage},
            source="loader",
        )

    @staticmethod
    def _cleanup_instance(instance: BasePlugin, name: str, stage: str) -> None:
        """Best-effort cleanup for a partially activated/initialized plugin."""
        try:
            if hasattr(instance, "shutdown"):
                instance.shutdown()
            elif hasattr(instance, "deactivate"):
                instance.deactivate()
        except Exception:
            log.exception("Cleanup failed for plugin %s during %s", name, stage)
