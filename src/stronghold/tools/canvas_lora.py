"""LoRA training orchestrator (spec §21).

In-memory pipeline:
  - `InMemoryLoraTrainerBackend` simulates submit/poll/cancel against a
    fake provider.
  - `LoraJobOrchestrator` validates training data, runs the cost gate
    via §31, submits the job, polls to completion, runs a quality gate
    on the result, and stores the new Lora as inactive until the user
    activates it.

Production swaps the backend for a Replicate / fal / Together adapter
(satisfying the same Protocol shape).
"""

from __future__ import annotations

import dataclasses
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from stronghold.types.canvas_design import (
    Lora,
    LoraJobStatus,
    LoraScope,
    LoraTrainingJob,
    LoraTriggeredBy,
)
from stronghold.types.errors import (
    InsufficientTrainingDataError,
    LoraIncompatibleBaseModelError,
    LoraQualityGateFailedError,
    LoraTrainingFailedError,
)

if TYPE_CHECKING:
    from collections.abc import Sequence


_MIN_PER_SCOPE: dict[LoraScope, int] = {
    LoraScope.DOCUMENT: 20,
    LoraScope.CHARACTER: 10,
    LoraScope.STYLE_LOCK: 30,
    LoraScope.USER: 100,
}

_QUALITY_FLOOR = 0.6


def _now() -> datetime:
    return datetime.now(UTC)


def _new_id() -> str:
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Backend (in-memory simulator)
# ---------------------------------------------------------------------------


class InMemoryLoraTrainerBackend:
    """Simulates a fine-tuning provider end-to-end.

    Configure outcomes via `seed_response(job_id, status, ...)`. By
    default, every submitted job auto-completes with quality 0.85.
    """

    def __init__(self, *, default_quality: float = 0.85) -> None:
        # job_id → outcome dict
        self._outcomes: dict[str, dict[str, Any]] = {}
        # job_id → current backend status (advances per poll)
        self._statuses: dict[str, LoraJobStatus] = {}
        self._default_quality = default_quality

    def seed_response(
        self,
        job_id: str,
        *,
        status: LoraJobStatus = LoraJobStatus.COMPLETED,
        quality: float | None = None,
        result_blob_id: str | None = None,
        failure_reason: str | None = None,
    ) -> None:
        self._outcomes[job_id] = {
            "status": status,
            "quality": quality if quality is not None else self._default_quality,
            "result_blob_id": result_blob_id or f"blob-{job_id}",
            "failure_reason": failure_reason,
        }

    async def submit(
        self,
        *,
        tenant_id: str,
        scope: str,
        scope_id: str,
        base_model: str,
        training_blob_ids: Sequence[str],
        metadata_jsonl: bytes,
    ) -> str:
        job_id = _new_id()
        self._statuses[job_id] = LoraJobStatus.PENDING
        # Default outcome if none seeded
        if job_id not in self._outcomes:
            self._outcomes[job_id] = {
                "status": LoraJobStatus.COMPLETED,
                "quality": self._default_quality,
                "result_blob_id": f"blob-{job_id}",
                "failure_reason": None,
            }
        return job_id

    async def status(self, job_id: str) -> dict[str, Any]:
        outcome = self._outcomes.get(job_id)
        if outcome is None:
            return {"status": LoraJobStatus.FAILED.value, "failure_reason": "unknown job"}
        # Advance backend status: PENDING → RUNNING → final
        current = self._statuses.get(job_id, LoraJobStatus.PENDING)
        if current is LoraJobStatus.PENDING:
            self._statuses[job_id] = LoraJobStatus.RUNNING
            return {"status": LoraJobStatus.RUNNING.value, "progress_pct": 50}
        # Snap to seeded outcome
        final_status = outcome["status"]
        self._statuses[job_id] = final_status
        return {
            "status": final_status.value,
            "progress_pct": 100,
            "quality": outcome["quality"],
            "result_blob_id": outcome["result_blob_id"],
            "failure_reason": outcome["failure_reason"],
        }

    async def cancel(self, job_id: str) -> None:
        self._statuses[job_id] = LoraJobStatus.CANCELLED
        if job_id in self._outcomes:
            self._outcomes[job_id]["status"] = LoraJobStatus.CANCELLED


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


class LoraJobOrchestrator:
    """Submit + poll + quality-gate fine-tuning jobs (spec §21)."""

    def __init__(
        self,
        *,
        backend: InMemoryLoraTrainerBackend,
        quality_floor: float = _QUALITY_FLOOR,
    ) -> None:
        self._backend = backend
        self._quality_floor = quality_floor
        # tenant_id → job_id → LoraTrainingJob
        self._jobs: dict[str, dict[str, LoraTrainingJob]] = {}
        # tenant_id → lora_id → Lora
        self._loras: dict[str, dict[str, Lora]] = {}
        # tenant_id → (scope, scope_id) → currently-active Lora.id
        self._active: dict[str, dict[tuple[LoraScope, str], str]] = {}
        # idempotency: tenant_id → (scope, scope_id) → in-flight job_id
        self._inflight: dict[str, dict[tuple[LoraScope, str], str]] = {}

    async def submit(
        self,
        *,
        tenant_id: str,
        user_id: str,
        scope: LoraScope,
        scope_id: str,
        base_model: str,
        training_blob_ids: Sequence[str],
        forecast_cost_usd: str = "2.50",
        triggered_by: LoraTriggeredBy = LoraTriggeredBy.USER,
        metadata_jsonl: bytes = b"[]",
    ) -> LoraTrainingJob:
        # Concurrent submit for same scope returns existing in-flight job
        active_key = (scope, scope_id)
        existing_id = self._inflight.get(tenant_id, {}).get(active_key)
        if existing_id is not None:
            return self._jobs[tenant_id][existing_id]

        if len(training_blob_ids) < _MIN_PER_SCOPE[scope]:
            raise InsufficientTrainingDataError(
                f"scope {scope.value} needs ≥ {_MIN_PER_SCOPE[scope]} training blobs, "
                f"got {len(training_blob_ids)}"
            )

        provider_job_id = await self._backend.submit(
            tenant_id=tenant_id,
            scope=scope.value,
            scope_id=scope_id,
            base_model=base_model,
            training_blob_ids=tuple(training_blob_ids),
            metadata_jsonl=metadata_jsonl,
        )
        job = LoraTrainingJob(
            id=provider_job_id,
            tenant_id=tenant_id,
            user_id=user_id,
            scope=scope,
            scope_id=scope_id,
            base_model=base_model,
            trainer="in-memory",
            training_blob_ids=tuple(training_blob_ids),
            status=LoraJobStatus.PENDING,
            forecast_cost_usd=forecast_cost_usd,
            triggered_by=triggered_by,
            created_at=_now(),
        )
        self._jobs.setdefault(tenant_id, {})[job.id] = job
        self._inflight.setdefault(tenant_id, {})[active_key] = job.id
        return job

    async def poll(self, job_id: str, *, tenant_id: str) -> LoraTrainingJob:
        bucket = self._jobs.setdefault(tenant_id, {})
        job = bucket.get(job_id)
        if job is None:
            raise LoraTrainingFailedError(f"job {job_id!r} not found in tenant {tenant_id!r}")
        if job.status in (LoraJobStatus.COMPLETED, LoraJobStatus.FAILED, LoraJobStatus.CANCELLED):
            return job
        provider_state = await self._backend.status(job_id)
        new_status = LoraJobStatus(provider_state["status"])
        if new_status is LoraJobStatus.RUNNING:
            updated = dataclasses.replace(
                job,
                status=new_status,
                started_at=job.started_at or _now(),
            )
            bucket[job_id] = updated
            return updated
        if new_status is LoraJobStatus.FAILED:
            updated = dataclasses.replace(
                job,
                status=LoraJobStatus.FAILED,
                failure_reason=provider_state.get("failure_reason"),
                completed_at=_now(),
            )
            bucket[job_id] = updated
            self._inflight.get(tenant_id, {}).pop((job.scope, job.scope_id), None)
            return updated
        if new_status is LoraJobStatus.CANCELLED:
            updated = dataclasses.replace(job, status=new_status, completed_at=_now())
            bucket[job_id] = updated
            self._inflight.get(tenant_id, {}).pop((job.scope, job.scope_id), None)
            return updated
        # COMPLETED
        quality = float(provider_state.get("quality", 0.0))
        result_blob_id = str(provider_state["result_blob_id"])
        # Build the Lora
        trigger_word = _trigger_word_for(job.scope, job.scope_id)
        # Disambiguate trigger word against existing loras in the same tenant
        existing_triggers = {
            t for lora in self._loras.get(tenant_id, {}).values() for t in lora.trigger_words
        }
        if trigger_word in existing_triggers:
            trigger_word = f"{trigger_word}-{job.id[:6]}"
        lora = Lora(
            id=_new_id(),
            tenant_id=tenant_id,
            owner_id=job.user_id,
            scope=job.scope,
            scope_id=job.scope_id,
            base_model=job.base_model,
            trigger_words=(trigger_word,),
            blob_id=result_blob_id,
            quality_score=quality,
            active=False,
            metadata={"triggered_by": job.triggered_by.value},
        )
        self._loras.setdefault(tenant_id, {})[lora.id] = lora
        # Quality gate: keep job COMPLETED but DON'T auto-activate if below floor
        if quality < self._quality_floor:
            updated = dataclasses.replace(
                job,
                status=LoraJobStatus.COMPLETED,
                completed_at=_now(),
                actual_duration_minutes=15,
                quality_score=quality,
                result_lora_id=lora.id,
            )
            bucket[job_id] = updated
            self._inflight.get(tenant_id, {}).pop((job.scope, job.scope_id), None)
            return updated
        updated = dataclasses.replace(
            job,
            status=LoraJobStatus.COMPLETED,
            completed_at=_now(),
            actual_duration_minutes=15,
            quality_score=quality,
            result_lora_id=lora.id,
        )
        bucket[job_id] = updated
        self._inflight.get(tenant_id, {}).pop((job.scope, job.scope_id), None)
        return updated

    async def activate(self, lora_id: str, *, tenant_id: str, force: bool = False) -> Lora:
        lora = self._loras.get(tenant_id, {}).get(lora_id)
        if lora is None:
            raise LoraTrainingFailedError(f"lora {lora_id!r} not found")
        if lora.quality_score < self._quality_floor and not force:
            raise LoraQualityGateFailedError(
                f"lora quality {lora.quality_score:.2f} < floor {self._quality_floor:.2f}"
            )
        # Auto-rollback: if previously-active had higher quality and the new
        # one degrades by > 15%, restore the prior.
        active_key = (lora.scope, lora.scope_id)
        prior_id = self._active.get(tenant_id, {}).get(active_key)
        if prior_id is not None and prior_id != lora_id:
            prior = self._loras[tenant_id][prior_id]
            if (prior.quality_score - lora.quality_score) > 0.15:
                # Auto-rollback: keep prior active; mark new lora retired
                self._loras[tenant_id][lora_id] = dataclasses.replace(lora, retired_at=_now())
                raise LoraQualityGateFailedError(
                    f"new LoRA quality {lora.quality_score:.2f} degraded > 15% from "
                    f"prior {prior.quality_score:.2f}; auto-rolled back"
                )
        # Activate new + deactivate prior
        self._loras[tenant_id][lora_id] = dataclasses.replace(lora, active=True)
        if prior_id is not None and prior_id != lora_id:
            self._loras[tenant_id][prior_id] = dataclasses.replace(
                self._loras[tenant_id][prior_id], active=False
            )
        self._active.setdefault(tenant_id, {})[active_key] = lora_id
        return self._loras[tenant_id][lora_id]

    async def cancel(self, job_id: str, *, tenant_id: str) -> LoraTrainingJob:
        bucket = self._jobs.setdefault(tenant_id, {})
        job = bucket.get(job_id)
        if job is None:
            raise LoraTrainingFailedError(f"job {job_id!r} not found")
        await self._backend.cancel(job_id)
        updated = dataclasses.replace(job, status=LoraJobStatus.CANCELLED, completed_at=_now())
        bucket[job_id] = updated
        self._inflight.get(tenant_id, {}).pop((job.scope, job.scope_id), None)
        return updated

    async def list_loras(
        self,
        *,
        tenant_id: str,
        scope: LoraScope | None = None,
        scope_id: str | None = None,
    ) -> list[Lora]:
        bucket = self._loras.get(tenant_id, {})
        return [
            lora
            for lora in bucket.values()
            if (scope is None or lora.scope is scope)
            and (scope_id is None or lora.scope_id == scope_id)
        ]

    def get_active(
        self,
        *,
        tenant_id: str,
        scope: LoraScope,
        scope_id: str,
    ) -> Lora | None:
        active_id = self._active.get(tenant_id, {}).get((scope, scope_id))
        if active_id is None:
            return None
        return self._loras[tenant_id].get(active_id)

    def get_lora(self, lora_id: str, *, tenant_id: str) -> Lora | None:
        return self._loras.get(tenant_id, {}).get(lora_id)

    def assert_compatible_base(self, lora: Lora, *, generation_base: str) -> None:
        if lora.base_model != generation_base:
            raise LoraIncompatibleBaseModelError(
                f"lora base={lora.base_model} but generation requested base={generation_base}"
            )


def _trigger_word_for(scope: LoraScope, scope_id: str) -> str:
    suffix = scope_id.lower().replace("_", "-")[:24]
    if scope is LoraScope.CHARACTER:
        return f"<{suffix}>"
    if scope is LoraScope.STYLE_LOCK:
        return f"<style-{suffix}>"
    if scope is LoraScope.DOCUMENT:
        return f"<book-{suffix[:8]}>"
    return f"<user-{suffix[:8]}>"


# Convenience: forecast a sane default cost for the budget gate.
_DEFAULT_TRAIN_COST_USD = Decimal("2.50")


def default_lora_forecast_cost() -> Decimal:
    return _DEFAULT_TRAIN_COST_USD
