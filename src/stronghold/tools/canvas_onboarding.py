"""Onboarding wizard state machine (spec §32).

A pure-data state machine that walks a new user from "I want to make a
book" to a partly-drafted Document with brand kit + style lock + first
character. The wizard runs without any LLM or image-gen — those calls
are made by callers using the orchestrators in the surrounding
modules. This file just owns the state transitions + validation.
"""

from __future__ import annotations

import dataclasses
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any

from stronghold.types.canvas_design import (
    AgeBand,
    DocumentKind,
)
from stronghold.types.errors import (
    WizardInputInvalidError,
    WizardSessionNotFoundError,
    WizardStepUnknownError,
)


class WizardStep(StrEnum):
    WELCOME = "welcome"
    INTENT = "intent"
    CLARIFY = "clarify"
    STYLE_BRIEF = "style_brief"
    CHARACTER = "character"
    BRAND_KIT = "brand_kit"
    BUDGET = "budget"
    FIRST_DRAFT = "first_draft"
    DONE = "done"


_STEP_ORDER: tuple[WizardStep, ...] = (
    WizardStep.WELCOME,
    WizardStep.INTENT,
    WizardStep.CLARIFY,
    WizardStep.STYLE_BRIEF,
    WizardStep.CHARACTER,
    WizardStep.BRAND_KIT,
    WizardStep.BUDGET,
    WizardStep.FIRST_DRAFT,
    WizardStep.DONE,
)


# Steps that are optional per doc_kind. Posters skip CHARACTER; infographics
# skip CHARACTER + STYLE_BRIEF.
_OPTIONAL_STEPS: dict[DocumentKind, tuple[WizardStep, ...]] = {
    DocumentKind.POSTER: (WizardStep.CHARACTER,),
    DocumentKind.INFOGRAPHIC: (WizardStep.CHARACTER, WizardStep.STYLE_BRIEF),
    DocumentKind.OPEN_CANVAS: (
        WizardStep.STYLE_BRIEF,
        WizardStep.CHARACTER,
    ),
    DocumentKind.VIDEO_OVERLAY: (WizardStep.CHARACTER,),
}


# Conservative budget defaults per spec §32.
_DEFAULT_DAILY_USD = Decimal("5")
_DEFAULT_TOTAL_USD = Decimal("20")


@dataclass(frozen=True)
class WizardCollected:
    """Accumulator: snapshot of every field gathered by the wizard."""

    doc_kind: DocumentKind | None = None
    intent_text: str = ""
    audience_age_band: AgeBand | None = None
    language: str = "en"
    page_count: int | None = None
    style_brief_choice: int | None = None
    style_seed_image_blob_id: str | None = None
    character_choice: int | None = None
    character_ref_id: str | None = None
    brand_kit_id: str | None = None
    budget_daily_usd: Decimal | None = None
    budget_total_usd: Decimal | None = None


@dataclass(frozen=True)
class WizardOutcome:
    document_id: str
    brand_kit_id: str | None
    style_lock_id: str | None
    character_ref_ids: tuple[str, ...]
    estimated_cost_usd: Decimal
    duration_seconds: int


@dataclass(frozen=True)
class WizardSession:
    id: str
    user_id: str
    tenant_id: str
    started_at: datetime
    current_step: WizardStep
    collected: WizardCollected
    outcome: WizardOutcome | None = None
    abandoned_at: datetime | None = None
    history: tuple[WizardStep, ...] = ()


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------


class InMemoryWizardStore:
    """Tenant-scoped wizard sessions (active + abandoned)."""

    def __init__(self) -> None:
        self._by_id: dict[str, WizardSession] = {}

    def start(self, *, tenant_id: str, user_id: str) -> WizardSession:
        session = WizardSession(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            user_id=user_id,
            started_at=datetime.now(UTC),
            current_step=WizardStep.WELCOME,
            collected=WizardCollected(),
        )
        self._by_id[session.id] = session
        return session

    def get(self, session_id: str, *, tenant_id: str) -> WizardSession:
        session = self._by_id.get(session_id)
        if session is None or session.tenant_id != tenant_id:
            raise WizardSessionNotFoundError(f"wizard session {session_id!r} not found")
        return session

    def resume_for_user(self, *, tenant_id: str, user_id: str) -> WizardSession | None:
        candidates = [
            s
            for s in self._by_id.values()
            if s.tenant_id == tenant_id
            and s.user_id == user_id
            and s.outcome is None
            and s.abandoned_at is None
        ]
        if not candidates:
            return None
        candidates.sort(key=lambda s: s.started_at, reverse=True)
        return candidates[0]

    def save(self, session: WizardSession) -> None:
        self._by_id[session.id] = session


# ---------------------------------------------------------------------------
# Transitions
# ---------------------------------------------------------------------------


def _next_step(current: WizardStep, doc_kind: DocumentKind | None) -> WizardStep:
    optional = _OPTIONAL_STEPS.get(doc_kind, ()) if doc_kind else ()
    idx = _STEP_ORDER.index(current)
    for next_step in _STEP_ORDER[idx + 1 :]:
        if next_step not in optional:
            return next_step
    return WizardStep.DONE


def _previous_step(current: WizardStep, doc_kind: DocumentKind | None) -> WizardStep:
    optional = _OPTIONAL_STEPS.get(doc_kind, ()) if doc_kind else ()
    idx = _STEP_ORDER.index(current)
    for prev in reversed(_STEP_ORDER[:idx]):
        if prev not in optional:
            return prev
    return WizardStep.WELCOME


def advance(
    session: WizardSession,
    step_input: dict[str, Any],
) -> WizardSession:
    """Apply step input + transition forward."""
    current = session.current_step
    collected = session.collected
    if current is WizardStep.WELCOME:
        kind = step_input.get("doc_kind")
        if not isinstance(kind, str):
            raise WizardInputInvalidError("WELCOME requires doc_kind: str")
        try:
            doc_kind = DocumentKind(kind)
        except ValueError as exc:
            raise WizardInputInvalidError(f"unknown doc_kind {kind!r}") from exc
        collected = dataclasses.replace(collected, doc_kind=doc_kind)
    elif current is WizardStep.INTENT:
        intent = step_input.get("intent_text", "").strip()
        if not intent:
            raise WizardInputInvalidError("INTENT requires non-empty intent_text")
        # Cheap heuristic: extract age_band from common phrases.
        age_band = _guess_age_band(intent)
        collected = dataclasses.replace(collected, intent_text=intent, audience_age_band=age_band)
    elif current is WizardStep.CLARIFY:
        if "age_band" in step_input:
            collected = dataclasses.replace(
                collected, audience_age_band=AgeBand(step_input["age_band"])
            )
        if "language" in step_input:
            collected = dataclasses.replace(collected, language=str(step_input["language"]))
    elif current is WizardStep.STYLE_BRIEF:
        choice = step_input.get("style_brief_choice")
        if isinstance(choice, int):
            collected = dataclasses.replace(collected, style_brief_choice=choice)
        if "style_seed_image_blob_id" in step_input:
            collected = dataclasses.replace(
                collected, style_seed_image_blob_id=str(step_input["style_seed_image_blob_id"])
            )
    elif current is WizardStep.CHARACTER:
        if "character_choice" in step_input:
            collected = dataclasses.replace(
                collected, character_choice=int(step_input["character_choice"])
            )
        if "character_ref_id" in step_input:
            collected = dataclasses.replace(
                collected, character_ref_id=str(step_input["character_ref_id"])
            )
    elif current is WizardStep.BRAND_KIT:
        if "brand_kit_id" in step_input:
            collected = dataclasses.replace(collected, brand_kit_id=str(step_input["brand_kit_id"]))
    elif current is WizardStep.BUDGET:
        daily = step_input.get("daily_usd", _DEFAULT_DAILY_USD)
        total = step_input.get("total_usd", _DEFAULT_TOTAL_USD)
        try:
            collected = dataclasses.replace(
                collected,
                budget_daily_usd=Decimal(str(daily)),
                budget_total_usd=Decimal(str(total)),
            )
        except Exception as exc:  # noqa: BLE001
            raise WizardInputInvalidError(f"invalid budget: {exc}") from exc
    elif current is WizardStep.FIRST_DRAFT:
        # Caller provides the resulting document_id — wizard records the
        # outcome and moves to DONE.
        document_id = step_input.get("document_id")
        if not isinstance(document_id, str) or not document_id:
            raise WizardInputInvalidError("FIRST_DRAFT requires document_id")
        outcome = WizardOutcome(
            document_id=document_id,
            brand_kit_id=collected.brand_kit_id,
            style_lock_id=step_input.get("style_lock_id"),
            character_ref_ids=tuple(step_input.get("character_ref_ids", ())),
            estimated_cost_usd=Decimal(str(step_input.get("cost_usd", "0"))),
            duration_seconds=int(step_input.get("duration_seconds", 0)),
        )
        return dataclasses.replace(
            session,
            collected=collected,
            outcome=outcome,
            current_step=WizardStep.DONE,
            history=(*session.history, current),
        )
    elif current is WizardStep.DONE:
        raise WizardStepUnknownError("wizard already finished")
    else:  # pragma: no cover  defensive
        raise WizardStepUnknownError(f"unknown step {current!r}")

    next_step = _next_step(current, collected.doc_kind)
    return dataclasses.replace(
        session,
        current_step=next_step,
        collected=collected,
        history=(*session.history, current),
    )


def back(session: WizardSession) -> WizardSession:
    prev = _previous_step(session.current_step, session.collected.doc_kind)
    return dataclasses.replace(session, current_step=prev)


def skip(session: WizardSession) -> WizardSession:
    """Skip the current step without recording any input."""
    next_step = _next_step(session.current_step, session.collected.doc_kind)
    return dataclasses.replace(
        session,
        current_step=next_step,
        history=(*session.history, session.current_step),
    )


def abandon(session: WizardSession) -> WizardSession:
    return dataclasses.replace(session, abandoned_at=datetime.now(UTC))


# ---------------------------------------------------------------------------
# Heuristics
# ---------------------------------------------------------------------------


def _guess_age_band(intent_text: str) -> AgeBand | None:
    text = intent_text.lower()
    # Look for "X-year-old" or "ages X-Y"
    import re

    m = re.search(r"(\d+)\s*[-–to ]+\s*(\d+)\s*(?:year|yo|years)", text)
    if m:
        lo, hi = int(m.group(1)), int(m.group(2))
        return _band_for_range(lo, hi)
    m2 = re.search(r"(\d+)\s*[-–]?\s*year[- ]old", text)
    if m2:
        age = int(m2.group(1))
        return _band_for_range(age, age)
    return None


def _band_for_range(lo: int, hi: int) -> AgeBand:
    mid = (lo + hi) / 2
    # Boundaries are inclusive on the lower side: age 5 → 5_7 (not 3_5).
    if mid < 3:
        return AgeBand.AGE_0_3
    if mid < 5:
        return AgeBand.AGE_3_5
    if mid < 7:
        return AgeBand.AGE_5_7
    if mid < 9:
        return AgeBand.AGE_7_9
    if mid <= 12:
        return AgeBand.AGE_9_12
    return AgeBand.TEEN
