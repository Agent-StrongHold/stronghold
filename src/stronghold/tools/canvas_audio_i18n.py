"""Audio + localization (specs §27, §26) — minimum viable subsets.

`MockTTSBackend`: deterministic in-memory text-to-speech adapter that
satisfies the `TTSBackend` Protocol. Production swaps an ElevenLabs /
OpenAI / Cartesia adapter.

`MockTranslationBackend`: deterministic translation adapter for tests +
dev. Production swaps a translation-tuned LLM endpoint.

`expansion_factor(target_lang)` returns the language's typical text
expansion vs English (German is 1.3×, CJK is 0.6×, etc.) — used by §14
smart-resize to predict text-overflow risk during localization.
"""

from __future__ import annotations

import hashlib
import re
import uuid
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from stronghold.types.errors import (
    LanguageUnsupportedError,
    LocalizationOverflowError,
    NarrationBackendError,
    TranslationFailedError,
    VoiceCloneRightsViolationError,
    VoiceNotFoundError,
)

if TYPE_CHECKING:
    from collections.abc import Sequence


# ---------------------------------------------------------------------------
# §27 Audio
# ---------------------------------------------------------------------------


class NarratorKind(StrEnum):
    SINGLE = "single"
    CHARACTER_BASED = "character_based"


@dataclass(frozen=True)
class WordTiming:
    word: str
    start_ms: int
    duration_ms: int


@dataclass(frozen=True)
class NarrationSegment:
    id: str
    page_id: str
    text: str
    voice_id: str
    start_ms: int
    duration_ms: int
    audio_bytes: bytes
    word_timings: tuple[WordTiming, ...] = ()
    layer_id: str | None = None


@dataclass(frozen=True)
class NarrationTrack:
    id: str
    document_id: str
    language: str
    voice_id: str
    narrator: NarratorKind
    segments: tuple[NarrationSegment, ...]
    audio_bytes: bytes


# Mock voice catalogue — minimal real-feeling set.
_VOICE_CATALOGUE: dict[str, dict[str, Any]] = {
    "openai/alloy": {
        "language_support": ("en", "es", "fr", "de"),
        "description": "warm female narrator",
    },
    "openai/echo": {
        "language_support": ("en",),
        "description": "calm male narrator",
    },
    "elevenlabs/serenity": {
        "language_support": ("en",),
        "description": "young curious female",
    },
    "cartesia/lullaby": {
        "language_support": ("en", "ja"),
        "description": "soft bedtime narrator",
    },
}


# Public-figure denylist for voice cloning — small example set.
_VOICE_CLONING_DENYLIST = frozenset({"morgan-freeman", "barack-obama"})


def list_voices(*, language: str | None = None) -> list[dict[str, Any]]:
    voices = []
    for voice_id, info in _VOICE_CATALOGUE.items():
        if language is None or language in info["language_support"]:
            voices.append({"voice_id": voice_id, **info})
    return voices


class MockTTSBackend:
    """Deterministic in-memory TTS satisfying the §27 backend Protocol.

    `synthesize(text, voice_id, language)` returns deterministic audio
    bytes (a hash-derived placeholder) plus word timings spaced at 250ms
    per word. `fail_next` simulates provider downtime.
    """

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self._fail_count = 0

    def fail_next(self, n: int) -> None:
        self._fail_count = n

    async def synthesize(
        self,
        text: str,
        *,
        voice_id: str,
        language: str = "en",
    ) -> bytes:
        self.calls.append({"text_len": len(text), "voice_id": voice_id, "language": language})
        if self._fail_count > 0:
            self._fail_count -= 1
            raise NarrationBackendError("mock TTS unavailable")
        if voice_id not in _VOICE_CATALOGUE:
            raise VoiceNotFoundError(f"voice {voice_id!r} not in catalogue")
        info = _VOICE_CATALOGUE[voice_id]
        if language not in info["language_support"]:
            raise LanguageUnsupportedError(
                f"voice {voice_id!r} does not support language {language!r}"
            )
        digest = hashlib.sha256(text.encode()).hexdigest()[:16]
        return f"WAV-mock:{voice_id}:{language}:{digest}".encode()

    async def list_voices(self, *, language: str | None = None) -> list[dict[str, Any]]:
        return list_voices(language=language)


def _word_timings(text: str, *, word_ms: int = 250) -> tuple[WordTiming, ...]:
    timings: list[WordTiming] = []
    cursor = 0
    for word in text.split():
        timings.append(WordTiming(word=word, start_ms=cursor, duration_ms=word_ms))
        cursor += word_ms
    return tuple(timings)


def voice_clone_check(*, voice_id: str, rights_acknowledged: bool) -> None:
    """Enforce spec §27 cloning checks. Raises on denylist + missing rights."""
    normalised = voice_id.lower().replace("clone-", "").replace("user/", "")
    for denied in _VOICE_CLONING_DENYLIST:
        if denied in normalised:
            raise VoiceCloneRightsViolationError(
                f"voice id {voice_id!r} matches denylisted public-figure pattern"
            )
    if not rights_acknowledged:
        raise VoiceCloneRightsViolationError(
            "voice cloning requires explicit rights_acknowledged=True"
        )


async def synthesize_track(
    *,
    document_id: str,
    voice_id: str,
    language: str,
    segments: Sequence[tuple[str, str]],  # (page_id, text)
    backend: MockTTSBackend,
    page_silence_ms: int = 800,
) -> NarrationTrack:
    out_segments: list[NarrationSegment] = []
    cursor = 0
    blob_chunks: list[bytes] = []
    for page_id, text in segments:
        if not text.strip():
            continue
        audio = await backend.synthesize(text, voice_id=voice_id, language=language)
        timings = _word_timings(text)
        duration = sum(t.duration_ms for t in timings) or 250
        seg = NarrationSegment(
            id=str(uuid.uuid4()),
            page_id=page_id,
            text=text,
            voice_id=voice_id,
            start_ms=cursor,
            duration_ms=duration,
            audio_bytes=audio,
            word_timings=timings,
        )
        out_segments.append(seg)
        cursor += duration + page_silence_ms
        blob_chunks.append(audio)
    track = NarrationTrack(
        id=str(uuid.uuid4()),
        document_id=document_id,
        language=language,
        voice_id=voice_id,
        narrator=NarratorKind.SINGLE,
        segments=tuple(out_segments),
        audio_bytes=b"|".join(blob_chunks),
    )
    return track


# ---------------------------------------------------------------------------
# Captions
# ---------------------------------------------------------------------------


def caption_from_narration(track: NarrationTrack) -> str:
    """Emit a WebVTT-formatted caption file from a narration track."""
    lines: list[str] = ["WEBVTT", ""]
    for seg in track.segments:
        start = _format_timestamp(seg.start_ms)
        end = _format_timestamp(seg.start_ms + seg.duration_ms)
        lines.append(f"{start} --> {end}")
        lines.append(seg.text)
        lines.append("")
    return "\n".join(lines)


def _format_timestamp(ms: int) -> str:
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d}.{ms:03d}"


# ---------------------------------------------------------------------------
# §26 Localization
# ---------------------------------------------------------------------------


# Spec §26 expansion-factor table — average text length vs English.
_EXPANSION: dict[str, float] = {
    "en": 1.0,
    "es": 1.2,
    "fr": 1.2,
    "de": 1.3,
    "pt": 1.2,
    "it": 1.2,
    "ru": 1.1,
    "ja": 0.6,
    "ko": 0.7,
    "zh": 0.5,
    "zh-Hans": 0.5,
    "zh-Hant": 0.5,
    "ar": 1.2,
    "he": 1.0,
    "hi": 1.1,
    "th": 0.9,
}


_RTL_LANGUAGES = frozenset({"ar", "he", "fa", "ur", "ar-SA"})


def expansion_factor(target_lang: str) -> float:
    """Return text-expansion multiplier vs English for the target language."""
    if target_lang in _EXPANSION:
        return _EXPANSION[target_lang]
    base = target_lang.split("-")[0]
    if base in _EXPANSION:
        return _EXPANSION[base]
    raise LanguageUnsupportedError(f"unknown language {target_lang!r}")


def is_rtl(language: str) -> bool:
    return language in _RTL_LANGUAGES or language.split("-")[0] in {"ar", "he", "fa", "ur"}


class MockTranslationBackend:
    """Deterministic translation backend.

    `translate(text, source_lang, target_lang)` produces a tagged copy
    that's reproducibly different from the source. Useful as a Protocol-
    shaped stand-in for tests + dev.
    """

    def __init__(self, *, refused: frozenset[str] = frozenset()) -> None:
        self._refused = refused

    async def translate(
        self,
        text: str,
        *,
        source_lang: str,
        target_lang: str,
        age_band: str | None = None,
    ) -> str:
        if not text.strip():
            return text
        if any(refusal in text for refusal in self._refused):
            raise TranslationFailedError("refused to translate (matched refusal pattern)")
        # Validate the target language even for the mock so callers can
        # catch unknown-language paths with the right error.
        expansion_factor(target_lang)
        prefix = f"[{target_lang}]"
        if age_band:
            prefix = f"[{target_lang}|age:{age_band}]"
        return f"{prefix} {text}"


def estimate_overflow_risk(
    text: str,
    *,
    target_lang: str,
    bbox_chars: int,
) -> bool:
    """True if the translated string is likely to overflow the bbox."""
    factor = expansion_factor(target_lang)
    estimated_len = int(len(text) * factor)
    return estimated_len > bbox_chars


def assert_fits(
    text: str,
    *,
    target_lang: str,
    bbox_chars: int,
) -> None:
    if estimate_overflow_risk(text, target_lang=target_lang, bbox_chars=bbox_chars):
        raise LocalizationOverflowError(
            f"text won't fit at {target_lang} expansion factor "
            f"({len(text)} chars × {expansion_factor(target_lang):.1f} > {bbox_chars})"
        )


# ---------------------------------------------------------------------------
# Bidi text segmentation (cheap)
# ---------------------------------------------------------------------------


_LATIN_RE = re.compile(r"[A-Za-z]+")


def segment_bidi(text: str) -> list[tuple[str, str]]:
    """Split a string into (direction, run) pairs.

    direction is `"ltr"` or `"rtl"`. Used at render time to set the
    appropriate Pillow text rendering direction for each run.
    """
    if not text.strip():
        return [("ltr", text)]
    segments: list[tuple[str, str]] = []
    cursor = 0
    for match in _LATIN_RE.finditer(text):
        if match.start() > cursor:
            segments.append(("rtl", text[cursor : match.start()]))
        segments.append(("ltr", match.group(0)))
        cursor = match.end()
    if cursor < len(text):
        segments.append(("rtl", text[cursor:]))
    if not segments:
        segments.append(("ltr", text))
    return segments
