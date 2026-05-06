"""Learning aggregation green tests — features/learning-aggregation.feature."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from stronghold.tools.canvas_learnings import (
    InMemoryCanvasLearningStore,
    aggregate,
    aggregate_into,
    apply_learnings_to_prompt,
    critic_for_kind,
)
from stronghold.types.canvas_design import (
    AgeBand,
    CanvasLearning,
    CanvasLearningScope,
    Correction,
    CorrectionContext,
    CorrectionKind,
    CorrectionSource,
    DocumentKind,
    LearningRuleKind,
)


def _ctx() -> CorrectionContext:
    return CorrectionContext(doc_kind=DocumentKind.PICTURE_BOOK, age_band=AgeBand.AGE_5_7)


def _correction(
    *,
    user_id: str = "alice",
    document_id: str = "D1",
    kind: CorrectionKind = CorrectionKind.FONT_CHANGE,
    before: dict[str, object] | None = None,
    after: dict[str, object] | None = None,
    layer_id: str | None = "L1",
) -> Correction:
    return Correction(
        id=str(uuid.uuid4()),
        tenant_id="acme",
        user_id=user_id,
        document_id=document_id,
        page_id="P0",
        session_id="S",
        kind=kind,
        source=CorrectionSource.DIRECT_MANIP,
        before=before or {"font": "Comic Sans"},
        after=after or {"font": "Atkinson Hyperlegible"},
        context=_ctx(),
        layer_id=layer_id,
    )


# ─── Cluster-based promotion ───────────────────────────────────────────────


class TestPromotion:
    async def test_3_same_font_changes_across_docs_promotes_user_scope(self) -> None:
        corrections = [_correction(document_id=f"D{i}") for i in range(3)]
        learnings = aggregate(corrections, tenant_id="acme")
        # Atkinson Hyperlegible also co-promotes a REQUIRES_ACCESSIBILITY_FONT
        # learning; here we just assert the PREFER_FONT_FAMILY one exists.
        font_user = [
            learning
            for learning in learnings
            if learning.rule_kind is LearningRuleKind.PREFER_FONT_FAMILY
            and learning.scope is CanvasLearningScope.USER
        ]
        assert len(font_user) == 1
        assert font_user[0].rule_data["family"] == "Atkinson Hyperlegible"
        assert font_user[0].confidence >= 0.7
        assert font_user[0].hit_count == 3

    async def test_2_changes_in_one_document_promote_document_scope(self) -> None:
        corrections = [_correction(document_id="D1") for _ in range(2)]
        learnings = aggregate(corrections, tenant_id="acme")
        doc_scoped = [
            learning for learning in learnings if learning.scope is CanvasLearningScope.DOCUMENT
        ]
        assert len(doc_scoped) == 1
        assert doc_scoped[0].document_id == "D1"

    async def test_below_threshold_no_promotion(self) -> None:
        corrections = [_correction()]
        learnings = aggregate(corrections, tenant_id="acme")
        # Single correction → below DOCUMENT threshold (2) and USER threshold (3)
        assert learnings == []

    async def test_brand_kit_color_promotes_requires_brand_kit_use(self) -> None:
        corrections = [
            _correction(
                kind=CorrectionKind.COLOR_CHANGE,
                before={"color": "#000000"},
                after={"color": "#FFAA00", "source": "brand_kit"},
            )
            for _ in range(3)
        ]
        learnings = aggregate(corrections, tenant_id="acme")
        kinds = {learning.rule_kind for learning in learnings}
        assert LearningRuleKind.REQUIRES_BRAND_KIT_USE in kinds

    async def test_atkinson_hyperlegible_promotes_accessibility_rule(self) -> None:
        corrections = [_correction(document_id=f"D{i}") for i in range(3)]
        learnings = aggregate(corrections, tenant_id="acme")
        kinds = {learning.rule_kind for learning in learnings}
        assert LearningRuleKind.REQUIRES_ACCESSIBILITY_FONT in kinds


# ─── Conflict resolution ───────────────────────────────────────────────────


class TestConflictResolution:
    async def test_inverse_changes_on_different_docs_no_learning(self) -> None:
        corrections = [
            _correction(
                document_id="D1",
                kind=CorrectionKind.COLOR_CHANGE,
                before={"color": "#0000FF"},
                after={"color": "#FF0000"},
            ),
            _correction(
                document_id="D2",
                kind=CorrectionKind.COLOR_CHANGE,
                before={"color": "#FF0000"},
                after={"color": "#0000FF"},
            ),
            _correction(
                document_id="D3",
                kind=CorrectionKind.COLOR_CHANGE,
                before={"color": "#00FF00"},
                after={"color": "#FFFF00"},
            ),
        ]
        learnings = aggregate(corrections, tenant_id="acme")
        # All have different USER-scope after values → conflict, no positive learning
        user_scope = [
            learning for learning in learnings if learning.scope is CanvasLearningScope.USER
        ]
        assert user_scope == []


# ─── Idempotence + reinforcement ───────────────────────────────────────────


class TestIdempotence:
    async def test_aggregate_into_is_idempotent_on_same_input(self) -> None:
        store = InMemoryCanvasLearningStore()
        corrections = [_correction(document_id=f"D{i}") for i in range(3)]
        first = await aggregate_into(corrections, store, tenant_id="acme")
        listing_before = await store.list(tenant_id="acme")
        await aggregate_into(corrections, store, tenant_id="acme")
        listing_after = await store.list(tenant_id="acme")
        # Same number of learnings; existing ones got reinforced (not duplicated)
        assert len(listing_after) == len(listing_before)
        # And reinforcement bumped hit_count past 3
        font_learning = next(
            learning
            for learning in listing_after
            if learning.rule_kind is LearningRuleKind.PREFER_FONT_FAMILY
            and learning.scope is CanvasLearningScope.USER
        )
        assert font_learning.hit_count > first[0].hit_count

    async def test_reinforcement_increases_confidence(self) -> None:
        store = InMemoryCanvasLearningStore()
        corrections = [_correction(document_id=f"D{i}") for i in range(3)]
        first = await aggregate_into(corrections, store, tenant_id="acme")
        await aggregate_into(corrections, store, tenant_id="acme")
        listing = await store.list(tenant_id="acme")
        font_learning = next(
            learning
            for learning in listing
            if learning.rule_kind is LearningRuleKind.PREFER_FONT_FAMILY
            and learning.scope is CanvasLearningScope.USER
        )
        baseline_confidence = next(
            learning.confidence for learning in first if learning.scope is CanvasLearningScope.USER
        )
        assert font_learning.confidence > baseline_confidence


# ─── Decay ─────────────────────────────────────────────────────────────────


class TestDecay:
    async def test_decay_reduces_weight(self) -> None:
        store = InMemoryCanvasLearningStore()
        old_learning = CanvasLearning(
            id="x",
            tenant_id="acme",
            rule_kind=LearningRuleKind.PREFER_FONT_FAMILY,
            rule_data={"family": "Inter"},
            scope=CanvasLearningScope.USER,
            confidence=0.7,
            weight=1.0,
            hit_count=4,
            user_id="alice",
            last_reinforced_at=datetime.now(UTC) - timedelta(days=120),
        )
        await store.upsert(old_learning)
        affected = await store.decay(days_since_run=120)
        assert affected == 1
        listing = await store.list(tenant_id="acme")
        assert listing[0].weight < 1.0

    async def test_pinned_immune_to_decay(self) -> None:
        store = InMemoryCanvasLearningStore()
        pinned = CanvasLearning(
            id="x",
            tenant_id="acme",
            rule_kind=LearningRuleKind.PREFER_FONT_FAMILY,
            rule_data={"family": "Inter"},
            scope=CanvasLearningScope.USER,
            confidence=0.7,
            weight=1.0,
            hit_count=4,
            user_id="alice",
            pinned=True,
            last_reinforced_at=datetime.now(UTC) - timedelta(days=120),
        )
        await store.upsert(pinned)
        await store.decay(days_since_run=120)
        listing = await store.list(tenant_id="acme")
        assert listing[0].weight == 1.0

    async def test_accessibility_floor_prevents_full_decay(self) -> None:
        store = InMemoryCanvasLearningStore()
        learning = CanvasLearning(
            id="x",
            tenant_id="acme",
            rule_kind=LearningRuleKind.REQUIRES_ACCESSIBILITY_FONT,
            rule_data={"family": "Atkinson Hyperlegible"},
            scope=CanvasLearningScope.USER,
            confidence=0.9,
            weight=1.0,
            hit_count=4,
            user_id="alice",
            last_reinforced_at=datetime.now(UTC) - timedelta(days=365),
        )
        await store.upsert(learning)
        await store.decay(days_since_run=365)
        listing = await store.list(tenant_id="acme")
        # Floor 0.5
        assert listing[0].weight >= 0.5


# ─── Critic decomposition ──────────────────────────────────────────────────


class TestCritics:
    def test_font_change_routed_to_type_critic(self) -> None:
        assert critic_for_kind(CorrectionKind.FONT_CHANGE) == "TYPE"

    def test_color_change_routed_to_color_critic(self) -> None:
        assert critic_for_kind(CorrectionKind.COLOR_CHANGE) == "COLOR"

    def test_transform_routed_to_composition_critic(self) -> None:
        assert critic_for_kind(CorrectionKind.TRANSFORM_MOVE) == "COMPOSITION"

    def test_regen_routed_to_prompt_critic(self) -> None:
        assert critic_for_kind(CorrectionKind.REGEN_WITH_NEW_PROMPT) == "PROMPT"

    def test_replace_prop_routed_to_prop_critic(self) -> None:
        assert critic_for_kind(CorrectionKind.REPLACE_PROP) == "PROP"

    def test_alt_text_routed_to_accessibility_critic(self) -> None:
        assert critic_for_kind(CorrectionKind.ALT_TEXT_EDIT) == "ACCESSIBILITY"


# ─── Tenant isolation ──────────────────────────────────────────────────────


class TestTenantIsolation:
    async def test_cross_tenant_learnings_isolated(self) -> None:
        store = InMemoryCanvasLearningStore()
        # Aggregate into tenant 'acme'
        await aggregate_into(
            [_correction(document_id=f"D{i}") for i in range(3)],
            store,
            tenant_id="acme",
        )
        # Cross-tenant list returns nothing
        listing = await store.list(tenant_id="globex")
        assert listing == []


# ─── Application: prompt directives ────────────────────────────────────────


class TestApplyToPrompt:
    def test_directive_injection(self) -> None:
        learnings = [
            CanvasLearning(
                id="x",
                tenant_id="acme",
                rule_kind=LearningRuleKind.PREFER_FONT_FAMILY,
                rule_data={"family": "Atkinson Hyperlegible"},
                scope=CanvasLearningScope.USER,
                confidence=0.8,
                weight=1.0,
                hit_count=3,
                user_id="alice",
            ),
        ]
        result = apply_learnings_to_prompt("a dragon", learnings)
        assert "Atkinson Hyperlegible" in result

    def test_no_learnings_no_change(self) -> None:
        result = apply_learnings_to_prompt("a dragon", [])
        assert result == "a dragon"

    def test_precedence_orders_directives(self) -> None:
        learnings = [
            CanvasLearning(
                id="a",
                tenant_id="acme",
                rule_kind=LearningRuleKind.PREFER_FONT_FAMILY,
                rule_data={"family": "Inter"},
                scope=CanvasLearningScope.USER,
                confidence=0.7,
                weight=1.0,
                hit_count=3,
                user_id="alice",
            ),
            CanvasLearning(
                id="b",
                tenant_id="acme",
                rule_kind=LearningRuleKind.REQUIRES_ACCESSIBILITY_FONT,
                rule_data={"family": "Atkinson Hyperlegible"},
                scope=CanvasLearningScope.USER,
                confidence=0.7,
                weight=1.0,
                hit_count=3,
                user_id="alice",
            ),
        ]
        result = apply_learnings_to_prompt("a dragon", learnings)
        # Accessibility (precedence 0) appears before TYPE (precedence 2)
        accessibility_idx = result.find("Atkinson")
        type_idx = result.find("Inter")
        assert accessibility_idx >= 0
        assert type_idx >= 0
        assert accessibility_idx < type_idx
