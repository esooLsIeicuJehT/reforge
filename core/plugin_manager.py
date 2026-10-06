"""Plugin interface definitions for ReForge.

Discovery and lifecycle orchestration live in :mod:`core.loader`.  Keeping the
base interface here avoids maintaining a second competing plugin manager.
"""
from __future__ import annotations

from core.event_bus import bus


class BasePlugin:
    """Minimal interface implemented by ReForge plugins."""

    def __init__(self) -> None:
        self.name = self.__class__.__name__
        self.version = "0.1.0"
        self.enabled = True
        self.event_bus = bus

    def activate(self) -> None:
        """Register non-GUI resources or event subscriptions."""

    def deactivate(self) -> None:
        """Release resources registered by :meth:`activate`."""

    def get_hooks(self):
        """Compatibility hook for older plugins."""
        return self
