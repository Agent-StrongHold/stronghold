"""Diff-comparator tests for check_vulture_whitelist.diff_entries.

These exercise §16.4.2's shrink-only contract: a PR's whitelist may
remove entries (good — the goal) or stay identical (fine), but new
entries are blocked unless the workflow YAML's label-skip suppresses
the gate entirely.
"""

from __future__ import annotations

from check_vulture_whitelist import diff_entries


def _line(name: str, kind: str = "class", path: str = "src/x.py", lineno: int = 1) -> str:
    return f"{name}  # unused {kind} ({path}:{lineno})\n"


def test_identical_whitelists_have_no_added_or_removed() -> None:
    text = _line("Foo") + _line("Bar", "method")
    added, removed = diff_entries(text, text)
    assert added == set()
    assert removed == set()


def test_pr_added_entry_shows_up_in_added_set() -> None:
    base = _line("Foo")
    head = _line("Foo") + _line("NewlyAdded")
    added, removed = diff_entries(base, head)
    assert added == {"NewlyAdded"}
    assert removed == set()


def test_pr_removed_entry_shows_up_in_removed_set_not_added() -> None:
    """The shrink case — a refactor deletes dead code and the entry that
    suppressed its false-positive. This is what the gate exists to
    *encourage*, not block."""
    base = _line("OldDead") + _line("Stays")
    head = _line("Stays")
    added, removed = diff_entries(base, head)
    assert added == set()
    assert removed == {"OldDead"}


def test_pr_can_simultaneously_add_and_remove() -> None:
    """A net-zero swap (delete one entry, add another) still fails the
    gate — the policy is shrink-only, not shrink-or-swap. Operators
    must explicitly approve any addition."""
    base = _line("OldName")
    head = _line("NewName")
    added, removed = diff_entries(base, head)
    assert added == {"NewName"}
    assert removed == {"OldName"}


def test_reordering_alone_produces_empty_diff() -> None:
    base = _line("Alpha") + _line("Beta") + _line("Gamma")
    head = _line("Gamma") + _line("Alpha") + _line("Beta")
    added, removed = diff_entries(base, head)
    assert added == set()
    assert removed == set()


def test_whitespace_and_comment_changes_alone_produce_empty_diff() -> None:
    """Re-flowing the prose at the top of the file or adjusting blank
    lines mustn't trigger growth."""
    base = "# old prose\n\n" + _line("Foo")
    head = "# new prose with edits\n\n\n\n" + _line("Foo")
    added, removed = diff_entries(base, head)
    assert added == set()
    assert removed == set()


def test_underscore_form_added_is_detected() -> None:
    base = _line("Bar")
    head = _line("Bar") + "_.new_method  # unused method (src/x.py:2)\n"
    added, _removed = diff_entries(base, head)
    assert added == {"_.new_method"}


def test_brand_new_whitelist_has_every_entry_in_added() -> None:
    """First-time generation case: base has no whitelist file (empty
    text), head has all the entries. Every entry counts as added."""
    base = ""
    head = _line("A") + _line("B") + _line("C")
    added, removed = diff_entries(base, head)
    assert added == {"A", "B", "C"}
    assert removed == set()


def test_whitelist_emptied_returns_every_entry_in_removed() -> None:
    """Heroic-shrink case: PR refactors away every dead-code source.
    The whole baseline drops; this is the §16.4.2 'eventual state'."""
    base = _line("A") + _line("B") + _line("C")
    head = ""
    added, removed = diff_entries(base, head)
    assert added == set()
    assert removed == {"A", "B", "C"}
