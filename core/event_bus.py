"""Thread-safe in-process event bus used by ReForge plugins."""
from __future__ import annotations

import logging
import threading
from collections import defaultdict
from typing import Callable

log = logging.getLogger("reforge.event_bus")


class Event:
    """Event envelope passed to subscribers."""

    def __init__(self, name: str, payload: dict | None = None, source: str = "unknown"):
        self.name = name
        self.payload = payload or {}
        self.source = source
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    @property
    def cancelled(self) -> bool:
        return self._cancelled

    def __repr__(self) -> str:
        return (
            f"<Event name={self.name!r} source={self.source!r} "
            f"payload={self.payload}>"
        )


class EventBus:
    """Thread-safe synchronous event dispatcher with priorities and wildcards."""

    def __init__(self):
        self._lock = threading.Lock()
        self._handlers: dict[str, list[tuple[int, Callable]]] = defaultdict(list)
        self._wildcards: list[tuple[int, Callable]] = []

    def subscribe(self, name: str, handler: Callable, priority: int = 50) -> None:
        with self._lock:
            target = self._wildcards if name == "*" else self._handlers[name]
            if any(existing == handler for _, existing in target):
                return
            target.append((priority, handler))
            target.sort(key=lambda item: item[0])

        log.debug(
            "[BUS] subscribed %s -> %s (priority=%d)",
            name,
            getattr(handler, "__qualname__", repr(handler)),
            priority,
        )

    def unsubscribe(self, name: str, handler: Callable) -> None:
        with self._lock:
            if name == "*":
                self._wildcards = [
                    (priority, existing)
                    for priority, existing in self._wildcards
                    if existing != handler
                ]
            else:
                self._handlers[name] = [
                    (priority, existing)
                    for priority, existing in self._handlers[name]
                    if existing != handler
                ]

    def emit(
        self,
        name: str,
        payload: dict | None = None,
        source: str = "core",
    ) -> Event:
        event = Event(name, payload, source)

        with self._lock:
            handlers = [
                *self._handlers.get(name, []),
                *self._wildcards,
            ]
        handlers.sort(key=lambda item: item[0])

        for _, handler in handlers:
            if event.cancelled:
                break
            try:
                handler(event)
            except Exception:
                log.exception(
                    "[BUS] handler %s raised during event %r",
                    getattr(handler, "__qualname__", repr(handler)),
                    name,
                )
        return event

    def emit_async(
        self,
        name: str,
        payload: dict | None = None,
        source: str = "core",
    ) -> threading.Thread:
        thread = threading.Thread(
            target=self.emit,
            args=(name, payload, source),
            daemon=True,
            name=f"reforge-event-{name}",
        )
        thread.start()
        return thread

    def on(self, name: str, priority: int = 50):
        def decorator(fn: Callable):
            self.subscribe(name, fn, priority)
            return fn

        return decorator


bus = EventBus()
