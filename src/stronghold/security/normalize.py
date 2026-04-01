"""Unified normalization pipeline for security scanning.

Single entry point used by ALL security scanners (Warden, Sentinel PII
filter, Gate) to normalize text before pattern matching. Consolidates
NFKD normalization, zero-width stripping, whitespace collapsing, and
homoglyph replacement that were previously duplicated across modules.

STYLE_GUIDE.md section 1.1: every scanner MUST normalize through this pipeline
before applying detection patterns, to prevent bypass via Unicode tricks.
"""

from __future__ import annotations

import re
import unicodedata

# Zero-width characters that attackers use to split keywords and evade
# regex-based detection. Includes: ZERO WIDTH SPACE (U+200B),
# ZERO WIDTH NON-JOINER (U+200C), ZERO WIDTH JOINER (U+200D),
# BOM / ZERO WIDTH NO-BREAK SPACE (U+FEFF), SOFT HYPHEN (U+00AD).
_ZERO_WIDTH_RE = re.compile("[\u200b\u200c\u200d\ufeff\u00ad]")

# Whitespace collapse: any run of whitespace characters (space, tab,
# newline, carriage return, form feed, etc.) becomes a single space.
_WHITESPACE_RE = re.compile(r"\s+")

# Homoglyph mapping: Cyrillic and Greek letters that visually resemble
# Latin ASCII characters. Attackers substitute these to bypass keyword
# detection (e.g. Cyrillic "а" instead of Latin "a" in "admin").
#
# Coverage: common Cyrillic + Greek lookalikes. This is not exhaustive
# across all of Unicode, but covers the practical attack surface for
# English-language prompt injection and keyword evasion.
_HOMOGLYPH_MAP: dict[str, str] = {
    # Cyrillic lowercase
    "\u0430": "a",  # а → a
    "\u0435": "e",  # е → e
    "\u0456": "i",  # і → i (Ukrainian i)
    "\u043e": "o",  # о → o
    "\u0440": "p",  # р → p
    "\u0441": "c",  # с → c
    "\u0443": "y",  # у → y
    "\u0445": "x",  # х → x
    "\u044a": "b",  # ъ → b (weak; included for completeness)
    # Cyrillic uppercase
    "\u0410": "A",  # А → A
    "\u0412": "B",  # В → B
    "\u0415": "E",  # Е → E
    "\u041a": "K",  # К → K
    "\u041c": "M",  # М → M
    "\u041d": "H",  # Н → H
    "\u041e": "O",  # О → O
    "\u0420": "P",  # Р → P
    "\u0421": "C",  # С → C
    "\u0422": "T",  # Т → T
    "\u0425": "X",  # Х → X
    # Greek lowercase
    "\u03bf": "o",  # ο (omicron) → o
    "\u03b1": "a",  # α (alpha) → a — close enough for scanning
    # Greek uppercase
    "\u0391": "A",  # Α (Alpha) → A
    "\u0392": "B",  # Β (Beta) → B
    "\u0395": "E",  # Ε (Epsilon) → E
    "\u0397": "H",  # Η (Eta) → H
    "\u0399": "I",  # Ι (Iota) → I
    "\u039a": "K",  # Κ (Kappa) → K
    "\u039c": "M",  # Μ (Mu) → M
    "\u039d": "N",  # Ν (Nu) → N
    "\u039f": "O",  # Ο (Omicron) → O
    "\u03a1": "P",  # Ρ (Rho) → P
    "\u03a4": "T",  # Τ (Tau) → T
    "\u03a7": "X",  # Χ (Chi) → X
    "\u03a5": "Y",  # Υ (Upsilon) → Y
    "\u0396": "Z",  # Ζ (Zeta) → Z
}

# Build a single translation table for str.translate() — O(n) performance.
_HOMOGLYPH_TABLE = str.maketrans(_HOMOGLYPH_MAP)


def normalize_for_scanning(text: str, *, lowercase: bool = False) -> str:
    """Normalize text through the unified security scanning pipeline.

    Steps applied in order:
    1. NFKD Unicode normalization (decompose compatibility characters)
    2. Strip zero-width characters (U+200B, U+200C, U+200D, U+FEFF, U+00AD)
    3. Normalize whitespace (collapse runs of spaces/tabs/newlines to single space)
    4. Strip leading/trailing whitespace
    5. Optionally lowercase (for case-insensitive comparison)

    Args:
        text: Raw input text to normalize.
        lowercase: If True, lowercase the result for comparison. Default False.

    Returns:
        Normalized text ready for pattern matching.
    """
    # Step 1: NFKD — decomposes fi ligatures, fullwidth chars, etc.
    text = unicodedata.normalize("NFKD", text)

    # Step 2: Strip zero-width characters
    text = _ZERO_WIDTH_RE.sub("", text)

    # Step 3: Collapse whitespace
    text = _WHITESPACE_RE.sub(" ", text)

    # Step 4: Strip leading/trailing
    text = text.strip()

    # Step 5: Optional lowercase
    if lowercase:
        text = text.lower()

    return text


def strip_homoglyphs(text: str) -> str:
    """Replace Cyrillic/Greek visual lookalikes with ASCII equivalents.

    Uses str.translate() for O(n) single-pass replacement. Covers the
    practical attack surface for English-language keyword evasion.

    Args:
        text: Text potentially containing homoglyph characters.

    Returns:
        Text with homoglyphs replaced by their ASCII equivalents.
    """
    return text.translate(_HOMOGLYPH_TABLE)
