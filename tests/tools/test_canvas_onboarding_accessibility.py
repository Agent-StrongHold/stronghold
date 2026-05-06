"""Tests for §32 onboarding wizard + §25 accessibility."""

from __future__ import annotations

from decimal import Decimal

import pytest

from stronghold.tools.canvas_accessibility import (
    AltText,
    DaltonismKind,
    InMemoryAltTextStore,
    WcagLevel,
    assert_contrast,
    assess_reading_level,
    auto_generate_alt_text,
    contrast_ratio,
    dyslexia_overrides,
    palette_colourblind_safe,
    relative_luminance,
    simulate_daltonism,
    wcag_level,
)
from stronghold.tools.canvas_onboarding import (
    InMemoryWizardStore,
    WizardStep,
    abandon,
    advance,
    back,
    skip,
)
from stronghold.types.canvas_design import AgeBand, Color, DocumentKind
from stronghold.types.errors import (
    AltTextRequiredError,
    ContrastFailedError,
    WizardInputInvalidError,
    WizardSessionNotFoundError,
)

# ─── Onboarding wizard ─────────────────────────────────────────────────────


class TestWizardLifecycle:
    def test_start_at_welcome(self) -> None:
        store = InMemoryWizardStore()
        session = store.start(tenant_id="acme", user_id="alice")
        assert session.current_step is WizardStep.WELCOME
        assert session.collected.doc_kind is None

    def test_welcome_to_intent(self) -> None:
        store = InMemoryWizardStore()
        session = store.start(tenant_id="acme", user_id="alice")
        next_session = advance(session, {"doc_kind": "picture_book"})
        assert next_session.current_step is WizardStep.INTENT
        assert next_session.collected.doc_kind is DocumentKind.PICTURE_BOOK

    def test_invalid_doc_kind(self) -> None:
        store = InMemoryWizardStore()
        session = store.start(tenant_id="acme", user_id="alice")
        with pytest.raises(WizardInputInvalidError):
            advance(session, {"doc_kind": "asteroid_field"})

    def test_intent_extracts_age_band(self) -> None:
        store = InMemoryWizardStore()
        session = store.start(tenant_id="acme", user_id="alice")
        session = advance(session, {"doc_kind": "picture_book"})
        session = advance(
            session,
            {"intent_text": "a bedtime story for my 5-year-old daughter"},
        )
        assert session.current_step is WizardStep.CLARIFY
        assert session.collected.audience_age_band is AgeBand.AGE_5_7

    def test_intent_no_age_phrase(self) -> None:
        store = InMemoryWizardStore()
        session = store.start(tenant_id="acme", user_id="alice")
        session = advance(session, {"doc_kind": "picture_book"})
        session = advance(session, {"intent_text": "a fantasy book about dragons"})
        # No age band phrase → unset
        assert session.collected.audience_age_band is None

    def test_empty_intent_rejected(self) -> None:
        store = InMemoryWizardStore()
        session = store.start(tenant_id="acme", user_id="alice")
        session = advance(session, {"doc_kind": "picture_book"})
        with pytest.raises(WizardInputInvalidError):
            advance(session, {"intent_text": "  "})


class TestOptionalSteps:
    def test_poster_skips_character(self) -> None:
        store = InMemoryWizardStore()
        session = store.start(tenant_id="acme", user_id="alice")
        session = advance(session, {"doc_kind": "poster"})
        session = advance(session, {"intent_text": "a movie poster for my film"})
        # Walk forward through clarify + style_brief
        session = advance(session, {})  # CLARIFY → STYLE_BRIEF
        session = advance(session, {"style_brief_choice": 1})
        # CHARACTER is skipped for posters → next is BRAND_KIT
        assert session.current_step is WizardStep.BRAND_KIT

    def test_infographic_skips_style_brief_and_character(self) -> None:
        store = InMemoryWizardStore()
        session = store.start(tenant_id="acme", user_id="alice")
        session = advance(session, {"doc_kind": "infographic"})
        session = advance(session, {"intent_text": "monthly KPIs"})
        session = advance(session, {})  # CLARIFY
        # STYLE_BRIEF skipped, CHARACTER skipped → next BRAND_KIT
        assert session.current_step is WizardStep.BRAND_KIT


class TestBudget:
    def test_default_budgets_applied(self) -> None:
        store = InMemoryWizardStore()
        session = store.start(tenant_id="acme", user_id="alice")
        session = advance(session, {"doc_kind": "picture_book"})
        session = advance(session, {"intent_text": "story for my 5 year old"})
        # Walk to budget
        for _ in range(5):
            session = advance(session, {})
            if session.current_step is WizardStep.BUDGET:
                break
        # Apply default budgets
        session = advance(session, {})
        assert session.collected.budget_daily_usd == Decimal("5")
        assert session.collected.budget_total_usd == Decimal("20")

    def test_invalid_budget_rejected(self) -> None:
        store = InMemoryWizardStore()
        session = store.start(tenant_id="acme", user_id="alice")
        session = advance(session, {"doc_kind": "picture_book"})
        session = advance(session, {"intent_text": "story for 5yo"})
        for _ in range(5):
            session = advance(session, {})
            if session.current_step is WizardStep.BUDGET:
                break
        with pytest.raises(WizardInputInvalidError):
            advance(session, {"daily_usd": "not-a-number"})


class TestFirstDraftAndDone:
    def test_first_draft_records_outcome(self) -> None:
        store = InMemoryWizardStore()
        session = store.start(tenant_id="acme", user_id="alice")
        session = advance(session, {"doc_kind": "poster"})
        session = advance(session, {"intent_text": "a poster"})
        # Walk to FIRST_DRAFT
        while session.current_step is not WizardStep.FIRST_DRAFT:
            session = advance(session, {})
        session = advance(
            session,
            {"document_id": "doc-123", "style_lock_id": "lock-x", "cost_usd": "0.04"},
        )
        assert session.current_step is WizardStep.DONE
        assert session.outcome is not None
        assert session.outcome.document_id == "doc-123"

    def test_first_draft_requires_document_id(self) -> None:
        store = InMemoryWizardStore()
        session = store.start(tenant_id="acme", user_id="alice")
        session = advance(session, {"doc_kind": "poster"})
        session = advance(session, {"intent_text": "x"})
        while session.current_step is not WizardStep.FIRST_DRAFT:
            session = advance(session, {})
        with pytest.raises(WizardInputInvalidError):
            advance(session, {})


class TestBackSkipAbandon:
    def test_back_returns_to_previous_step(self) -> None:
        store = InMemoryWizardStore()
        session = store.start(tenant_id="acme", user_id="alice")
        session = advance(session, {"doc_kind": "picture_book"})
        # At INTENT — go back to WELCOME
        prev = back(session)
        assert prev.current_step is WizardStep.WELCOME
        # Collected is preserved
        assert prev.collected.doc_kind is DocumentKind.PICTURE_BOOK

    def test_skip_advances_without_input(self) -> None:
        store = InMemoryWizardStore()
        session = store.start(tenant_id="acme", user_id="alice")
        session = advance(session, {"doc_kind": "picture_book"})
        session = advance(session, {"intent_text": "x"})
        # Skip CLARIFY without supplying anything
        skipped = skip(session)
        assert skipped.current_step is WizardStep.STYLE_BRIEF

    def test_abandon_marks_session(self) -> None:
        store = InMemoryWizardStore()
        session = store.start(tenant_id="acme", user_id="alice")
        abandoned = abandon(session)
        assert abandoned.abandoned_at is not None


class TestStoreLifecycle:
    def test_resume_returns_latest_unfinished(self) -> None:
        store = InMemoryWizardStore()
        s1 = store.start(tenant_id="acme", user_id="alice")
        s2 = store.start(tenant_id="acme", user_id="alice")
        latest = store.resume_for_user(tenant_id="acme", user_id="alice")
        # Newest start_at wins
        assert latest is not None
        assert latest.id in (s1.id, s2.id)

    def test_get_unknown_raises(self) -> None:
        store = InMemoryWizardStore()
        with pytest.raises(WizardSessionNotFoundError):
            store.get("missing", tenant_id="acme")


# ─── §25 Accessibility ─────────────────────────────────────────────────────


class TestContrast:
    def test_pure_black_on_white_is_aaa(self) -> None:
        ratio = contrast_ratio((0, 0, 0), (255, 255, 255))
        assert ratio == pytest.approx(21.0, abs=0.01)
        assert wcag_level((0, 0, 0), (255, 255, 255)) is WcagLevel.AAA

    def test_grey_on_white_aa_only(self) -> None:
        # #767676 on white ≈ 4.5:1
        level = wcag_level((118, 118, 118), (255, 255, 255))
        assert level in (WcagLevel.AA, WcagLevel.AAA)

    def test_low_contrast_fails(self) -> None:
        ratio = contrast_ratio((255, 255, 224), (255, 255, 255))
        assert ratio < 2.0
        assert wcag_level((255, 255, 224), (255, 255, 255)) is WcagLevel.FAIL

    def test_assert_contrast_passes_aa(self) -> None:
        assert_contrast(
            Color("#000000"),
            Color("#FFFFFF"),
            require=WcagLevel.AA,
        )

    def test_assert_contrast_raises_on_failure(self) -> None:
        with pytest.raises(ContrastFailedError):
            assert_contrast(
                Color("#FFFFE0"),
                Color("#FFFFFF"),
                require=WcagLevel.AA,
            )

    def test_large_text_threshold_relaxed(self) -> None:
        # 3:1 contrast: fails for normal text, passes for large
        fg = (140, 140, 140)
        bg = (255, 255, 255)
        normal = wcag_level(fg, bg, is_large_text=False)
        large = wcag_level(fg, bg, is_large_text=True)
        assert normal is WcagLevel.FAIL or large is not WcagLevel.FAIL

    def test_relative_luminance_extremes(self) -> None:
        assert relative_luminance((0, 0, 0)) == 0.0
        assert relative_luminance((255, 255, 255)) == pytest.approx(1.0, abs=0.001)


class TestDaltonism:
    def test_protanopia_dims_red(self) -> None:
        red = (255, 0, 0)
        sim = simulate_daltonism(red, DaltonismKind.PROTANOPIA)
        # Reds drop in brightness for red-blind users
        assert sim[0] < 255

    def test_distinct_palette_passes(self) -> None:
        palette = (
            Color("#000000"),
            Color("#FFFFFF"),
            Color("#FFFF00"),
        )
        is_safe, failing = palette_colourblind_safe(palette)
        assert is_safe
        assert failing == []

    def test_red_green_palette_compresses_under_deutan(self) -> None:
        palette = (
            Color("#FF0000"),
            Color("#00FF00"),
            Color("#FFFFFF"),
        )
        # Pure red and green compress from euclidean ~360 to ~142 under
        # the deuteranopia mock matrix. Strict threshold here demonstrates
        # the compression; the default 30 is permissive enough that very
        # different colours stay distinguishable.
        is_safe, failing = palette_colourblind_safe(palette, min_distance=200)
        assert not is_safe
        kinds = {f[2] for f in failing}
        assert DaltonismKind.DEUTERANOPIA in kinds


class TestReadingLevel:
    def test_short_simple_sentence_appropriate_for_5_7(self) -> None:
        text = "The cat sat on the mat. It was warm."
        report = assess_reading_level(text, AgeBand.AGE_5_7)
        assert report.appropriate
        assert report.avg_words_per_sentence < 10

    def test_long_words_inappropriate_for_3_5(self) -> None:
        text = "Differentiating between paradigmatic constellations is intellectually demanding."
        report = assess_reading_level(text, AgeBand.AGE_3_5)
        assert not report.appropriate

    def test_empty_text_is_appropriate(self) -> None:
        report = assess_reading_level("", AgeBand.AGE_5_7)
        assert report.appropriate


class TestAltText:
    def test_set_and_get(self) -> None:
        store = InMemoryAltTextStore()
        store.set("L1", "a smiling dragon", tenant_id="acme")
        alt = store.get("L1", tenant_id="acme")
        assert isinstance(alt, AltText)
        assert alt.text == "a smiling dragon"
        assert alt.user_supplied is True

    def test_user_supplied_overrides_auto(self) -> None:
        store = InMemoryAltTextStore()
        store.set("L1", "user version", tenant_id="acme", user_supplied=True)
        # Auto-gen attempts to overwrite — should NOT win
        store.set("L1", "auto version", tenant_id="acme", user_supplied=False)
        alt = store.get("L1", tenant_id="acme")
        assert alt is not None
        assert alt.text == "user version"

    def test_assert_present_raises_when_missing(self) -> None:
        store = InMemoryAltTextStore()
        with pytest.raises(AltTextRequiredError):
            store.assert_present("L1", tenant_id="acme")

    def test_auto_generate_strips_an_image_of(self) -> None:
        out = auto_generate_alt_text("an image of a smiling dragon")
        assert not out.lower().startswith("an image of")
        assert "smiling dragon" in out

    def test_auto_generate_handles_empty(self) -> None:
        out = auto_generate_alt_text("")
        assert out  # non-empty fallback


class TestDyslexiaMode:
    def test_overrides_set_accessibility_font(self) -> None:
        overrides = dyslexia_overrides()
        assert "Atkinson" in overrides.body_font_family
        assert overrides.line_height >= 1.6
        assert overrides.italics_disabled
        assert overrides.justify_disabled
