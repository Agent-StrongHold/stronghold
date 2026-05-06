"""Manuscript import (spec §33).

Parse Markdown / plain text manuscripts into pages-worth of structured
text, with chapter/section detection + scene-break markers + per-age-band
pagination. DOCX/EPUB/PDF parsing is deferred behind a thin format
dispatcher so the surrounding plumbing tests against deterministic
in-memory parsers.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum

from stronghold.tools.canvas_layouts import auto_paginate_word_count
from stronghold.types.canvas_design import AgeBand, LayoutKind
from stronghold.types.errors import (
    ManuscriptEncodingError,
    ManuscriptFormatUnsupportedError,
    ManuscriptParseError,
)


class ManuscriptFormat(StrEnum):
    MARKDOWN = "markdown"
    PLAIN = "plain"
    DOCX = "docx"
    EPUB = "epub"
    PDF = "pdf"


class BlockKind(StrEnum):
    PARAGRAPH = "paragraph"
    HEADING = "heading"
    LIST_ITEM = "list_item"
    QUOTE = "quote"
    DIALOGUE = "dialogue"
    SCENE_BREAK = "scene_break"
    CHAPTER_BREAK = "chapter_break"
    PAGE_BREAK = "page_break"


@dataclass(frozen=True)
class TextBlock:
    kind: BlockKind
    content: str
    level: int = 0
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class ManuscriptPage:
    ordering: int
    layout_kind: LayoutKind
    blocks: tuple[TextBlock, ...]
    illustration_prompt: str | None = None


@dataclass(frozen=True)
class Manuscript:
    blocks: tuple[TextBlock, ...]
    pages: tuple[ManuscriptPage, ...]
    chapter_count: int
    word_count: int
    language: str
    warnings: tuple[str, ...] = ()


# ---------------------------------------------------------------------------
# Parser dispatch
# ---------------------------------------------------------------------------


def parse(
    file_bytes: bytes,
    fmt: ManuscriptFormat,
    *,
    encoding: str = "utf-8",
) -> tuple[TextBlock, ...]:
    if fmt is ManuscriptFormat.MARKDOWN:
        return _parse_markdown(_decode(file_bytes, encoding))
    if fmt is ManuscriptFormat.PLAIN:
        return _parse_plain(_decode(file_bytes, encoding))
    if fmt in (ManuscriptFormat.DOCX, ManuscriptFormat.EPUB, ManuscriptFormat.PDF):
        # Production wires python-docx / ebooklib / pdfplumber here.
        # The in-memory plumbing rejects so callers that need the format
        # see a clear error instead of silent fallback.
        raise ManuscriptFormatUnsupportedError(
            f"format {fmt.value!r} requires its provider library; "
            "in-process parsing not implemented in this slice"
        )
    raise ManuscriptFormatUnsupportedError(f"unknown format {fmt!r}")


def _decode(file_bytes: bytes, encoding: str) -> str:
    try:
        return file_bytes.decode(encoding)
    except UnicodeDecodeError as exc:
        # Best-effort retry with utf-8-sig + latin-1
        for fallback in ("utf-8-sig", "latin-1"):
            try:
                return file_bytes.decode(fallback)
            except UnicodeDecodeError:
                continue
        raise ManuscriptEncodingError(f"could not decode bytes: {exc}") from exc


# ---------------------------------------------------------------------------
# Markdown + plain parsers
# ---------------------------------------------------------------------------


_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")
_SCENE_RE = re.compile(r"^\s*(?:\*\s*\*\s*\*|---|~~~)\s*$")
_LIST_RE = re.compile(r"^\s*[-*+]\s+")
_QUOTE_RE = re.compile(r"^\s*>\s?")


def _parse_markdown(text: str) -> tuple[TextBlock, ...]:
    blocks: list[TextBlock] = []
    in_code = False
    paragraph_buffer: list[str] = []

    def flush_paragraph() -> None:
        if not paragraph_buffer:
            return
        joined = " ".join(paragraph_buffer).strip()
        if joined:
            blocks.append(TextBlock(kind=BlockKind.PARAGRAPH, content=joined))
        paragraph_buffer.clear()

    for raw in text.splitlines():
        line = raw.rstrip()
        if line.startswith("```"):
            in_code = not in_code
            flush_paragraph()
            continue
        if in_code:
            # Treat code blocks as monospace paragraph annotations
            paragraph_buffer.append(line)
            continue
        if _SCENE_RE.match(line):
            flush_paragraph()
            blocks.append(TextBlock(kind=BlockKind.SCENE_BREAK, content=""))
            continue
        if not line.strip():
            flush_paragraph()
            continue
        m = _HEADING_RE.match(line)
        if m:
            flush_paragraph()
            level = len(m.group(1))
            content = m.group(2).strip()
            kind = BlockKind.CHAPTER_BREAK if level == 1 else BlockKind.HEADING
            blocks.append(TextBlock(kind=kind, content=content, level=level))
            continue
        if _LIST_RE.match(line):
            flush_paragraph()
            blocks.append(TextBlock(kind=BlockKind.LIST_ITEM, content=_LIST_RE.sub("", line, 1)))
            continue
        if _QUOTE_RE.match(line):
            flush_paragraph()
            blocks.append(TextBlock(kind=BlockKind.QUOTE, content=_QUOTE_RE.sub("", line, 1)))
            continue
        paragraph_buffer.append(line)
    flush_paragraph()
    if not blocks:
        raise ManuscriptParseError("manuscript produced no blocks")
    return tuple(blocks)


def _parse_plain(text: str) -> tuple[TextBlock, ...]:
    blocks: list[TextBlock] = []
    for paragraph in re.split(r"\n\s*\n", text):
        stripped = paragraph.strip()
        if not stripped:
            continue
        blocks.append(TextBlock(kind=BlockKind.PARAGRAPH, content=stripped))
    if not blocks:
        raise ManuscriptParseError("plain manuscript produced no blocks")
    return tuple(blocks)


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------


_CHAPTER_BREAK_BUDGET = 1  # 1 illustration slot per scene break per page


def paginate(
    blocks: tuple[TextBlock, ...],
    *,
    age_band: AgeBand,
    interior_layout: LayoutKind = LayoutKind.ART_WITH_BODY,
    chapter_layout: LayoutKind = LayoutKind.TEXT_ONLY,
) -> list[ManuscriptPage]:
    """Greedy paginator. CHAPTER_BREAKs force a new page; SCENE_BREAKs add
    illustration slots; otherwise pack PARAGRAPHs to the age-band wpp."""
    pages: list[ManuscriptPage] = []
    current: list[TextBlock] = []
    illustration_prompt: str | None = None
    page_layout = interior_layout

    def commit_page(force_layout: LayoutKind | None = None) -> None:
        nonlocal current, illustration_prompt, page_layout
        if not current and force_layout is None:
            return
        layout = force_layout or page_layout
        pages.append(
            ManuscriptPage(
                ordering=len(pages),
                layout_kind=layout,
                blocks=tuple(current),
                illustration_prompt=illustration_prompt,
            )
        )
        current = []
        illustration_prompt = None
        page_layout = interior_layout

    word_budget = 0
    target = _wpp_for(age_band)
    for block in blocks:
        if block.kind is BlockKind.CHAPTER_BREAK:
            commit_page()
            current.append(block)
            page_layout = chapter_layout
            continue
        if block.kind is BlockKind.SCENE_BREAK:
            # Capture an illustration slot: take last paragraph as scene context
            ctx = next(
                (
                    b.content
                    for b in reversed(current)
                    if b.kind in (BlockKind.PARAGRAPH, BlockKind.HEADING)
                ),
                "",
            )
            illustration_prompt = ctx[:200] if ctx else "scene-break illustration"
            continue
        if block.kind is BlockKind.PAGE_BREAK:
            commit_page()
            continue
        words = len(block.content.split())
        if word_budget + words > target and current:
            commit_page()
            word_budget = 0
        current.append(block)
        word_budget += words
    commit_page()
    return pages


def _wpp_for(age_band: AgeBand) -> int:
    return {
        AgeBand.AGE_0_3: 30,
        AgeBand.AGE_3_5: 40,
        AgeBand.AGE_5_7: 60,
        AgeBand.AGE_7_9: 90,
        AgeBand.AGE_9_12: 250,
        AgeBand.TEEN: 400,
        AgeBand.GENERAL: 250,
    }[age_band]


# ---------------------------------------------------------------------------
# End-to-end ingest
# ---------------------------------------------------------------------------


def import_manuscript(
    file_bytes: bytes,
    fmt: ManuscriptFormat,
    *,
    age_band: AgeBand,
    language: str = "en",
    encoding: str = "utf-8",
) -> Manuscript:
    blocks = parse(file_bytes, fmt, encoding=encoding)
    pages = tuple(paginate(blocks, age_band=age_band))
    chapter_count = sum(1 for b in blocks if b.kind is BlockKind.CHAPTER_BREAK)
    word_count = sum(len(b.content.split()) for b in blocks)
    expected_pages = auto_paginate_word_count(
        " ".join(b.content for b in blocks), age_band=age_band.value
    )
    warnings: list[str] = []
    if len(pages) > expected_pages * 2:
        warnings.append("paginated_more_than_expected")
    return Manuscript(
        blocks=blocks,
        pages=pages,
        chapter_count=chapter_count,
        word_count=word_count,
        language=language,
        warnings=tuple(warnings),
    )
