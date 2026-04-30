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

import re

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
