"""Display utilities — spinner, formatting helpers."""
from __future__ import annotations

import threading


class Spinner:
    """Thinking indicator that runs in a background thread until stopped."""
    _FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]

    def __init__(self, label: str = "Thinking") -> None:
        self._label = label
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._stop.clear()
        self._thread = threading.Thread(target=self._spin, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join()
        print(f"\r{' ' * (len(self._label) + 4)}\r", end="", flush=True)

    def _spin(self) -> None:
        i = 0
        while not self._stop.is_set():
            frame = self._FRAMES[i % len(self._FRAMES)]
            print(f"\r{frame} {self._label}...", end="", flush=True)
            i += 1
            self._stop.wait(0.1)
