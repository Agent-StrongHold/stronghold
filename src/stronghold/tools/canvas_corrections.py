"""Correction capture (spec §19).

Tenant-scoped append-only event log. Every direct-manipulation edit and
chat-driven tweak by a USER yields a `Correction` record; agent-authored
mutations are NOT captured. Coalescing collapses rapid same-author
same-layer same-kind ops within a 5-second window. Reverts within 60s
flip `reverted=True` on the prior correction.

Mock intent inference: in production a vision/diff-LLM produces a short
human-readable intent. Tests + dev use a deterministic placeholder
keyed on (kind, before_hash, after_hash). The Protocol is identical.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from stronghold.types.canvas_design import (
    Correction,
    CorrectionContext,
    CorrectionKind,
    CorrectionSource,
)

_COALESCE_WINDOW = timedelta(seconds=5)
_REVERT_WINDOW = timedelta(seconds=60)


def _now() -> datetime:
    return datetime.now(UTC)


def _new_id() -> str:
    return str(uuid.uuid4())


def _hash(payload: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()[
        :16
    ]


# ---------------------------------------------------------------------------
# Mock intent inferrer
# ---------------------------------------------------------------------------


class MockIntentInferrer:
    """Cached deterministic mock; production swaps a vision/diff-LLM."""

    def __init__(self) -> None:
        self._cache: dict[str, str] = {}
        self.call_count = 0

    def infer(
        self,
        kind: CorrectionKind,
        before: dict[str, Any],
        after: dict[str, Any],
    ) -> str:
        key = f"{kind.value}:{_hash(before)}:{_hash(after)}"
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        self.call_count += 1
        # Build a short description from the diff
        diffs: list[str] = []
        for k in sorted(set(before) | set(after)):
            if before.get(k) != after.get(k):
                diffs.append(f"{k}: {before.get(k)!r} → {after.get(k)!r}")
        intent = f"{kind.value}: {'; '.join(diffs) if diffs else 'no-op'}"
        self._cache[key] = intent
        return intent


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------


_USER_SOURCES = (CorrectionSource.DIRECT_MANIP, CorrectionSource.CHAT, CorrectionSource.AUTO_FIX)
# WIZARD source captured but EXCLUDED from §20 aggregation by default
_AGGREGATABLE_SOURCES = _USER_SOURCES


def _initial_signal_strength(
    kind: CorrectionKind,
    before: dict[str, Any],
    after: dict[str, Any],
) -> float:
    """Heuristic strength in [0.1, 2.0]. Real weights come from §20 aggregation."""
    # Brand-kit-color-applied corrections start strong (§20 promotion rule)
    if kind is CorrectionKind.COLOR_CHANGE and after.get("source") == "brand_kit":
        return 1.5
    return 1.0


class InMemoryCorrectionStore:
    """Tenant-scoped Correction event log satisfying CorrectionStore Protocol."""

    def __init__(self, *, intent_inferrer: MockIntentInferrer | None = None) -> None:
        # tenant_id → user_id → list[Correction]  (newest at end)
        self._by_user: dict[str, dict[str, list[Correction]]] = {}
        self._intents = intent_inferrer or MockIntentInferrer()

    async def capture(
        self,
        *,
        tenant_id: str,
        user_id: str,
        document_id: str,
        page_id: str,
        layer_id: str | None,
        session_id: str,
        kind: CorrectionKind,
        source: CorrectionSource,
        before: dict[str, Any],
        after: dict[str, Any],
        context: CorrectionContext,
    ) -> Correction:
        bucket = self._by_user.setdefault(tenant_id, {}).setdefault(user_id, [])
        # Coalescing: same user + same layer + same kind within window
        prior = bucket[-1] if bucket else None
        if (
            prior is not None
            and prior.kind is kind
            and prior.layer_id == layer_id
            and prior.source is source
            and (_now() - prior.timestamp) <= _COALESCE_WINDOW
        ):
            merged = dataclasses.replace(prior, after=dict(after), timestamp=_now())
            bucket[-1] = merged
            return merged

        intent = self._intents.infer(kind, before, after)
        correction = Correction(
            id=_new_id(),
            tenant_id=tenant_id,
            user_id=user_id,
            document_id=document_id,
            page_id=page_id,
            session_id=session_id,
            kind=kind,
            source=source,
            before=dict(before),
            after=dict(after),
            context=context,
            layer_id=layer_id,
            inferred_intent=intent,
            signal_strength=_initial_signal_strength(kind, before, after),
        )
        bucket.append(correction)
        return correction

    async def list_for_user(
        self,
        *,
        tenant_id: str,
        user_id: str,
        kind: CorrectionKind | None = None,
        since: datetime | None = None,
        limit: int = 1000,
    ) -> list[Correction]:
        bucket = self._by_user.get(tenant_id, {}).get(user_id, [])
        out = [
            c
            for c in bucket
            if (kind is None or c.kind is kind) and (since is None or c.timestamp >= since)
        ]
        return out[-limit:]

    async def mark_reverted(self, correction_id: str, *, tenant_id: str) -> None:
        bucket = self._by_user.get(tenant_id, {})
        for _user_id, items in bucket.items():
            for i, c in enumerate(items):
                if c.id == correction_id:
                    items[i] = dataclasses.replace(c, reverted=True, reverted_at=_now())
                    return
        # Not found — silent no-op per Protocol contract

    async def delete_for_user(self, *, tenant_id: str, user_id: str) -> int:
        bucket = self._by_user.get(tenant_id, {})
        items = bucket.pop(user_id, [])
        return len(items)

    # ── helpers ────────────────────────────────────────────────────────

    async def list_for_document(
        self,
        *,
        tenant_id: str,
        document_id: str,
        only_aggregatable: bool = True,
    ) -> list[Correction]:
        out: list[Correction] = []
        for items in self._by_user.get(tenant_id, {}).values():
            for c in items:
                if c.document_id != document_id:
                    continue
                if c.reverted:
                    continue
                if only_aggregatable and c.source not in _AGGREGATABLE_SOURCES:
                    continue
                out.append(c)
        return out

    async def list_aggregatable(
        self,
        *,
        tenant_id: str,
        user_id: str | None = None,
        since: datetime | None = None,
    ) -> list[Correction]:
        """Reverted + WIZARD source corrections excluded; everything else returns."""
        out: list[Correction] = []
        bucket = self._by_user.get(tenant_id, {})
        users = [user_id] if user_id else list(bucket.keys())
        for uid in users:
            for c in bucket.get(uid, []):
                if c.reverted:
                    continue
                if c.source not in _AGGREGATABLE_SOURCES:
                    continue
                if since is not None and c.timestamp < since:
                    continue
                out.append(c)
        return out

    def revert_within_window(self, correction_id: str, *, tenant_id: str) -> bool:
        """Return True if the correction is within the revert window and was flipped."""
        bucket = self._by_user.get(tenant_id, {})
        for _user_id, items in bucket.items():
            for i, c in enumerate(items):
                if c.id != correction_id:
                    continue
                if (_now() - c.timestamp) > _REVERT_WINDOW:
                    return False
                items[i] = dataclasses.replace(c, reverted=True, reverted_at=_now())
                return True
        return False
