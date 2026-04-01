"""Tests for the unified normalization pipeline.

Covers NFKD normalization, zero-width character stripping, whitespace
collapsing, homoglyph replacement, and edge cases.
"""

from __future__ import annotations

from stronghold.security.normalize import normalize_for_scanning, strip_homoglyphs


class TestNormalizeForScanning:
    """Tests for normalize_for_scanning()."""

    def test_nfkd_applied(self) -> None:
        """NFKD decomposes compatibility characters (e.g. fi ligature)."""
        # U+FB01 = fi ligature, NFKD decomposes to "fi"
        result = normalize_for_scanning("\ufb01le")
        assert "fi" in result

    def test_nfkd_fullwidth_latin(self) -> None:
        """NFKD normalizes fullwidth Latin letters to ASCII equivalents."""
        # U+FF41 = fullwidth 'a', U+FF42 = fullwidth 'b'
        result = normalize_for_scanning("\uff41\uff42\uff43")
        assert result == "abc"

    def test_zero_width_stripped(self) -> None:
        """Zero-width characters are removed entirely."""
        # U+200B ZERO WIDTH SPACE, U+200C ZERO WIDTH NON-JOINER,
        # U+200D ZERO WIDTH JOINER, U+FEFF BOM, U+00AD SOFT HYPHEN
        text = "he\u200bl\u200cl\u200do\ufeff w\u00adorld"
        result = normalize_for_scanning(text)
        assert result == "hello world"

    def test_zero_width_only_input(self) -> None:
        """Input consisting solely of zero-width characters yields empty string."""
        text = "\u200b\u200c\u200d\ufeff\u00ad"
        result = normalize_for_scanning(text)
        assert result == ""

    def test_whitespace_collapsed(self) -> None:
        """Multiple spaces, tabs, and newlines collapse to single space."""
        text = "hello   \t\t  \n\n  world"
        result = normalize_for_scanning(text)
        assert result == "hello world"

    def test_leading_trailing_whitespace_stripped(self) -> None:
        """Leading and trailing whitespace is removed."""
        text = "   hello world   "
        result = normalize_for_scanning(text)
        assert result == "hello world"

    def test_lowercase_default_off(self) -> None:
        """By default, case is preserved."""
        result = normalize_for_scanning("Hello World")
        assert result == "Hello World"

    def test_lowercase_enabled(self) -> None:
        """When lowercase=True, output is lowercased."""
        result = normalize_for_scanning("Hello WORLD", lowercase=True)
        assert result == "hello world"

    def test_empty_string(self) -> None:
        """Empty string returns empty string."""
        result = normalize_for_scanning("")
        assert result == ""

    def test_plain_ascii_passthrough(self) -> None:
        """Plain ASCII text passes through unchanged (minus extra whitespace)."""
        text = "simple test string"
        result = normalize_for_scanning(text)
        assert result == "simple test string"

    def test_combined_pipeline(self) -> None:
        """All steps work together: NFKD + zero-width + whitespace + lowercase."""
        # Fullwidth 'A' + zero-width space + multiple spaces + fi ligature
        text = "\uff21\u200b   \ufb01le"
        result = normalize_for_scanning(text, lowercase=True)
        assert result == "a file"

    def test_carriage_return_normalized(self) -> None:
        """Carriage returns (\\r\\n) are collapsed like other whitespace."""
        text = "line one\r\nline two\rline three"
        result = normalize_for_scanning(text)
        assert result == "line one line two line three"


class TestStripHomoglyphs:
    """Tests for strip_homoglyphs()."""

    def test_cyrillic_a_replaced(self) -> None:
        """Cyrillic 'a' (U+0430) is replaced with ASCII 'a'."""
        # \u0430 = Cyrillic small letter a
        result = strip_homoglyphs("\u0430dmin")
        assert result == "admin"

    def test_cyrillic_e_replaced(self) -> None:
        """Cyrillic 'e' (U+0435) is replaced with ASCII 'e'."""
        result = strip_homoglyphs("s\u0435cret")
        assert result == "secret"

    def test_cyrillic_o_replaced(self) -> None:
        """Cyrillic 'o' (U+043E) is replaced with ASCII 'o'."""
        result = strip_homoglyphs("r\u043e\u043et")
        assert result == "root"

    def test_cyrillic_p_replaced(self) -> None:
        """Cyrillic 'p' (U+0440) is replaced with ASCII 'p'."""
        result = strip_homoglyphs("\u0440assword")
        assert result == "password"

    def test_greek_omicron_replaced(self) -> None:
        """Greek small letter omicron (U+03BF) is replaced with ASCII 'o'."""
        result = strip_homoglyphs("r\u03bf\u03bft")
        assert result == "root"

    def test_cyrillic_uppercase_replaced(self) -> None:
        """Cyrillic uppercase lookalikes are replaced with ASCII equivalents."""
        # \u0410 = Cyrillic A, \u0412 = Cyrillic B (looks like B),
        # \u0421 = Cyrillic S (looks like C)
        result = strip_homoglyphs("\u0410\u0412\u0421")
        assert result == "ABC"

    def test_mixed_cyrillic_and_ascii(self) -> None:
        """Mixed Cyrillic homoglyphs and real ASCII are normalized."""
        # "ignore" with Cyrillic 'i' (\u0456) and 'o' (\u043E)
        result = strip_homoglyphs("\u0456gn\u043ere")
        assert result == "ignore"

    def test_plain_ascii_unchanged(self) -> None:
        """Plain ASCII text passes through unchanged."""
        result = strip_homoglyphs("hello world")
        assert result == "hello world"

    def test_empty_string(self) -> None:
        """Empty string returns empty string."""
        result = strip_homoglyphs("")
        assert result == ""
