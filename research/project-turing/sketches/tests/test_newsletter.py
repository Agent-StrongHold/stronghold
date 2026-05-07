"""Tests for NewsletterContentReader (runtime/tools/newsletter.py).

Spec: Scans a vault directory for markdown files with YAML frontmatter.
Parses title, source, date, tags from frontmatter; body becomes summary.

Acceptance criteria:
- AC-1: invoke returns parsed newsletters from .md files
- AC-2: incremental scan skips unchanged files
- AC-3: full scan rereads all files
- AC-4: empty/missing vault returns []
- AC-5: vault_dir="" raises ValueError
- AC-6: files without frontmatter still parse (title = filename stem)
- AC-7: malformed YAML falls back gracefully
"""

from __future__ import annotations

import pytest
from pathlib import Path

from turing.runtime.tools.newsletter import NewsletterContentReader, ParsedNewsletter


@pytest.fixture
def vault(tmp_path: Path) -> Path:
    d = tmp_path / "vault"
    d.mkdir()
    return d


def _write_md(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_ac5_empty_vault_dir_raises() -> None:
    with pytest.raises(ValueError):
        NewsletterContentReader(vault_dir="")


def test_ac4_missing_vault_returns_empty(tmp_path: Path) -> None:
    reader = NewsletterContentReader(vault_dir=tmp_path / "nonexistent")
    assert reader.invoke() == []


def test_ac1_parses_newsletter_with_frontmatter(vault: Path) -> None:
    _write_md(
        vault / "01.md",
        "---\ntitle: Test Title\nsource: huggingface\ntags: [ai, ml]\n---\nHello world. This is a test!",
    )
    reader = NewsletterContentReader(vault_dir=vault)
    results = reader.invoke()
    assert len(results) == 1
    r = results[0]
    assert isinstance(r, ParsedNewsletter)
    assert r.title == "Test Title"
    assert r.source == "huggingface"
    assert r.summary == "Hello world. This is a test!"
    assert r.sentence_count == 2
    assert "ai" in r.tags


def test_ac6_no_frontmatter_uses_filename(vault: Path) -> None:
    _write_md(vault / "my-file.md", "Just some content here.")
    reader = NewsletterContentReader(vault_dir=vault)
    results = reader.invoke()
    assert results[0].title == "my-file"
    assert results[0].source == "unknown"


def test_ac7_malformed_yaml_falls_back(vault: Path) -> None:
    _write_md(vault / "bad.md", "---\n[invalid yaml: }\n---\nContent here.")
    reader = NewsletterContentReader(vault_dir=vault)
    results = reader.invoke()
    assert len(results) == 1
    assert results[0].title == "bad"


def test_ac2_incremental_skips_unchanged(vault: Path) -> None:
    _write_md(vault / "a.md", "---\ntitle: A\n---\nAlpha.")
    reader = NewsletterContentReader(vault_dir=vault)
    first = reader.invoke()
    assert len(first) == 1
    second = reader.invoke(scan_mode="incremental")
    assert len(second) == 0


def test_ac3_full_rereads_all(vault: Path) -> None:
    _write_md(vault / "a.md", "---\ntitle: A\n---\nAlpha.")
    reader = NewsletterContentReader(vault_dir=vault)
    reader.invoke()
    full = reader.invoke(scan_mode="full")
    assert len(full) == 1


def test_empty_file_skipped(vault: Path) -> None:
    _write_md(vault / "empty.md", "")
    reader = NewsletterContentReader(vault_dir=vault)
    assert reader.invoke() == []


def test_date_parsing_iso_format(vault: Path) -> None:
    _write_md(
        vault / "dated.md",
        "---\ntitle: D\ncreated: 2026-01-15T10:30:00\n---\nDated content.",
    )
    reader = NewsletterContentReader(vault_dir=vault)
    results = reader.invoke()
    assert results[0].received_at is not None
    assert results[0].received_at.year == 2026


def test_received_at_fallback(vault: Path) -> None:
    _write_md(
        vault / "r.md",
        "---\ntitle: R\nreceived_at: 2026-03-01T12:00:00\n---\nContent.",
    )
    reader = NewsletterContentReader(vault_dir=vault)
    results = reader.invoke()
    assert results[0].received_at is not None
