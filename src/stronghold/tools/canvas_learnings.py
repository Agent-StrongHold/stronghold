"""Learning aggregation (spec §20).

Walks `Correction` events, applies promotion rules, produces +
maintains `CanvasLearning` rows. Implements decay, contradiction
resolution, and the basic critic decomposition (Type / Color /
Composition / Prompt / Prop / Accessibility / Cost — §30) at a
single-process level.

The aggregator is idempotent on the same input window: re-running it
with the same corrections doesn't duplicate learnings.
"""

from __future__ import annotations

import dataclasses
import uuid
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from stronghold.types.canvas_design import (
    CanvasLearning,
    CanvasLearningScope,
    Correction,
    CorrectionKind,
    LearningRuleKind,
)

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence


_USER_PROMOTION_THRESHOLD = 3
_DOCUMENT_PROMOTION_THRESHOLD = 2
_ASSET_PROMOTION_THRESHOLD = 3
_BRAND_KIT_PROMOTION_THRESHOLD = 3
_DEFAULT_DECAY_FACTOR = 0.99
_ACCESSIBILITY_FLOOR = 0.5
_BRAND_FLOOR = 0.3


def _now() -> datetime:
    return datetime.now(UTC)


def _new_id() -> str:
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Critic mapping (spec §30)
# ---------------------------------------------------------------------------


_CRITIC_WATCHES: dict[str, frozenset[CorrectionKind]] = {
    "TYPE": frozenset(
        {
            CorrectionKind.TEXT_EDIT,
            CorrectionKind.FONT_CHANGE,
            CorrectionKind.EFFECT_ADD,
            CorrectionKind.EFFECT_REMOVE,
            CorrectionKind.EFFECT_PARAMS_CHANGE,
        }
    ),
    "COLOR": frozenset({CorrectionKind.COLOR_CHANGE}),
    "COMPOSITION": frozenset(
        {
            CorrectionKind.TRANSFORM_MOVE,
            CorrectionKind.TRANSFORM_SCALE,
            CorrectionKind.TRANSFORM_ROTATE,
            CorrectionKind.REORDER,
            CorrectionKind.LAYOUT_APPLY,
        }
    ),
    "PROMPT": frozenset({CorrectionKind.REGEN_WITH_NEW_PROMPT}),
    "PROP": frozenset({CorrectionKind.REPLACE_PROP, CorrectionKind.REPLACE_CHARACTER}),
    # Accessibility critic owns ALT_TEXT_EDIT outright. Per spec §30 it also
    # *watches* font/color changes for flagged values, but those primary-
    # route via TYPE/COLOR; the accessibility-specific signal lives in
    # rule_kind = REQUIRES_ACCESSIBILITY_FONT, not in critic ownership.
    "ACCESSIBILITY": frozenset({CorrectionKind.ALT_TEXT_EDIT}),
}

_CRITIC_PRECEDENCE: dict[str, int] = {
    "ACCESSIBILITY": 0,
    "COLOR": 1,
    "TYPE": 2,
    "PROP": 3,
    "COMPOSITION": 4,
    "PROMPT": 5,
    "COST": 6,
}


def critic_for_kind(kind: CorrectionKind) -> str | None:
    """Return the highest-precedence critic that watches this kind."""
    candidates: list[tuple[int, str]] = [
        (_CRITIC_PRECEDENCE[name], name) for name, kinds in _CRITIC_WATCHES.items() if kind in kinds
    ]
    if not candidates:
        return None
    candidates.sort()
    return candidates[0][1]


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------


class InMemoryCanvasLearningStore:
    """Tenant-scoped CanvasLearning store satisfying the Protocol."""

    def __init__(self) -> None:
        # tenant_id → learning_id → CanvasLearning
        self._learnings: dict[str, dict[str, CanvasLearning]] = {}

    async def upsert(self, learning: CanvasLearning) -> None:
        bucket = self._learnings.setdefault(learning.tenant_id, {})
        bucket[learning.id] = learning

    async def list(
        self,
        *,
        tenant_id: str,
        scope: CanvasLearningScope | None = None,
        user_id: str | None = None,
        document_id: str | None = None,
        asset_id: str | None = None,
        rule_kinds: Iterable[LearningRuleKind] | None = None,
    ) -> list[CanvasLearning]:
        bucket = self._learnings.get(tenant_id, {})
        kind_set = set(rule_kinds) if rule_kinds is not None else None
        return [
            learning
            for learning in bucket.values()
            if (scope is None or learning.scope is scope)
            and (user_id is None or learning.user_id == user_id)
            and (document_id is None or learning.document_id == document_id)
            and (asset_id is None or learning.asset_id == asset_id)
            and (kind_set is None or learning.rule_kind in kind_set)
        ]

    async def decay(self, *, days_since_run: int) -> int:
        """Decay weights of unreinforced learnings; respect floors."""
        affected = 0
        cutoff = _now() - timedelta(days=days_since_run)
        for tenant_id, bucket in self._learnings.items():
            for lid, learning in list(bucket.items()):
                if learning.pinned or learning.last_reinforced_at >= cutoff:
                    continue
                floor = _floor_for(learning.rule_kind)
                new_weight = max(floor, learning.weight * (_DEFAULT_DECAY_FACTOR**days_since_run))
                if new_weight != learning.weight:
                    bucket[lid] = dataclasses.replace(learning, weight=new_weight)
                    affected += 1
            self._learnings[tenant_id] = bucket
        return affected

    async def pin(self, learning_id: str, *, tenant_id: str, pinned: bool) -> None:
        bucket = self._learnings.get(tenant_id, {})
        learning = bucket.get(learning_id)
        if learning is None:
            return
        bucket[learning_id] = dataclasses.replace(learning, pinned=pinned)

    # ── helpers ────────────────────────────────────────────────────────

    def find_matching(
        self,
        *,
        tenant_id: str,
        rule_kind: LearningRuleKind,
        scope: CanvasLearningScope,
        user_id: str | None,
        document_id: str | None,
        asset_id: str | None,
        rule_data: dict[str, Any],
    ) -> CanvasLearning | None:
        """Find an existing learning that matches the same rule_data signature."""
        for learning in self._learnings.get(tenant_id, {}).values():
            if (
                learning.rule_kind is rule_kind
                and learning.scope is scope
                and learning.user_id == user_id
                and learning.document_id == document_id
                and learning.asset_id == asset_id
                and learning.rule_data == rule_data
            ):
                return learning
        return None


def _floor_for(rule_kind: LearningRuleKind) -> float:
    if rule_kind is LearningRuleKind.REQUIRES_ACCESSIBILITY_FONT:
        return _ACCESSIBILITY_FLOOR
    if rule_kind is LearningRuleKind.REQUIRES_BRAND_KIT_USE:
        return _BRAND_FLOOR
    return 0.0


# ---------------------------------------------------------------------------
# Aggregator
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class _Cluster:
    """Bag of corrections sharing a promotion target."""

    rule_kind: LearningRuleKind
    rule_data: tuple[tuple[str, Any], ...]  # tuple repr of dict for hashability
    scope: CanvasLearningScope
    user_id: str | None
    document_id: str | None
    asset_id: str | None
    correction_ids: tuple[str, ...]


def _font_after(c: Correction) -> str | None:
    val = c.after.get("font")
    return str(val) if val is not None else None


def _color_after(c: Correction) -> str | None:
    val = c.after.get("color")
    return str(val) if val is not None else None


def aggregate(
    corrections: Sequence[Correction],
    *,
    tenant_id: str,
    user_scope_threshold: int = _USER_PROMOTION_THRESHOLD,
    document_scope_threshold: int = _DOCUMENT_PROMOTION_THRESHOLD,
    asset_scope_threshold: int = _ASSET_PROMOTION_THRESHOLD,
) -> list[CanvasLearning]:
    """Promote learnings from a batch of corrections.

    Idempotent: matching existing learnings get reinforced (hit_count +1,
    last_reinforced_at refreshed); non-existing get created.
    """
    # Build clusters per rule + scope
    clusters = _cluster(corrections)
    out: list[CanvasLearning] = []
    for cluster in clusters:
        threshold = {
            CanvasLearningScope.USER: user_scope_threshold,
            CanvasLearningScope.DOCUMENT: document_scope_threshold,
            CanvasLearningScope.ASSET: asset_scope_threshold,
            CanvasLearningScope.TENANT: user_scope_threshold,
        }[cluster.scope]
        if len(cluster.correction_ids) < threshold:
            continue
        hit_count = len(cluster.correction_ids)
        confidence = min(0.99, 0.5 + 0.1 * hit_count)
        rule_data = dict(cluster.rule_data)
        learning = CanvasLearning(
            id=_new_id(),
            tenant_id=tenant_id,
            rule_kind=cluster.rule_kind,
            rule_data=rule_data,
            scope=cluster.scope,
            confidence=confidence,
            weight=1.0,
            hit_count=hit_count,
            user_id=cluster.user_id,
            document_id=cluster.document_id,
            asset_id=cluster.asset_id,
            evidence=cluster.correction_ids,
            last_reinforced_at=_now(),
        )
        out.append(learning)
    return out


async def aggregate_into(
    corrections: Sequence[Correction],
    store: InMemoryCanvasLearningStore,
    *,
    tenant_id: str,
) -> list[CanvasLearning]:
    """Aggregate + persist; reinforces existing matches in place."""
    new_or_reinforced: list[CanvasLearning] = []
    candidates = aggregate(corrections, tenant_id=tenant_id)
    for candidate in candidates:
        existing = store.find_matching(
            tenant_id=tenant_id,
            rule_kind=candidate.rule_kind,
            scope=candidate.scope,
            user_id=candidate.user_id,
            document_id=candidate.document_id,
            asset_id=candidate.asset_id,
            rule_data=candidate.rule_data,
        )
        if existing is None:
            await store.upsert(candidate)
            new_or_reinforced.append(candidate)
            continue
        # Reinforce existing
        merged_evidence = tuple(set(existing.evidence) | set(candidate.evidence))
        new_confidence = min(
            0.99,
            existing.confidence + (1.0 - existing.confidence) * 0.3,
        )
        new_weight = min(1.0, existing.weight * 1.1)
        reinforced = dataclasses.replace(
            existing,
            hit_count=existing.hit_count + len(candidate.evidence),
            confidence=new_confidence,
            weight=new_weight,
            last_reinforced_at=_now(),
            evidence=merged_evidence,
        )
        await store.upsert(reinforced)
        new_or_reinforced.append(reinforced)
    return new_or_reinforced


# ---------------------------------------------------------------------------
# Clustering
# ---------------------------------------------------------------------------


def _cluster(corrections: Sequence[Correction]) -> list[_Cluster]:
    """Group corrections by promotion signature.

    Signatures are computed per-(rule_kind, scope, after-value). For
    brand-kit hit detection we look at `after.source == 'brand_kit'`.
    Conflicting changes (same key, opposite values across docs) are
    detected and excluded as "no positive learning".
    """
    # Bag corrections by (rule_kind, scope, user_id, document_id, asset_id, value)
    bucket_key_t = tuple[
        LearningRuleKind,
        CanvasLearningScope,
        str | None,
        str | None,
        str | None,
        tuple[tuple[str, Any], ...],
    ]
    buckets: dict[bucket_key_t, list[Correction]] = {}

    # Track conflicting values per (kind, scope_axis) — different after-values
    # across multiple corrections in the same promotion frame indicate
    # "contextual, not preference" and we skip those clusters.
    conflict_axis: dict[
        tuple[LearningRuleKind, CanvasLearningScope, str | None], set[tuple[tuple[str, Any], ...]]
    ] = {}

    for correction in corrections:
        signatures = _signatures_for(correction)
        for rule_kind, scope, scope_id, value_tuple in signatures:
            user_id = correction.user_id if scope is CanvasLearningScope.USER else None
            document_id = correction.document_id if scope is CanvasLearningScope.DOCUMENT else None
            asset_id = scope_id if scope is CanvasLearningScope.ASSET else None
            key = (rule_kind, scope, user_id, document_id, asset_id, value_tuple)
            buckets.setdefault(key, []).append(correction)
            axis_key = (rule_kind, scope, scope_id)
            conflict_axis.setdefault(axis_key, set()).add(value_tuple)

    out: list[_Cluster] = []
    for key, items in buckets.items():
        rule_kind, scope, user_id, document_id, asset_id, value_tuple = key
        # Per spec: inverse changes on different docs → no learning
        scope_id_for_axis = (
            user_id or document_id or asset_id if scope is not CanvasLearningScope.TENANT else None
        )
        axis_key = (rule_kind, scope, scope_id_for_axis)
        if len(conflict_axis.get(axis_key, set())) > 1:
            # Multiple disagreeing target values for this axis → contextual, skip
            continue
        out.append(
            _Cluster(
                rule_kind=rule_kind,
                rule_data=value_tuple,
                scope=scope,
                user_id=user_id,
                document_id=document_id,
                asset_id=asset_id,
                correction_ids=tuple(c.id for c in items),
            )
        )
    return out


def _signatures_for(
    correction: Correction,
) -> list[tuple[LearningRuleKind, CanvasLearningScope, str | None, tuple[tuple[str, Any], ...]]]:
    """Map a Correction to (rule_kind, scope, scope_id, value-tuple) targets."""
    out: list[
        tuple[LearningRuleKind, CanvasLearningScope, str | None, tuple[tuple[str, Any], ...]]
    ] = []
    if correction.kind is CorrectionKind.FONT_CHANGE:
        font = _font_after(correction)
        if font is not None:
            value = (("family", font),)
            out.append(
                (
                    LearningRuleKind.PREFER_FONT_FAMILY,
                    CanvasLearningScope.USER,
                    correction.user_id,
                    value,
                )
            )
            out.append(
                (
                    LearningRuleKind.PREFER_FONT_FAMILY,
                    CanvasLearningScope.DOCUMENT,
                    correction.document_id,
                    value,
                )
            )
            # Atkinson Hyperlegible promoted to REQUIRES_ACCESSIBILITY_FONT
            if "Atkinson Hyperlegible" in font:
                out.append(
                    (
                        LearningRuleKind.REQUIRES_ACCESSIBILITY_FONT,
                        CanvasLearningScope.USER,
                        correction.user_id,
                        (("family", font),),
                    )
                )
    elif correction.kind is CorrectionKind.COLOR_CHANGE:
        color = _color_after(correction)
        is_brand = correction.after.get("source") == "brand_kit"
        if color is not None:
            value = (("color", color),)
            out.append(
                (
                    LearningRuleKind.PREFER_PALETTE_COLOR,
                    CanvasLearningScope.USER,
                    correction.user_id,
                    value,
                )
            )
            out.append(
                (
                    LearningRuleKind.PREFER_PALETTE_COLOR,
                    CanvasLearningScope.DOCUMENT,
                    correction.document_id,
                    value,
                )
            )
            if is_brand:
                out.append(
                    (
                        LearningRuleKind.REQUIRES_BRAND_KIT_USE,
                        CanvasLearningScope.DOCUMENT,
                        correction.document_id,
                        (("kit_used", True),),
                    )
                )
    elif correction.kind is CorrectionKind.REGEN_WITH_NEW_PROMPT:
        suffix = correction.after.get("prompt_suffix")
        if isinstance(suffix, str) and suffix:
            value = (("suffix", suffix),)
            out.append(
                (
                    LearningRuleKind.PREFER_PROMPT_SUFFIX,
                    CanvasLearningScope.USER,
                    correction.user_id,
                    value,
                )
            )
    elif correction.kind in (CorrectionKind.REPLACE_PROP, CorrectionKind.REPLACE_CHARACTER):
        asset_id = correction.after.get("asset_id")
        variant = correction.after.get("variant_field")
        if isinstance(asset_id, str) and isinstance(variant, str):
            asset_value: tuple[tuple[str, Any], ...] = (
                ("variant_field", variant),
                ("variant_value", correction.after.get("variant_value")),
            )
            out.append(
                (
                    LearningRuleKind.CHARACTER_REFINEMENT,
                    CanvasLearningScope.ASSET,
                    asset_id,
                    asset_value,
                )
            )
    return out


# ---------------------------------------------------------------------------
# Application: merge applicable learnings into a generation prompt
# ---------------------------------------------------------------------------


def apply_learnings_to_prompt(
    prompt: str,
    learnings: Sequence[CanvasLearning],
) -> str:
    """Inject directives from active learnings; precedence-ordered."""
    ranked = sorted(
        learnings,
        key=lambda learning: (
            _CRITIC_PRECEDENCE.get(_critic_for_rule(learning.rule_kind) or "PROMPT", 99),
            -learning.confidence * learning.weight,
        ),
    )
    suffixes: list[str] = []
    for learning in ranked:
        directive = _directive_for(learning)
        if directive:
            suffixes.append(directive)
    if not suffixes:
        return prompt
    return f"{prompt}, {', '.join(suffixes)}"


def _critic_for_rule(rule: LearningRuleKind) -> str | None:
    if rule in (LearningRuleKind.PREFER_FONT_FAMILY, LearningRuleKind.PREFER_FONT_WEIGHT):
        return "TYPE"
    if rule in (
        LearningRuleKind.PREFER_PALETTE_COLOR,
        LearningRuleKind.AVOID_PALETTE_COLOR,
        LearningRuleKind.REQUIRES_BRAND_KIT_USE,
    ):
        return "COLOR"
    if rule is LearningRuleKind.PREFER_LAYOUT:
        return "COMPOSITION"
    if rule in (LearningRuleKind.PREFER_PROMPT_SUFFIX, LearningRuleKind.AVOID_PROMPT_TERMS):
        return "PROMPT"
    if rule in (LearningRuleKind.PREFER_ASSET_VARIANT, LearningRuleKind.CHARACTER_REFINEMENT):
        return "PROP"
    if rule is LearningRuleKind.REQUIRES_ACCESSIBILITY_FONT:
        return "ACCESSIBILITY"
    return None


def _directive_for(learning: CanvasLearning) -> str | None:
    rd = learning.rule_data
    if learning.rule_kind is LearningRuleKind.PREFER_FONT_FAMILY:
        return f"using {rd.get('family')} for body type"
    if learning.rule_kind is LearningRuleKind.REQUIRES_ACCESSIBILITY_FONT:
        return f"using accessible font {rd.get('family')}"
    if learning.rule_kind is LearningRuleKind.PREFER_PALETTE_COLOR:
        return f"using palette colour {rd.get('color')}"
    if learning.rule_kind is LearningRuleKind.PREFER_PROMPT_SUFFIX:
        return str(rd.get("suffix", ""))
    if learning.rule_kind is LearningRuleKind.REQUIRES_BRAND_KIT_USE:
        return "using brand kit colours"
    return None
