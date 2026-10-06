from types import SimpleNamespace

from core.event_bus import bus
from core.loader import Loader, PluginRecord
from core.plugin_manager import BasePlugin


def _module_with(plugin_class):
    return SimpleNamespace(Plugin=plugin_class)


def test_activation_failure_creates_only_disabled_failure_record(monkeypatch):
    cleanup = {"called": False}
    failures = []

    class FailingPlugin(BasePlugin):
        def activate(self):
            raise RuntimeError("activation exploded")

        def shutdown(self):
            cleanup["called"] = True

    monkeypatch.setattr(
        "core.loader.importlib.import_module",
        lambda _name: _module_with(FailingPlugin),
    )

    def on_failure(event):
        failures.append(event.payload)

    bus.subscribe("plugin.failed", on_failure)
    try:
        loader = Loader()
        loader._load_package("failing")
    finally:
        bus.unsubscribe("plugin.failed", on_failure)

    assert len(loader.records) == 1
    record = loader.records[0]
    assert record.module_name == "failing"
    assert record.instance is None
    assert record.enabled is False
    assert record.stage == "activate"
    assert record.error == "activation exploded"
    assert loader.plugins == []
    assert cleanup["called"] is True
    assert failures[-1]["stage"] == "activate"


def test_successful_plugin_is_recorded_after_activation(monkeypatch):
    state = {"activated": False}

    class GoodPlugin(BasePlugin):
        def activate(self):
            state["activated"] = True

    monkeypatch.setattr(
        "core.loader.importlib.import_module",
        lambda _name: _module_with(GoodPlugin),
    )

    loader = Loader()
    loader._load_package("good")

    assert state["activated"] is True
    assert len(loader.records) == 1
    assert loader.records[0].enabled is True
    assert isinstance(loader.records[0].instance, GoodPlugin)
    assert loader.get("good") is loader.records[0]
    assert loader.plugins == [loader.records[0].instance]


def test_shutdown_failure_does_not_block_other_plugins():
    state = {"bad": 0, "good": 0}
    failures = []

    class GoodPlugin(BasePlugin):
        def shutdown(self):
            state["good"] += 1

    class BadPlugin(BasePlugin):
        def shutdown(self):
            state["bad"] += 1
            raise RuntimeError("shutdown exploded")

    loader = Loader()
    good = PluginRecord("good", GoodPlugin())
    bad = PluginRecord("bad", BadPlugin())
    loader.records = [good, bad]

    def on_failure(event):
        failures.append(event.payload)

    bus.subscribe("plugin.failed", on_failure)
    try:
        loader.shutdown_all()
    finally:
        bus.unsubscribe("plugin.failed", on_failure)

    assert state == {"bad": 1, "good": 1}
    assert good.enabled is False
    assert good.stage == "shutdown"
    assert bad.enabled is False
    assert bad.stage == "shutdown"
    assert bad.error == "shutdown exploded"
    assert failures[-1]["stage"] == "shutdown"
