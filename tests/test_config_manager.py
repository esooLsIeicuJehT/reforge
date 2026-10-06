import json

from core.config_manager import ConfigManager


def test_config_round_trip(tmp_path):
    manager = ConfigManager(tmp_path)
    manager.config["last_file"] = "/tmp/example.bin"
    manager.save()

    loaded = ConfigManager(tmp_path)
    assert loaded.config["last_file"] == "/tmp/example.bin"
    assert loaded.config["plugin_states"] == {}


def test_corrupt_config_is_quarantined(tmp_path):
    settings = tmp_path / "settings.json"
    settings.write_text("{ definitely not json", encoding="utf-8")

    manager = ConfigManager(tmp_path)

    assert manager.config["last_file"] == ""
    assert not settings.exists()
    backups = list(tmp_path.glob("settings.corrupt-*.json"))
    assert len(backups) == 1


def test_non_object_config_is_rejected(tmp_path):
    (tmp_path / "settings.json").write_text(json.dumps(["bad"]), encoding="utf-8")

    manager = ConfigManager(tmp_path)

    assert manager.config["plugin_states"] == {}
