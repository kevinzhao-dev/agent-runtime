"""In-process event bus.

A tiny fan-out: the query loop publishes events once, and any number of
subscribers (display renderer, transcript writer, future TUI, ...) receive
them. No async, no queues — callbacks run inline in publish order.
"""
from __future__ import annotations

from typing import Any, Callable

Subscriber = Callable[[Any], None]


class EventBus:
    def __init__(self) -> None:
        self._subs: list[Subscriber] = []

    def subscribe(self, callback: Subscriber) -> None:
        self._subs.append(callback)

    def publish(self, event: Any) -> None:
        for cb in self._subs:
            try:
                cb(event)
            except Exception as e:
                print(f"\n[bus] subscriber error: {e}")
