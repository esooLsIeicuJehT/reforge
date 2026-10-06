from core.event_bus import EventBus


def test_priority_and_cancellation_across_direct_and_wildcard_handlers():
    bus = EventBus()
    calls = []

    def wildcard(event):
        calls.append("wildcard")
        event.cancel()

    def direct(event):
        calls.append("direct")

    bus.subscribe("demo", direct, priority=50)
    bus.subscribe("*", wildcard, priority=10)

    event = bus.emit("demo")

    assert event.cancelled is True
    assert calls == ["wildcard"]


def test_bound_method_unsubscribe_works():
    bus = EventBus()
    calls = []

    class Listener:
        def receive(self, event):
            calls.append(event.name)

    listener = Listener()
    bus.subscribe("alpha", listener.receive)
    bus.emit("alpha")
    bus.unsubscribe("alpha", listener.receive)
    bus.emit("alpha")

    assert calls == ["alpha"]


def test_duplicate_subscription_is_ignored():
    bus = EventBus()
    calls = []

    def listener(event):
        calls.append(event.name)

    bus.subscribe("alpha", listener)
    bus.subscribe("alpha", listener)
    bus.emit("alpha")

    assert calls == ["alpha"]
