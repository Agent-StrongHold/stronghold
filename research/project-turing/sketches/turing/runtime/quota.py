"""FreeTierQuotaTracker: per-provider headroom and pressure.

Aggregates `FreeTierWindow` snapshots from registered providers and converts
them into the `pressure_vec` component feeding `Motivation.set_pressure`. One
scalar per pool.

The scalar is:

    pressure(pool) = headroom × quality_weight ÷ (time_to_reset_seconds + 1)

rising as unused tokens approach the end of their window. Saturated at
PRESSURE_MAX (from motivation module seeds; tuner adjusts at runtime).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from ..motivation import PRESSURE_MAX
from .providers.base import FreeTierWindow, Provider


logger = logging.getLogger("turing.runtime.quota")


DEFAULT_QUALITY_WEIGHT: float = 1.0
_SECONDS_PER_WINDOW_FLOOR: float = 1.0


def _pool_score(headroom: int, quality_weight: float, seconds_to_reset: float) -> float:
    return headroom * quality_weight / max(_SECONDS_PER_WINDOW_FLOOR, seconds_to_reset)


@dataclass(frozen=True)
class ProviderRegistration:
    provider: Provider
    quality_weight: float = DEFAULT_QUALITY_WEIGHT


class FreeTierQuotaTracker:
    """Tracks per-provider quota and emits a pressure scalar per pool.

    Not thread-safe. Called from the reactor's main thread during on_tick;
    providers themselves live in executor workers, which update their own
    windows when they make calls.
    """

    def __init__(self) -> None:
        self._registrations: dict[str, ProviderRegistration] = {}

    def register(
        self,
        provider: Provider,
        *,
        quality_weight: float = DEFAULT_QUALITY_WEIGHT,
    ) -> None:
        self._registrations[provider.name] = ProviderRegistration(
            provider=provider, quality_weight=quality_weight
        )

    def providers(self) -> dict[str, Provider]:
        return {name: reg.provider for name, reg in self._registrations.items()}

    def window(self, pool_name: str) -> FreeTierWindow | None:
        reg = self._registrations.get(pool_name)
        if reg is None:
            return None
        return reg.provider.quota_window()

    def pressure_for(self, pool_name: str) -> float:
        reg = self._registrations.get(pool_name)
        if reg is None:
            return 0.0
        window = reg.provider.quota_window()
        if window is None:
            return 0.0
        if window.headroom <= 0:
            return 0.0
        now = datetime.now(UTC)
        seconds_to_reset = (window.window_ends_at - now).total_seconds()
        raw = _pool_score(window.headroom, reg.quality_weight, seconds_to_reset)
        return min(raw, PRESSURE_MAX)

    def pressure_vec(self) -> dict[str, float]:
        return {pool_name: self.pressure_for(pool_name) for pool_name in self._registrations}

    def select_best_provider(self) -> str | None:
        best_name: str | None = None
        best_score: float = 0.0
        now = datetime.now(UTC)
        for pool_name, reg in self._registrations.items():
            window = reg.provider.quota_window()
            if window is None or window.headroom <= 0:
                continue
            seconds_to_reset = (window.window_ends_at - now).total_seconds()
            score = _pool_score(window.headroom, reg.quality_weight, seconds_to_reset)
            if score > best_score:
                best_score = score
                best_name = pool_name
        return best_name
