"""Persistent user configuration for ReForge."""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

log = logging.getLogger("reforge.config")


class ConfigManager:
    """Load and atomically persist per-user configuration."""

    DEFAULTS: dict[str, Any] = {
        "last_file": "",
        "plugin_states": {},
        "window_geometry": None,
    }

    def __init__(self, config_dir: str | Path | None = None):
        self.config_dir = Path(config_dir) if config_dir else Path.home() / ".reforge"
        self.config_file = self.config_dir / "settings.json"
        self.config: dict[str, Any] = dict(self.DEFAULTS)
        self.config_dir.mkdir(parents=True, exist_ok=True)
        self.load()

    def load(self) -> dict[str, Any]:
        if not self.config_file.exists():
            return self.config

        try:
            with self.config_file.open("r", encoding="utf-8") as fh:
                loaded = json.load(fh)
            if not isinstance(loaded, dict):
                raise ValueError("settings.json must contain a JSON object")
            self.config.update(loaded)
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            backup = self._quarantine_corrupt_config()
            log.warning(
                "Could not load %s (%s). Using defaults%s.",
                self.config_file,
                exc,
                f"; corrupt file moved to {backup}" if backup else "",
            )
        return self.config

    def save(self) -> None:
        self.config_dir.mkdir(parents=True, exist_ok=True)
        temp_file = self.config_file.with_suffix(".json.tmp")

        with temp_file.open("w", encoding="utf-8") as fh:
            json.dump(self.config, fh, indent=2, sort_keys=True)
            fh.write("\n")
            fh.flush()
            os.fsync(fh.fileno())

        os.replace(temp_file, self.config_file)
        try:
            self.config_file.chmod(0o600)
        except OSError:
            pass

    def _quarantine_corrupt_config(self) -> Path | None:
        if not self.config_file.exists():
            return None
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        backup = self.config_file.with_name(f"settings.corrupt-{stamp}.json")
        try:
            self.config_file.replace(backup)
            return backup
        except OSError:
            return None
