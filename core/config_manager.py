import json
from pathlib import Path

CONFIG_DIR = Path.home() / ".reforge"
CONFIG_FILE = CONFIG_DIR / "settings.json"

class ConfigManager:
    def __init__(self):
        self.config = {
            "last_file": "",
            "plugin_states": {},
            "window_geometry": None
        }
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        self.load()

    def load(self):
        if CONFIG_FILE.exists():
            with open(CONFIG_FILE, "r") as f:
                self.config.update(json.load(f))

    def save(self):
        with open(CONFIG_FILE, "w") as f:
            json.dump(self.config, f, indent=4)