import importlib
import inspect
import pkgutil
from pathlib import Path
from typing import List
import pluggy
from core.event_bus import EventBus
from core.logger import get_logger

logger = get_logger(__name__)

hookspec = pluggy.HookspecMarker("reforge")

class ReForgeHooks:
    @hookspec
    def on_plugin_loaded(self, plugin_name: str):
        pass

    @hookspec
    def on_file_opened(self, filepath: str):
        pass

    @hookspec
    def on_analysis_requested(self, filepath: str, analysis_type: str):
        pass

    @hookspec
    def register_tools(self, tool_registry: dict):
        pass

pm = pluggy.PluginManager("reforge")
pm.add_hookspecs(ReForgeHooks)

class BasePlugin:
    def __init__(self):
        self.name = self.__class__.__name__
        self.version = "0.1"
        self.enabled = True
        self.event_bus = EventBus()

    def activate(self):
        pass

    def deactivate(self):
        pass

    def get_hooks(self):
        return self

class PluginManager:
    def __init__(self, plugin_dir: str = "plugins"):
        self.plugin_dir = Path(plugin_dir)
        self.plugins: List[BasePlugin] = []
        self.discover_plugins()

    def discover_plugins(self):
        logger.info(f"Discovering plugins in {self.plugin_dir}")
        for _, name, is_pkg in pkgutil.iter_modules([str(self.plugin_dir)]):
            if not is_pkg:
                continue
            try:
                plugin_module = importlib.import_module(f"plugins.{name}.plugin")
                for _, obj in inspect.getmembers(plugin_module, inspect.isclass):
                    if issubclass(obj, BasePlugin) and obj is not BasePlugin:
                        instance = obj()
                        instance.event_bus = EventBus()
                        self.plugins.append(instance)
                        pm.register(instance)
                        instance.activate()
                        pm.hook.on_plugin_loaded(plugin_name=name)
                        logger.info(f"Loaded plugin: {name}")
            except Exception as e:
                logger.error(f"Failed to load plugin '{name}': {e}")

    def shutdown(self):
        for plugin in self.plugins:
            try:
                plugin.deactivate()
            except Exception as e:
                logger.error(f"Error deactivating {plugin.name}: {e}")