"""Parser tests for check_vulture_whitelist.parse_whitelist.

Whitelist file lines come from `vulture --make-whitelist` output —
either bare identifiers, dotted-attr underscore form, or assignments,
each followed by a `# unused <kind> ...` comment.
"""

from __future__ import annotations

from check_vulture_whitelist import parse_whitelist


def test_extracts_bare_identifier_entry() -> None:
    line = "GuestPeerRegistry  # unused class (src/stronghold/a2a/guest_peers.py:85)"
    assert parse_whitelist(line) == {"GuestPeerRegistry"}


def test_extracts_underscore_attribute_form() -> None:
    line = "_.register_peer  # unused method (src/stronghold/a2a/guest_peers.py:92)"
    assert parse_whitelist(line) == {"_.register_peer"}


def test_extracts_function_name_entry() -> None:
    line = "check_mock_usage  # unused function (src/stronghold/agents/auditor/checks.py:54)"
    assert parse_whitelist(line) == {"check_mock_usage"}


def test_extracts_attribute_entry() -> None:
    line = "_.max_retries  # unused attribute (src/stronghold/agents/artificer/strategy.py:48)"
    assert parse_whitelist(line) == {"_.max_retries"}


def test_ignores_blank_lines_and_comments() -> None:
    text = (
        "# Vulture whitelist for Stronghold.\n"
        "#\n"
        "# Many 'unused' findings come from framework-mediated indirection ...\n"
        "\n"
        "GuestPeerRegistry  # unused class (src/stronghold/a2a/guest_peers.py:85)\n"
    )
    assert parse_whitelist(text) == {"GuestPeerRegistry"}


def test_collects_all_entries_from_real_excerpt() -> None:
    excerpt = (
        "GuestPeerRegistry  # unused class (src/stronghold/a2a/guest_peers.py:85)\n"
        "_.register_peer  # unused method (src/stronghold/a2a/guest_peers.py:92)\n"
        "_.remove_peer  # unused method (src/stronghold/a2a/guest_peers.py:96)\n"
        "_.list_peers  # unused method (src/stronghold/a2a/guest_peers.py:104)\n"
        "_.delegate  # unused method (src/stronghold/a2a/guest_peers.py:108)\n"
        "_.max_retries  # unused attribute (src/stronghold/agents/artificer/strategy.py:48)\n"
        "check_mock_usage  # unused function (src/stronghold/agents/auditor/checks.py:54)\n"
    )
    parsed = parse_whitelist(excerpt)
    assert len(parsed) == 7
    assert "_.register_peer" in parsed
    assert "check_mock_usage" in parsed


def test_parser_is_set_so_reordered_lines_compare_equal() -> None:
    """Re-ordered or whitespace-shifted whitelists are equivalent —
    only the *content* matters for the shrink-only check."""
    a = (
        "GuestPeerRegistry  # unused class (src/x.py:1)\n"
        "_.register_peer  # unused method (src/x.py:2)\n"
    )
    b = (
        "_.register_peer  # unused method (src/x.py:2)\n"
        "GuestPeerRegistry  # unused class (src/x.py:1)\n"
    )
    assert parse_whitelist(a) == parse_whitelist(b)


def test_parser_ignores_lines_lacking_unused_comment() -> None:
    """Defensive: never grab identifiers from lines that aren't whitelist
    entries — a future stray `import x` in this file shouldn't get
    counted."""
    text = (
        "import os  # noqa: hypothetical stray import\n"
        "Foo = 1  # ordinary comment, not a whitelist entry\n"
        "Bar  # unused class (src/x.py:1)\n"
    )
    assert parse_whitelist(text) == {"Bar"}
