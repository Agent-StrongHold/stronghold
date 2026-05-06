"""Effect stack render pipeline (spec §01).

`EffectStackRenderer` applies a Layer's ordered Effect tuple head-to-tail
through an `EffectApplier`, with a process-local LRU cache keyed on
(source_hash, effects_hash). Disabled effects are filtered out before
hashing so toggling a disabled-no-op stays a cache hit.

This is the runtime the §01 Gherkin scenarios assume:
  - Empty stack renders source unchanged
  - Disabled effects are skipped during render
  - Re-ordering produces different bytes (when effects are non-commutative)
  - Same logical state → byte-identical render
  - Cache hit on identical input
  - Cache invalidation on stack mutation
"""

from __future__ import annotations

import hashlib
import json
from collections import OrderedDict
from typing import TYPE_CHECKING

from stronghold.types.errors import EffectStackOverflowError

if TYPE_CHECKING:
    from collections.abc import Sequence

    from stronghold.protocols.canvas_design import EffectApplier
    from stronghold.types.canvas_design import Effect


# Soft cap mirrors types.canvas_design.MAX_EFFECTS_PER_LAYER, repeated here
# to avoid a circular import at runtime when the renderer is imported by
# the layer-rendering pipeline.
_MAX_STACK = 32


class EffectStackRenderer:
    """Applies an ordered effect stack with a small LRU cache.

    Cache size is per-instance; the default 64 entries is enough for a
    32-layer page edited iteratively.
    """

    def __init__(self, applier: EffectApplier, *, cache_size: int = 64) -> None:
        self._applier = applier
        self._cache: OrderedDict[str, bytes] = OrderedDict()
        self._cache_size = cache_size
        self.hits = 0
        self.misses = 0

    def render(self, source: bytes, effects: Sequence[Effect]) -> bytes:
        if len(effects) > _MAX_STACK:
            raise EffectStackOverflowError(
                f"effect stack length {len(effects)} exceeds {_MAX_STACK}"
            )
        active = tuple(e for e in effects if e.enabled)
        key = self._cache_key(source, active)
        cached = self._cache.get(key)
        if cached is not None:
            self.hits += 1
            self._cache.move_to_end(key)
            return cached
        self.misses += 1
        result = source
        for effect in active:
            result = self._applier.apply(result, effect)
        self._cache[key] = result
        if len(self._cache) > self._cache_size:
            self._cache.popitem(last=False)
        return result

    def reset_metrics(self) -> None:
        self.hits = 0
        self.misses = 0

    def clear_cache(self) -> None:
        self._cache.clear()

    @staticmethod
    def _cache_key(source: bytes, active_effects: Sequence[Effect]) -> str:
        src_hash = hashlib.sha256(source).hexdigest()
        # Normalise effect params to a stable JSON string for hashing.
        # `params` may contain ints/floats — json.dumps handles both.
        effect_payload = [
            {"id": e.id, "kind": e.kind.value, "params": _normalise_params(e.params)}
            for e in active_effects
        ]
        eff_blob = json.dumps(effect_payload, sort_keys=True, separators=(",", ":")).encode()
        eff_hash = hashlib.sha256(eff_blob).hexdigest()
        return f"{src_hash}:{eff_hash}"


def _normalise_params(params: dict[str, object]) -> dict[str, object]:
    """JSON-stable normalisation: bools first, then numerics, sorted keys."""
    return {k: params[k] for k in sorted(params)}
