"""
ReForge Central Plugin Loader
———————————————————————————————————————————————
Dynamically discovers, validates, loads, and manages the lifecycle
of every plugin under plugins/.  Publishes bus events at each stage.
"""
from __future__ import annotations
import importlib
import inspect
import pkgutil
import sys
import traceback
from pathlib import Path
from typing import List, Optional

from core.logger import get_logger
from core.event_bus import bus
from core.plugin_manager import BasePlugin

log = get_logger("core.loader")

# ANSI colours for terminal boot messages
_GRN  = "\033[38;5;82m"
_RED  = "\033[38;5;196m"
_CYN  = "\033[38;5;51m"
_YEL  = "\033[38;5;226m"
_DIM  = "\033[2m"
_RST  = "\033[0m"
_BLD  = "\033[1m"

def _banner(msg: str, colour: str = _CYN):
    print(f"{colour}{_BLD}{msg}{_RST}")


class PluginRecord:
    """Metadata wrapper around a live plugin instance."""
    def __init__(self, module_name: str, instance: BasePlugin):
        self.module_name = module_name
        self.instance    = instance
        self.enabled     = True
        self.error       = None

    def __repr__(self):
        state = "OK" if self.enabled and not self.error else f"ERR:{self.error}"
        return f"<Plugin {self.module_name!r} [{state}]>"


class Loader:
    """
    Scans the plugins/ package, imports each sub-package's plugin.py,
    finds all concrete BasePlugin subclasses, and manages their lifecycle.

    Emits the following bus events:
      • plugin.discovered  — {name}
      • plugin.loaded      — {name, instance}
      • plugin.failed      — {name, error}
      • plugin.shutdown    — {name}
      • loader.complete    — {count}
    """

    def __init__(self, plugin_dir: str = "plugins"):
        self.plugin_dir   = Path(plugin_dir)
        self.records:  List[PluginRecord] = []
        self._name_map: dict[str, PluginRecord] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def discover_and_load(self) -> List[PluginRecord]:
        _banner(f"\n{'━'*58}", _DIM)
        _banner(f"  ██████╗ ███████╗███████╗ ██████╗ ██████╗  ██████╗ ███████╗", _CYN)
        _banner(f"  ██╔══██╗██╔════╝██╔════╝██╔═══██╗██╔══██╗██╔════╝ ██╔════╝", _CYN)
        _banner(f"  ██████╔╝█████╗  █████╗  ██║   ██║██████╔╝██║  ███╗█████╗  ", _CYN)
        _banner(f"  ██╔══██╗██╔══╝  ██╔══╝  ██║   ██║██╔══██╗██║   ██║██╔══╝  ", _CYN)
        _banner(f"  ██║  ██║███████╗██║     ╚██████╔╝██║  ██║╚██████╔╝███████╗", _CYN)
        _banner(f"  ╚═╝  ╚═╝╚══════╝╚═╝      ╚═════╝ ╚═╝  ╚═╝ ╚═════╝ ╚══════╝", _CYN)
        _banner(f"  Modular RE Framework — Plugin Loader v2.0", _YEL)
        _banner(f"{'━'*58}\n", _DIM)

        log.info("Scanning plugin directory: %s", self.plugin_dir.resolve())

        for _, name, is_pkg in pkgutil.iter_modules([str(self.plugin_dir)]):
            if not is_pkg:
                continue
            log.debug("%s[SCAN]%s  discovered package: %s", _YEL, _RST, name)
            bus.emit("plugin.discovered", {"name": name}, source="loader")
            self._load_package(name)

        ok_count  = sum(1 for r in self.records if r.enabled)
        err_count = len(self.records) - ok_count
        _banner(f"\n  ✔  {ok_count} plugin(s) loaded  |  ✖  {err_count} failed\n", _GRN)
        bus.emit("loader.complete", {"count": ok_count}, source="loader")
        return self.records

    def initialize_all(self, main_window):
        """Call plugin.initialize(main_window) for every loaded plugin."""
        for rec in self.records:
            if not rec.enabled:
                continue
            plugin = rec.instance
            if hasattr(plugin, "initialize"):
                try:
                    plugin.initialize(main_window)
                    log.info("%s[INIT]%s  %-30s → GUI attached", _GRN, _RST, rec.module_name)
                except Exception as exc:
                    rec.error   = str(exc)
                    rec.enabled = False
                    log.error("%s[FAIL]%s  %-30s → %s", _RED, _RST, rec.module_name, exc)

    def shutdown_all(self):
        for rec in self.records:
            try:
                if hasattr(rec.instance, "shutdown"):
                    rec.instance.shutdown()
                elif hasattr(rec.instance, "deactivate"):
                    rec.instance.deactivate()
                bus.emit("plugin.shutdown", {"name": rec.module_name}, source="loader")
                log.info("%s[DOWN]%s  %s", _YEL, _RST, rec.module_name)
            except Exception as exc:
                log.error("Error shutting down %s: %s", rec.module_name, exc)

    def get(self, name: str) -> Optional[PluginRecord]:
        return self._name_map.get(name)

    @property
    def plugins(self) -> list:
        return [r.instance for r in self.records if r.enabled]

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------
    def _load_package(self, name: str):
        module_path = f"plugins.{name}.plugin"
        try:
            mod = importlib.import_module(module_path)
        except ImportError as exc:
            log.error("%s[SKIP]%s  %s — cannot import: %s", _RED, _RST, name, exc)
            bus.emit("plugin.failed", {"name": name, "error": str(exc)}, source="loader")
            return

        found = 0
        for _, obj in inspect.getmembers(mod, inspect.isclass):
            if obj is BasePlugin:
                continue
            if not issubclass(obj, BasePlugin):
                continue
            try:
                instance = obj()
                instance.event_bus = bus          # inject shared bus
                rec = PluginRecord(name, instance)
                self.records.append(rec)
                self._name_map[name] = rec
                instance.activate()
                found += 1
                _banner(f"  {_GRN}✔{_RST}  {name:<28} {_DIM}{obj.__name__}{_RST}")
                log.info("%s[LOAD]%s  %-28s class=%s", _GRN, _RST, name, obj.__name__)
                bus.emit("plugin.loaded", {"name": name, "instance": instance}, source="loader")
            except Exception as exc:
                tb = traceback.format_exc()
                log.error("%s[FAIL]%s  %s — %s\n%s", _RED, _RST, name, exc, tb)
                bus.emit("plugin.failed", {"name": name, "error": str(exc)}, source="loader")
                rec = PluginRecord(name, None)      # type: ignore
                rec.enabled = False
                rec.error   = str(exc)
                self.records.append(rec)

        if found == 0:
            log.warning("%s[WARN]%s  %s — no BasePlugin subclass found", _YEL, _RST, name)
