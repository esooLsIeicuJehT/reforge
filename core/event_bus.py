"""
ReForge Event Bus — Decoupled inter-plugin messaging backbone.
Supports typed events, priority subscribers, and wildcard listeners.
"""
from __future__ import annotations
import threading
import logging
from collections import defaultdict
from typing import Callable, Any

log = logging.getLogger("reforge.event_bus")


class Event:
    """Immutable event envelope passed to every subscriber."""
    def __init__(self, name: str, payload: dict | None = None, source: str = "unknown"):
        self.name    = name
        self.payload = payload or {}
        self.source  = source
        self._cancelled = False

    def cancel(self):
        """Cancellable events: remaining lower-priority handlers are skipped."""
        self._cancelled = True

    @property
    def cancelled(self):
        return self._cancelled

    def __repr__(self):
        return f"<Event name={self.name!r} source={self.source!r} payload={self.payload}>"


class EventBus:
    """
    Thread-safe, singleton-style event bus.

    Usage:
        bus = EventBus()
        bus.subscribe("device.connected", my_handler)
        bus.emit("device.connected", payload={"serial": "ABC123"}, source="adb_plugin")
    """

    def __init__(self):
        self._lock       = threading.Lock()
        # {event_name: [(priority, handler)]}
        self._handlers:  dict[str, list[tuple[int, Callable]]] = defaultdict(list)
        self._wildcards: list[tuple[int, Callable]] = []   # handlers subscribed to "*"

    # ------------------------------------------------------------------
    def subscribe(self, name: str, handler: Callable, priority: int = 50):
        """
        Register *handler* to receive events named *name*.
        Lower priority number = called first.  Use name="*" for all events.
        """
        with self._lock:
            if name == "*":
                self._wildcards.append((priority, handler))
                self._wildcards.sort(key=lambda x: x[0])
            else:
                self._handlers[name].append((priority, handler))
                self._handlers[name].sort(key=lambda x: x[0])
        log.debug("[BUS] subscribed %s → %s (priority=%d)", name, handler.__qualname__, priority)

    def unsubscribe(self, name: str, handler: Callable):
        with self._lock:
            if name == "*":
                self._wildcards = [(p, h) for p, h in self._wildcards if h is not handler]
            else:
                self._handlers[name] = [(p, h) for p, h in self._handlers[name] if h is not handler]

    # ------------------------------------------------------------------
    def emit(self, name: str, payload: dict | None = None, source: str = "core") -> Event:
        """
        Fire an event synchronously.  Returns the Event so callers can
        inspect whether it was cancelled.
        """
        event = Event(name, payload, source)
        log.debug("[BUS] ⚡ emit %-30s from %-20s payload=%s", name, source, payload)

        with self._lock:
            # snapshot to avoid lock re-entry issues
            handlers  = list(self._handlers.get(name, []))
            wildcards = list(self._wildcards)

        for _, handler in handlers + wildcards:
            if event.cancelled:
                break
            try:
                handler(event)
            except Exception as exc:
                log.exception("[BUS] handler %s raised during event %r: %s",
                              handler.__qualname__, name, exc)
        return event

    def emit_async(self, name: str, payload: dict | None = None, source: str = "core"):
        """Fire the event in a daemon thread (fire-and-forget)."""
        t = threading.Thread(target=self.emit, args=(name, payload, source), daemon=True)
        t.start()

    # Convenience shorthand used by plugins
    def on(self, name: str, priority: int = 50):
        """Decorator — @bus.on('some.event')"""
        def decorator(fn: Callable):
            self.subscribe(name, fn, priority)
            return fn
        return decorator


# Global singleton every module can import directly
bus = EventBus()
