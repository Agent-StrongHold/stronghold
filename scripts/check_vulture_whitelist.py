"""G-2 whitelist-shrink-only check for .vulture_whitelist.py.

Spec: ARCHITECTURE.md §16.4.2.

Vulture itself is already wired as a blocking gate; G-2's *new* piece is
enforcing that .vulture_whitelist.py never grows in a PR without explicit
operator approval (the `vulture-whitelist-grow` label, gated in workflow
YAML — this script trusts the workflow's filter).

Exits per §16.7.2:
  0 — whitelist did not grow (entries removed or unchanged).
  1 — whitelist grew (one or more entries added vs. base).
  2 — tool/contract error (file missing, git ref unreadable).

Stdlib only. Treats scripts/ as src-isolated per §16.9.9.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

WHITELIST_PATH = ".vulture_whitelist.py"

# A whitelist line either declares a name (with optional .attribute prefix)
# followed by an unused-* comment from `vulture --make-whitelist`, or it's
# pure prose / blank. We extract just the names so re-ordered files don't
# count as growth.
_ENTRY_RE = re.compile(
    r"^(?P<entry>[A-Za-z_][\w.]*|_\.\w+)"  # identifier or '_.<attr>' form
    r"(?:\s*=\s*\S.*?)?"  # optional assignment (vulture sometimes emits)
    r"\s*#\s*unused\s+",  # the comment that confirms it's a whitelist entry
    re.IGNORECASE,
)


def parse_whitelist(text: str) -> set[str]:
    """Extract the set of whitelist entries from the file's text.

    An entry is the leading identifier (or `_.<attr>` form) on any line
    that ends in a `# unused <kind> ...` comment — the standard format
    `vulture --make-whitelist` emits. Comment-only lines and blank lines
    are ignored, so re-flowing the prose at the top of the file does
    not count as growth.
    """
    entries: set[str] = set()
    for line in text.splitlines():
        m = _ENTRY_RE.match(line.strip())
        if m:
            entries.add(m["entry"])
    return entries


def diff_entries(base_text: str, head_text: str) -> tuple[set[str], set[str]]:
    """Return (added, removed) entry sets between two whitelist contents.

    Pure set-difference. The shrink-only policy fails on `added` being
    non-empty; `removed` is informational (the goal — celebrate it).
    """
    base = parse_whitelist(base_text)
    head = parse_whitelist(head_text)
    return head - base, base - head


def read_whitelist_at_ref(ref: str, path: str = WHITELIST_PATH) -> str:
    """Read .vulture_whitelist.py at a given git ref.

    Returns "" if the file did not exist at that ref (first-time-creation
    case — see test_brand_new_whitelist_has_every_entry_in_added).
    Raises subprocess.CalledProcessError if the ref itself is unknown.
    """
    proc = subprocess.run(  # noqa: S603 — fixed argv, no shell
        ["git", "show", f"{ref}:{path}"],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode == 0:
        return proc.stdout
    # `git show` returns 128 with "fatal: path '...' does not exist in '...'"
    # when the file was added in the PR. Treat that as empty base content.
    if "does not exist" in proc.stderr:
        return ""
    raise subprocess.CalledProcessError(
        proc.returncode, proc.args, output=proc.stdout, stderr=proc.stderr
    )


def _format_failure(added: set[str], removed: set[str]) -> str:
    lines = [f"FAIL: .vulture_whitelist.py grew by {len(added)} entr(ies):"]
    for name in sorted(added):
        lines.append(f"  + {name}")
    if removed:
        lines.append(f"(also removed {len(removed)} — thank you, but additions still block.)")
    lines.append(
        "If the additions are legitimate framework indirections, apply the "
        "'vulture-whitelist-grow' label to this PR (operator-tier reviewers only). "
        "Otherwise, fix the dead code rather than whitelisting it."
    )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    """Entrypoint. Returns the exit code (0/1/2 per §16.7.2)."""
    parser = argparse.ArgumentParser(
        description=(
            "G-2: enforce that .vulture_whitelist.py only shrinks. "
            "Skipped in workflow YAML when the 'vulture-whitelist-grow' "
            "label is on the PR."
        )
    )
    parser.add_argument(
        "--base",
        help="Git ref for the PR's base (e.g. origin/integration). "
        "Mutually exclusive with --from-file.",
    )
    parser.add_argument(
        "--from-file",
        type=Path,
        help="Read base whitelist content from FILE (hermetic test hook).",
    )
    parser.add_argument(
        "--to-file",
        type=Path,
        help="Read head whitelist content from FILE instead of "
        f"{WHITELIST_PATH} (hermetic test hook).",
    )
    args = parser.parse_args(argv)

    if args.base and args.from_file:
        print("ERROR: --base and --from-file are mutually exclusive", file=sys.stderr)
        return 2
    if not args.base and not args.from_file:
        print("ERROR: one of --base or --from-file is required", file=sys.stderr)
        return 2

    # Base content
    if args.from_file is not None:
        try:
            base_text = args.from_file.read_text()
        except OSError as exc:
            print(f"ERROR: --from-file unreadable: {exc}", file=sys.stderr)
            return 2
    else:
        try:
            base_text = read_whitelist_at_ref(args.base)
        except subprocess.CalledProcessError as exc:
            print(f"ERROR: git show failed: {exc.stderr}", file=sys.stderr)
            return 2

    # Head content
    head_path: Path = args.to_file if args.to_file is not None else Path(WHITELIST_PATH)
    try:
        head_text = head_path.read_text()
    except OSError as exc:
        print(f"ERROR: head whitelist unreadable: {exc}", file=sys.stderr)
        return 2

    added, removed = diff_entries(base_text, head_text)

    if not added:
        if removed:
            print(f"OK: whitelist shrank by {len(removed)} entr(ies).")
        else:
            print("OK: whitelist unchanged.")
        return 0

    print(_format_failure(added, removed))
    return 1


if __name__ == "__main__":
    sys.exit(main())
