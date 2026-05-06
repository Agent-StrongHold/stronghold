"""Tests for §27 audio + §26 i18n."""

from __future__ import annotations

import pytest

from stronghold.tools.canvas_audio_i18n import (
    MockTranslationBackend,
    MockTTSBackend,
    NarrationTrack,
    assert_fits,
    caption_from_narration,
    estimate_overflow_risk,
    expansion_factor,
    is_rtl,
    list_voices,
    segment_bidi,
    synthesize_track,
    voice_clone_check,
)
from stronghold.types.errors import (
    LanguageUnsupportedError,
    LocalizationOverflowError,
    NarrationBackendError,
    TranslationFailedError,
    VoiceCloneRightsViolationError,
    VoiceNotFoundError,
)

# ─── §27 TTS ───────────────────────────────────────────────────────────────


class TestTtsCatalogue:
    def test_list_voices_returns_known_set(self) -> None:
        voices = list_voices()
        assert any(v["voice_id"] == "openai/alloy" for v in voices)

    def test_list_voices_filters_by_language(self) -> None:
        ja = list_voices(language="ja")
        assert all("ja" in v["language_support"] for v in ja)

    async def test_synthesize_returns_audio_bytes(self) -> None:
        backend = MockTTSBackend()
        audio = await backend.synthesize(
            "Hello world",
            voice_id="openai/alloy",
            language="en",
        )
        assert audio.startswith(b"WAV-mock:")

    async def test_unknown_voice_raises(self) -> None:
        backend = MockTTSBackend()
        with pytest.raises(VoiceNotFoundError):
            await backend.synthesize("x", voice_id="unknown-voice", language="en")

    async def test_unsupported_language_raises(self) -> None:
        backend = MockTTSBackend()
        with pytest.raises(LanguageUnsupportedError):
            await backend.synthesize(
                "x",
                voice_id="elevenlabs/serenity",
                language="zh",  # serenity only supports en
            )

    async def test_fail_next_simulates_outage(self) -> None:
        backend = MockTTSBackend()
        backend.fail_next(1)
        with pytest.raises(NarrationBackendError):
            await backend.synthesize("x", voice_id="openai/alloy", language="en")
        # Recovers
        await backend.synthesize("x", voice_id="openai/alloy", language="en")


class TestSynthesizeTrack:
    async def test_track_assembles_segments(self) -> None:
        backend = MockTTSBackend()
        track = await synthesize_track(
            document_id="D1",
            voice_id="openai/alloy",
            language="en",
            segments=(("P0", "Once upon a time"), ("P1", "There was a dragon")),
            backend=backend,
        )
        assert isinstance(track, NarrationTrack)
        assert len(track.segments) == 2
        # Each segment has word timings
        assert track.segments[0].word_timings
        # Cursor advances + page silence inserted between segments
        assert track.segments[1].start_ms > track.segments[0].duration_ms

    async def test_empty_segments_skipped(self) -> None:
        backend = MockTTSBackend()
        track = await synthesize_track(
            document_id="D1",
            voice_id="openai/alloy",
            language="en",
            segments=(("P0", "  "), ("P1", "Real text")),
            backend=backend,
        )
        assert len(track.segments) == 1


class TestCaptions:
    async def test_caption_emits_webvtt_header(self) -> None:
        backend = MockTTSBackend()
        track = await synthesize_track(
            document_id="D1",
            voice_id="openai/alloy",
            language="en",
            segments=(("P0", "Hello"),),
            backend=backend,
        )
        vtt = caption_from_narration(track)
        assert vtt.startswith("WEBVTT")
        assert "-->" in vtt


class TestVoiceCloning:
    def test_clone_denylist_rejected(self) -> None:
        with pytest.raises(VoiceCloneRightsViolationError):
            voice_clone_check(voice_id="user/clone-morgan-freeman", rights_acknowledged=True)

    def test_clone_requires_rights_ack(self) -> None:
        with pytest.raises(VoiceCloneRightsViolationError):
            voice_clone_check(voice_id="user/clone-fred", rights_acknowledged=False)

    def test_clone_with_rights_passes(self) -> None:
        # Doesn't raise
        voice_clone_check(voice_id="user/clone-bob", rights_acknowledged=True)


# ─── §26 i18n ──────────────────────────────────────────────────────────────


class TestExpansionFactor:
    @pytest.mark.parametrize(
        ("lang", "factor"),
        [
            ("en", 1.0),
            ("de", 1.3),
            ("ja", 0.6),
            ("zh-Hans", 0.5),
            ("ar", 1.2),
        ],
    )
    def test_known_languages(self, lang: str, factor: float) -> None:
        assert expansion_factor(lang) == factor

    def test_falls_back_to_base_for_locale(self) -> None:
        # de-AT not directly listed but `de` is
        assert expansion_factor("de-AT") == 1.3

    def test_unknown_language_raises(self) -> None:
        with pytest.raises(LanguageUnsupportedError):
            expansion_factor("xx-YY")


class TestRtl:
    def test_arabic_is_rtl(self) -> None:
        assert is_rtl("ar") is True
        assert is_rtl("ar-SA") is True

    def test_hebrew_is_rtl(self) -> None:
        assert is_rtl("he") is True

    def test_english_is_ltr(self) -> None:
        assert is_rtl("en") is False


class TestTranslation:
    async def test_translate_tags_with_target_lang(self) -> None:
        backend = MockTranslationBackend()
        out = await backend.translate("Hello", source_lang="en", target_lang="es")
        assert out.startswith("[es]")

    async def test_translate_includes_age_band_when_provided(self) -> None:
        backend = MockTranslationBackend()
        out = await backend.translate("Hello", source_lang="en", target_lang="ja", age_band="5_7")
        assert "[ja|age:5_7]" in out

    async def test_unknown_target_lang_raises(self) -> None:
        backend = MockTranslationBackend()
        with pytest.raises(LanguageUnsupportedError):
            await backend.translate("x", source_lang="en", target_lang="xx-YY")

    async def test_refused_pattern_raises(self) -> None:
        backend = MockTranslationBackend(refused=frozenset({"<refuse>"}))
        with pytest.raises(TranslationFailedError):
            await backend.translate(
                "<refuse> me",
                source_lang="en",
                target_lang="es",
            )

    async def test_empty_text_passes_through(self) -> None:
        backend = MockTranslationBackend()
        out = await backend.translate("", source_lang="en", target_lang="es")
        assert out == ""


class TestOverflowEstimation:
    def test_german_expands_versus_english(self) -> None:
        text = "Hello world"  # 11 chars
        risky = estimate_overflow_risk(text, target_lang="de", bbox_chars=12)
        assert risky  # 11 × 1.3 ≈ 14 > 12

    def test_japanese_compresses(self) -> None:
        # English fills the bbox, but Japanese fits comfortably
        text = "x" * 100
        risky = estimate_overflow_risk(text, target_lang="ja", bbox_chars=70)
        assert not risky  # 100 × 0.6 = 60 < 70

    def test_assert_fits_raises_on_overflow(self) -> None:
        with pytest.raises(LocalizationOverflowError):
            assert_fits("Hello world", target_lang="de", bbox_chars=8)


class TestBidiSegmentation:
    def test_pure_latin_returns_single_ltr_run(self) -> None:
        segments = segment_bidi("Hello")
        assert segments == [("ltr", "Hello")]

    def test_arabic_with_latin_brand_isolated(self) -> None:
        # mixed: rtl + " " + ltr + " " + rtl
        segments = segment_bidi("سلام Visit مرحبا")
        directions = [d for d, _ in segments]
        assert "ltr" in directions
        assert "rtl" in directions
        # Latin brand "Visit" is preserved as a single LTR run
        ltr_runs = [text for direction, text in segments if direction == "ltr"]
        assert any("Visit" in r for r in ltr_runs)
