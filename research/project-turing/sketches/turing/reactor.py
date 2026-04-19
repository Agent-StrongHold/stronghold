"""A tickable FakeReactor for research-branch tests.

Mirrors the contract that real main.Reactor exposes to producers:
per-tick event dispatch to registered handlers, deterministic under
explicit tick() calls. Not a performance fixture; just a correctness fixture.
"""

from __future__ import annotations

from collections.abc import Callable


class FakeReactor:
    def __init__(self) -> None:
        self._handlers: list[Callable[[int], None]] = []
        self.tick_count: int = 0

    def register(self, handler: Callable[[int], None]) -> None:
        self._handlers.append(handler)

    def tick(self, n: int = 1) -> None:
        for _ in range(n):
            self.tick_count += 1
            for handler in list(self._handlers):
                handler(self.tick_count)
