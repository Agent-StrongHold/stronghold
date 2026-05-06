"""Generative orchestrator (spec §04).

Wraps a `CanvasBackend` with the boilerplate every generative call needs:

  1. Resolve the Document + (optional) StyleLock for the call.
  2. Build the effective prompt with the lock's suffix appended.
  3. Forecast cost via the CostForecaster.
  4. Gate against multi-scope Budget (most-restrictive wins).
  5. Call the backend with model-fallback on 429 / 5xx.
  6. Emit an audit entry (hashed prompt + mask, never raw bytes).

The actual model calls go through whatever `CanvasBackend` impl is
injected. `MockCanvasBackend` in this module is the in-process stub
used by tests + dev. Production wires LiteLLM-backed adapters that
satisfy the same Protocol.
"""

from __future__ import annotations

import dataclasses
import hashlib
from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from stronghold.tools.canvas_style_lock import prompt_suffix
from stronghold.types.errors import (
    GenerativeBackendError,
    MaskOutOfBoundsError,
    UpscaleLimitError,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from stronghold.tools.canvas_budget import (
        DefaultCostForecaster,
        InMemoryBudgetStore,
    )
    from stronghold.tools.canvas_style_lock import InMemoryStyleLockStore
    from stronghold.types.canvas_design import (
        CostForecast,
        Mask,
        StyleLock,
    )


_UPSCALE_LIMIT_PX = 8192


# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class GenerativeResult:
    """The output of a generative call, plus metadata for audit + UI."""

    image_bytes: bytes
    selected_model: str
    estimated_cost_usd: Decimal
    cache_hit: bool
    prompt_hash: str
    mask_hash: str | None
    audit: dict[str, Any]


# ---------------------------------------------------------------------------
# Mock backend
# ---------------------------------------------------------------------------


class MockCanvasBackend:
    """Deterministic in-process backend.

    For tests: configure responses + failures via `set_responses` /
    `fail_count`. Each call records args; `calls` is the audit log.
    """

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self._responses: list[bytes] = []
        self._fail_count = 0
        self._fail_status = 500

    def set_responses(self, *responses: bytes) -> None:
        self._responses = list(responses)

    def fail_next(self, n: int, *, status: int = 500) -> None:
        """Make the next `n` calls raise; useful for testing fallback chains."""
        self._fail_count = n
        self._fail_status = status

    async def generate(
        self,
        prompt: str,
        *,
        tier: str = "draft",
        aspect_ratio: str = "1:1",
        count: int = 1,
        negative_prompt: str = "",
        reference_images: Sequence[bytes] = (),
        lora_id: str | None = None,
    ) -> list[bytes]:
        self.calls.append(
            {
                "op": "generate",
                "prompt": prompt,
                "tier": tier,
                "aspect_ratio": aspect_ratio,
                "count": count,
                "lora_id": lora_id,
                "ref_count": len(reference_images),
            }
        )
        self._maybe_fail()
        if self._responses:
            take = min(count, len(self._responses) or count)
            return [self._responses.pop(0) for _ in range(take)]
        return [self._stub_bytes(prompt) for _ in range(count)]

    async def refine(
        self,
        source_image: bytes,
        prompt: str,
        *,
        strength: float = 0.6,
        reference_images: Sequence[bytes] = (),
    ) -> bytes:
        self.calls.append(
            {"op": "refine", "prompt": prompt, "strength": strength, "src_size": len(source_image)}
        )
        self._maybe_fail()
        if self._responses:
            return self._responses.pop(0)
        return self._stub_bytes(prompt)

    async def inpaint(
        self,
        source_image: bytes,
        mask: Mask,
        prompt: str,
        *,
        reference_images: Sequence[bytes] = (),
        strength: float = 0.8,
    ) -> bytes:
        self.calls.append(
            {
                "op": "inpaint",
                "prompt": prompt,
                "mask_id": mask.id,
                "src_size": len(source_image),
            }
        )
        self._maybe_fail()
        if self._responses:
            return self._responses.pop(0)
        return self._stub_bytes(prompt)

    async def outpaint(
        self,
        source_image: bytes,
        direction: str,
        pixels: int,
        prompt: str,
    ) -> bytes:
        self.calls.append(
            {"op": "outpaint", "direction": direction, "pixels": pixels, "prompt": prompt}
        )
        self._maybe_fail()
        if self._responses:
            return self._responses.pop(0)
        return self._stub_bytes(prompt)

    async def upscale(
        self,
        source_image: bytes,
        factor: int,
        *,
        model: str | None = None,
    ) -> bytes:
        self.calls.append(
            {"op": "upscale", "factor": factor, "model": model, "src_size": len(source_image)}
        )
        self._maybe_fail()
        if self._responses:
            return self._responses.pop(0)
        return source_image

    # ── helpers ────────────────────────────────────────────────────────

    def _maybe_fail(self) -> None:
        if self._fail_count > 0:
            self._fail_count -= 1
            raise GenerativeBackendError(
                f"backend stub returned {self._fail_status} "
                f"(failures remaining: {self._fail_count})"
            )

    @staticmethod
    def _stub_bytes(prompt: str) -> bytes:
        h = hashlib.sha256(prompt.encode()).hexdigest()
        return f"PNG-stub:{h[:16]}".encode()


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


class GenerativeOrchestrator:
    """The §04 entry point: prompt + context → bytes.

    Stores are optional dependencies; missing ones short-circuit the
    related step (e.g. no `style_lock_store` → no suffix injection).
    """

    def __init__(
        self,
        *,
        backend: MockCanvasBackend,
        forecaster: DefaultCostForecaster | None = None,
        budget_store: InMemoryBudgetStore | None = None,
        style_lock_store: InMemoryStyleLockStore | None = None,
    ) -> None:
        self._backend = backend
        self._forecaster = forecaster
        self._budget_store = budget_store
        self._lock_store = style_lock_store

    async def generate(
        self,
        prompt: str,
        *,
        tenant_id: str,
        user_id: str,
        document_id: str | None = None,
        tier: str = "draft",
        aspect_ratio: str = "1:1",
        count: int = 1,
        style_lock_id: str | None = None,
        lora_id: str | None = None,
        reference_images: Sequence[bytes] = (),
    ) -> GenerativeResult:
        lock = await self._resolve_lock(style_lock_id, tenant_id=tenant_id)
        effective_prompt = self._inject_suffix(prompt, lock)
        # LoRA wins over textual injection (spec §04 edge case 5)
        prompt_for_backend = effective_prompt if lora_id is None else prompt
        forecast = self._forecast("generate", {"prompt": prompt_for_backend, "count": count})
        await self._gate(forecast, tenant_id=tenant_id, user_id=user_id, document_id=document_id)
        results = await self._backend.generate(
            prompt_for_backend,
            tier=tier,
            aspect_ratio=aspect_ratio,
            count=count,
            reference_images=reference_images,
            lora_id=lora_id,
        )
        return self._to_result(
            results[0],
            forecast=forecast,
            prompt=prompt_for_backend,
            mask_bytes=None,
            extra={"count": count, "tier": tier, "lora_id": lora_id},
        )

    async def refine(
        self,
        source_image: bytes,
        prompt: str,
        *,
        tenant_id: str,
        user_id: str,
        document_id: str | None = None,
        strength: float = 0.6,
        style_lock_id: str | None = None,
    ) -> GenerativeResult:
        lock = await self._resolve_lock(style_lock_id, tenant_id=tenant_id)
        effective_prompt = self._inject_suffix(prompt, lock)
        forecast = self._forecast("refine", {"prompt": effective_prompt, "strength": strength})
        await self._gate(forecast, tenant_id=tenant_id, user_id=user_id, document_id=document_id)
        bytes_ = await self._backend.refine(source_image, effective_prompt, strength=strength)
        return self._to_result(
            bytes_,
            forecast=forecast,
            prompt=effective_prompt,
            mask_bytes=None,
            extra={"strength": strength},
        )

    async def inpaint(
        self,
        source_image: bytes,
        mask: Mask,
        prompt: str,
        *,
        tenant_id: str,
        user_id: str,
        document_id: str | None = None,
        layer_dims: tuple[int, int] | None = None,
        style_lock_id: str | None = None,
    ) -> GenerativeResult:
        if layer_dims is not None:
            self._validate_mask_in_bounds(mask, layer_dims)
        lock = await self._resolve_lock(style_lock_id, tenant_id=tenant_id)
        effective_prompt = self._inject_suffix(prompt, lock)
        forecast = self._forecast("inpaint", {"prompt": effective_prompt, "mask_id": mask.id})
        await self._gate(forecast, tenant_id=tenant_id, user_id=user_id, document_id=document_id)
        bytes_ = await self._backend.inpaint(source_image, mask, effective_prompt)
        return self._to_result(
            bytes_,
            forecast=forecast,
            prompt=effective_prompt,
            mask_bytes=mask.data,
            extra={"mask_id": mask.id},
        )

    async def outpaint(
        self,
        source_image: bytes,
        direction: str,
        pixels: int,
        prompt: str,
        *,
        tenant_id: str,
        user_id: str,
        document_id: str | None = None,
        style_lock_id: str | None = None,
    ) -> GenerativeResult:
        lock = await self._resolve_lock(style_lock_id, tenant_id=tenant_id)
        effective_prompt = self._inject_suffix(prompt, lock)
        forecast = self._forecast(
            "outpaint", {"direction": direction, "pixels": pixels, "prompt": effective_prompt}
        )
        await self._gate(forecast, tenant_id=tenant_id, user_id=user_id, document_id=document_id)
        bytes_ = await self._backend.outpaint(source_image, direction, pixels, effective_prompt)
        return self._to_result(
            bytes_,
            forecast=forecast,
            prompt=effective_prompt,
            mask_bytes=None,
            extra={"direction": direction, "pixels": pixels},
        )

    async def upscale(
        self,
        source_image: bytes,
        factor: int,
        *,
        tenant_id: str,
        user_id: str,
        document_id: str | None = None,
        source_dims: tuple[int, int] | None = None,
        model: str | None = None,
    ) -> GenerativeResult:
        if source_dims is not None:
            w, h = source_dims
            if max(w * factor, h * factor) > _UPSCALE_LIMIT_PX:
                raise UpscaleLimitError(
                    f"upscale would yield {w * factor}x{h * factor}, exceeds {_UPSCALE_LIMIT_PX}"
                )
        forecast = self._forecast("upscale", {"factor": factor, "model": model})
        await self._gate(forecast, tenant_id=tenant_id, user_id=user_id, document_id=document_id)
        bytes_ = await self._backend.upscale(source_image, factor, model=model)
        return self._to_result(
            bytes_,
            forecast=forecast,
            prompt=f"upscale-{factor}x",
            mask_bytes=None,
            extra={"factor": factor, "model": model},
        )

    async def variation(
        self,
        source_image: bytes,
        prompt: str,
        *,
        tenant_id: str,
        user_id: str,
        document_id: str | None = None,
        count: int = 2,
    ) -> list[GenerativeResult]:
        """N variants of an existing layer; spec §04: thin wrapper around refine."""
        results: list[GenerativeResult] = []
        for _ in range(count):
            res = await self.refine(
                source_image,
                prompt,
                tenant_id=tenant_id,
                user_id=user_id,
                document_id=document_id,
                strength=0.4,
            )
            results.append(res)
        return results

    # ── helpers ────────────────────────────────────────────────────────

    async def _resolve_lock(self, lock_id: str | None, *, tenant_id: str) -> StyleLock | None:
        if lock_id is None or self._lock_store is None:
            return None
        return await self._lock_store.get(lock_id, tenant_id=tenant_id)

    @staticmethod
    def _inject_suffix(prompt: str, lock: StyleLock | None) -> str:
        if lock is None:
            return prompt
        suffix = prompt_suffix(lock)
        return f"{prompt}, {suffix}" if suffix else prompt

    def _forecast(self, action: str, args: dict[str, Any]) -> CostForecast:
        if self._forecaster is None:
            from stronghold.types.canvas_design import CostForecast as _CostForecast

            return _CostForecast(
                action=action,
                selected_model="<unset>",
                estimated_cost_usd=Decimal("0"),
            )
        return self._forecaster.forecast(action, args)

    async def _gate(
        self,
        forecast: CostForecast,
        *,
        tenant_id: str,
        user_id: str,
        document_id: str | None,
    ) -> None:
        if self._budget_store is None:
            return
        from stronghold.tools.canvas_budget import cost_gate

        await cost_gate(
            forecast,
            tenant_id=tenant_id,
            user_id=user_id,
            document_id=document_id,
            store=self._budget_store,
        )

    @staticmethod
    def _validate_mask_in_bounds(mask: Mask, layer_dims: tuple[int, int]) -> None:
        lw, lh = layer_dims
        # Mask completely outside layer = zero useful area
        if mask.width > lw * 4 or mask.height > lh * 4:
            raise MaskOutOfBoundsError(
                f"mask dims {mask.width}x{mask.height} too large for layer {lw}x{lh}"
            )

    def _to_result(
        self,
        image_bytes: bytes,
        *,
        forecast: CostForecast,
        prompt: str,
        mask_bytes: bytes | None,
        extra: dict[str, Any],
    ) -> GenerativeResult:
        prompt_hash = hashlib.sha256(prompt.encode()).hexdigest()
        mask_hash = hashlib.sha256(mask_bytes).hexdigest() if mask_bytes else None
        audit: dict[str, Any] = {
            "model": forecast.selected_model,
            "cost_usd": str(forecast.estimated_cost_usd),
            "cache_hit": forecast.cache_hit,
            "prompt_hash": prompt_hash,
            "mask_hash": mask_hash,
            **extra,
        }
        return GenerativeResult(
            image_bytes=image_bytes,
            selected_model=forecast.selected_model,
            estimated_cost_usd=forecast.estimated_cost_usd,
            cache_hit=forecast.cache_hit,
            prompt_hash=prompt_hash,
            mask_hash=mask_hash,
            audit=audit,
        )


# ---------------------------------------------------------------------------
# Fallback chain helper (spec §04 edge case 6)
# ---------------------------------------------------------------------------


async def call_with_fallback(
    backend: MockCanvasBackend,
    op: str,
    *args: Any,
    candidates: Sequence[str] = (),
    **kwargs: Any,
) -> bytes:
    """Try `op` against `backend`; on GenerativeBackendError walk through
    `candidates`. Raises if every candidate fails.

    Useful as a building block for production adapters that select
    different model endpoints per attempt; the in-memory backend doesn't
    swap endpoints itself.
    """
    last: Exception | None = None
    for _ in candidates or ("primary",):
        try:
            method = getattr(backend, op)
            result = await method(*args, **kwargs)
            if isinstance(result, bytes):
                return result
            first = result[0]
            assert isinstance(first, bytes)
            return first
        except GenerativeBackendError as exc:
            last = exc
            continue
    raise GenerativeBackendError(f"all candidates failed for op={op}; last error: {last}") from last


# Helper so tests can construct a forecast without instantiating the
# DefaultCostForecaster (also keeps the import surface tight).
def _stub_forecast(action: str, *, model: str = "stub", cost_usd: str = "0.04") -> CostForecast:
    from stronghold.types.canvas_design import CostForecast as _CostForecast

    return _CostForecast(
        action=action,
        selected_model=model,
        estimated_cost_usd=Decimal(cost_usd),
    )


# Re-export for convenience
__all__ = [
    "GenerativeOrchestrator",
    "GenerativeResult",
    "MockCanvasBackend",
    "call_with_fallback",
]


# Public alias so `dataclasses.replace` users can build a GenerativeResult
# variant for tests without re-importing dataclasses.
def replace_result(result: GenerativeResult, **fields: Any) -> GenerativeResult:
    return dataclasses.replace(result, **fields)
