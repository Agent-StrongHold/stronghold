"""Generative orchestrator green tests — features/generative.feature."""

from __future__ import annotations

from decimal import Decimal

import pytest

from stronghold.tools.canvas_budget import (
    DefaultCostForecaster,
    InMemoryBudgetStore,
)
from stronghold.tools.canvas_generative import (
    GenerativeOrchestrator,
    MockCanvasBackend,
    call_with_fallback,
)
from stronghold.tools.canvas_style_lock import InMemoryStyleLockStore
from stronghold.types.canvas_design import (
    Budget,
    BudgetPeriod,
    BudgetScope,
    Color,
    LightingDirection,
    LineWeight,
    Mask,
    MaskOrigin,
)
from stronghold.types.errors import (
    BudgetExceededError,
    GenerativeBackendError,
    MaskOutOfBoundsError,
    UpscaleLimitError,
)


def _palette() -> tuple[Color, ...]:
    return (Color("#FF0000"), Color("#00FF00"), Color("#0000FF"))


def _mask(mask_id: str = "M1", *, w: int = 100, h: int = 100) -> Mask:
    return Mask(
        id=mask_id,
        width=w,
        height=h,
        data=b"\x00" * (w * h),
        origin=MaskOrigin.BBOX,
    )


# ─── Style suffix injection ────────────────────────────────────────────────


class TestStyleSuffixInjection:
    async def test_generate_with_lock_appends_suffix(self) -> None:
        backend = MockCanvasBackend()
        locks = InMemoryStyleLockStore()
        lock = await locks.create_from_brief(
            tenant_id="acme",
            owner_id="alice",
            name="warm-lock",
            rendering_style_prompt="watercolour, soft",
            palette=_palette(),
            line_weight=LineWeight.FINE,
            lighting=LightingDirection.DRAMATIC,
        )
        orchestrator = GenerativeOrchestrator(backend=backend, style_lock_store=locks)
        await orchestrator.generate(
            "a dragon",
            tenant_id="acme",
            user_id="alice",
            style_lock_id=lock.id,
        )
        sent = backend.calls[-1]["prompt"]
        assert "a dragon" in sent
        assert "watercolour, soft" in sent
        assert "fine" in sent
        assert "dramatic" in sent

    async def test_generate_without_lock_passes_prompt_through(self) -> None:
        backend = MockCanvasBackend()
        orchestrator = GenerativeOrchestrator(backend=backend)
        await orchestrator.generate(
            "a dragon",
            tenant_id="acme",
            user_id="alice",
        )
        assert backend.calls[-1]["prompt"] == "a dragon"

    async def test_lora_id_omits_suffix_per_spec_priority(self) -> None:
        backend = MockCanvasBackend()
        locks = InMemoryStyleLockStore()
        lock = await locks.create_from_brief(
            tenant_id="acme",
            owner_id="alice",
            name="x",
            rendering_style_prompt="watercolour",
            palette=_palette(),
        )
        orchestrator = GenerativeOrchestrator(backend=backend, style_lock_store=locks)
        await orchestrator.generate(
            "a dragon",
            tenant_id="acme",
            user_id="alice",
            style_lock_id=lock.id,
            lora_id="lora-warrior-v3",
        )
        # Per spec §04 edge case 5, LoRA wins over textual style suffix
        assert backend.calls[-1]["prompt"] == "a dragon"
        assert backend.calls[-1]["lora_id"] == "lora-warrior-v3"


# ─── Inpaint ───────────────────────────────────────────────────────────────


class TestInpaint:
    async def test_inpaint_passes_mask_to_backend(self) -> None:
        backend = MockCanvasBackend()
        orchestrator = GenerativeOrchestrator(backend=backend)
        m = _mask("M-77")
        await orchestrator.inpaint(
            b"source",
            m,
            "fix the hands",
            tenant_id="acme",
            user_id="alice",
        )
        assert backend.calls[-1]["op"] == "inpaint"
        assert backend.calls[-1]["mask_id"] == "M-77"

    async def test_inpaint_failure_propagates(self) -> None:
        backend = MockCanvasBackend()
        backend.fail_next(1)
        orchestrator = GenerativeOrchestrator(backend=backend)
        with pytest.raises(GenerativeBackendError):
            await orchestrator.inpaint(
                b"source",
                _mask(),
                "fix",
                tenant_id="acme",
                user_id="alice",
            )

    async def test_inpaint_mask_too_large_raises(self) -> None:
        backend = MockCanvasBackend()
        orchestrator = GenerativeOrchestrator(backend=backend)
        big_mask = _mask("big", w=2048, h=2048)
        with pytest.raises(MaskOutOfBoundsError):
            await orchestrator.inpaint(
                b"source",
                big_mask,
                "fix",
                tenant_id="acme",
                user_id="alice",
                layer_dims=(100, 100),
            )

    async def test_audit_records_hashes_not_raw(self) -> None:
        backend = MockCanvasBackend()
        orchestrator = GenerativeOrchestrator(backend=backend)
        m = _mask()
        result = await orchestrator.inpaint(
            b"source",
            m,
            "secret-prompt-content",
            tenant_id="acme",
            user_id="alice",
        )
        assert "secret-prompt-content" not in str(result.audit)
        assert result.prompt_hash != ""
        assert result.mask_hash is not None


# ─── Outpaint ──────────────────────────────────────────────────────────────


class TestOutpaint:
    async def test_outpaint_carries_direction_and_pixels(self) -> None:
        backend = MockCanvasBackend()
        orchestrator = GenerativeOrchestrator(backend=backend)
        await orchestrator.outpaint(
            b"src",
            "right",
            512,
            "more sky",
            tenant_id="acme",
            user_id="alice",
        )
        call = backend.calls[-1]
        assert call["op"] == "outpaint"
        assert call["direction"] == "right"
        assert call["pixels"] == 512


# ─── Upscale ───────────────────────────────────────────────────────────────


class TestUpscale:
    async def test_upscale_under_cap_succeeds(self) -> None:
        backend = MockCanvasBackend()
        orchestrator = GenerativeOrchestrator(backend=backend)
        result = await orchestrator.upscale(
            b"src",
            factor=2,
            tenant_id="acme",
            user_id="alice",
            source_dims=(1024, 1024),
        )
        assert result.image_bytes is not None

    async def test_upscale_over_cap_raises(self) -> None:
        backend = MockCanvasBackend()
        orchestrator = GenerativeOrchestrator(backend=backend)
        with pytest.raises(UpscaleLimitError):
            await orchestrator.upscale(
                b"src",
                factor=4,
                tenant_id="acme",
                user_id="alice",
                source_dims=(4096, 4096),
            )


# ─── Variation ─────────────────────────────────────────────────────────────


class TestVariation:
    async def test_variation_produces_n_children(self) -> None:
        backend = MockCanvasBackend()
        orchestrator = GenerativeOrchestrator(backend=backend)
        results = await orchestrator.variation(
            b"source",
            "more like this",
            tenant_id="acme",
            user_id="alice",
            count=3,
        )
        assert len(results) == 3
        # Each variation calls refine with the lower-strength default
        refines = [c for c in backend.calls if c["op"] == "refine"]
        assert len(refines) == 3
        assert all(c["strength"] == 0.4 for c in refines)


# ─── Cost gate integration ─────────────────────────────────────────────────


class TestCostGate:
    async def test_cost_gate_blocks_when_budget_exceeded(self) -> None:
        backend = MockCanvasBackend()
        forecaster = DefaultCostForecaster()
        budget_store = InMemoryBudgetStore()
        await budget_store.upsert_budget(
            Budget(
                id="b",
                scope=BudgetScope.USER,
                scope_id="alice",
                period=BudgetPeriod.DAILY,
                cap_usd=Decimal("0.01"),
            ),
            tenant_id="acme",
        )
        orchestrator = GenerativeOrchestrator(
            backend=backend,
            forecaster=forecaster,
            budget_store=budget_store,
        )
        with pytest.raises(BudgetExceededError):
            await orchestrator.inpaint(
                b"src",
                _mask(),
                "fix",
                tenant_id="acme",
                user_id="alice",
            )
        # Backend was never called
        assert not any(c["op"] == "inpaint" for c in backend.calls)

    async def test_cache_hit_zero_cost_in_audit(self) -> None:
        backend = MockCanvasBackend()
        forecaster = DefaultCostForecaster(is_cached=lambda *_: True)
        orchestrator = GenerativeOrchestrator(backend=backend, forecaster=forecaster)
        result = await orchestrator.inpaint(
            b"src",
            _mask(),
            "fix",
            tenant_id="acme",
            user_id="alice",
        )
        assert result.cache_hit is True
        assert result.estimated_cost_usd == Decimal("0")


# ─── Fallback chain ────────────────────────────────────────────────────────


class TestFallbackChain:
    async def test_call_with_fallback_succeeds_when_first_fails(self) -> None:
        backend = MockCanvasBackend()
        backend.fail_next(2)  # first 2 attempts fail; 3rd succeeds
        result = await call_with_fallback(
            backend,
            "generate",
            "prompt",
            candidates=("model-a", "model-b", "model-c"),
            count=1,
        )
        assert result is not None

    async def test_call_with_fallback_all_failures_raise(self) -> None:
        backend = MockCanvasBackend()
        backend.fail_next(5)
        with pytest.raises(GenerativeBackendError):
            await call_with_fallback(
                backend,
                "generate",
                "prompt",
                candidates=("a", "b", "c"),
                count=1,
            )


# ─── Result + audit shape ──────────────────────────────────────────────────


class TestResultShape:
    async def test_audit_includes_model_and_cost(self) -> None:
        backend = MockCanvasBackend()
        forecaster = DefaultCostForecaster()
        orchestrator = GenerativeOrchestrator(backend=backend, forecaster=forecaster)
        result = await orchestrator.generate(
            "prompt",
            tenant_id="acme",
            user_id="alice",
        )
        assert result.audit["model"] == result.selected_model
        assert result.audit["cost_usd"] == str(result.estimated_cost_usd)
        assert "prompt_hash" in result.audit
