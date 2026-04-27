Feature: Text rendering
  First-class text layers with full typographic control. Variable fonts,
  drop caps, text on path, text-to-shape, RTL bidi, emoji.

  See ../05-text.md.

  Background:
    Given an authenticated user in tenant "acme"
    And a Page of size 1024x1024
    And the bundled font set is available

  @p0 @critical
  Scenario: Render basic text layer with defaults
    When I create a text layer with content "Hello"
    Then the layer renders successfully
    And the rasterized output is non-empty
    And no glyphs are missing

  @p0
  Scenario Outline: Apply text style fields
    When I render text "Sample" with <field>=<value>
    Then the rasterized output reflects <field>
    And the layer style has <field>=<value>

    Examples:
      | field          | value      |
      | font_family    | Roboto     |
      | size_px        | 96         |
      | color          | #FF0000    |
      | letter_spacing | 0.1        |
      | line_height    | 1.5        |
      | underline      | true       |
      | strikethrough  | true       |

  @p0
  Scenario Outline: Text transform applies to rendered glyphs
    When I render "Hello World" with text_transform=<transform>
    Then the rendered text reads "<expected>"

    Examples:
      | transform | expected      |
      | NONE      | Hello World   |
      | UPPERCASE | HELLO WORLD   |
      | LOWERCASE | hello world   |
      | TITLECASE | Hello World   |

  @p0
  Scenario: Auto-wrap on max_width
    When I render "the quick brown fox" with size_px=24, max_width_px=120
    Then the text wraps onto multiple lines on whitespace
    And no line exceeds 120px

  @p0
  Scenario: Hyphenation when a word exceeds max_width
    When I render "supercalifragilisticexpialidocious" with size_px=24, max_width_px=80, hyphenate=true
    Then the word is broken with a hyphen at a syllable boundary

  @p0
  Scenario: Truncation with ellipsis at max_lines
    When I render a 5-line paragraph with max_lines=3
    Then the rendered text has 3 lines
    And the last line ends with "…"

  @p0 @critical
  Scenario: Drop cap wraps body text around the enlarged first letter
    When I add a drop_cap effect of 3 lines on a paragraph
    Then the first letter is enlarged to span 3 line heights
    And subsequent text wraps to its right
    And the third body line baseline aligns with the drop cap baseline

  @p0
  Scenario: Variable font axes within range applied
    Given font "Inter Variable" supports weight 100..900
    When I render with font_weight=550 (between regular and medium)
    Then the rendered glyphs use weight 550

  @p0
  Scenario: Variable font axes out of range are clamped
    Given font "Inter Variable" supports weight 100..900
    When I render with font_weight=1500
    Then the rendered glyphs use weight 900
    And a warning is emitted

  @p0
  Scenario: Missing glyph falls through script-aware fallback
    Given font "Inter" lacks Devanagari glyphs
    When I render "नमस्ते"
    Then a Devanagari fallback font is used
    And the result has no missing-glyph boxes

  @p0
  Scenario: Missing glyph with no fallback shows tofu
    Given a Private Use Area codepoint with no font support
    When I render it
    Then the rendered output contains a "□" tofu box
    And the result metadata includes a MissingGlyphWarning

  @p0 @critical
  Scenario: RTL text renders right-to-left with proper bidi
    When I render Arabic text "مرحبا"
    Then the glyphs are in correct visual order
    And final-form glyphs appear at the start of the visual line

  @p0
  Scenario: Mixed RTL+LTR text uses bidi algorithm
    When I render "Visit مرحبا today"
    Then the LTR runs and RTL run are correctly ordered

  @p0
  Scenario: Emoji renders via colour fallback font
    When I render "Hello 🐉"
    Then the dragon emoji uses a colour glyph from the Twemoji fallback

  @p0
  Scenario: Text on path follows the path
    Given a Bezier path layer "P1"
    When I render text along path "P1"
    Then glyphs are placed along the path
    And glyph rotations follow the path tangent

  @p0
  Scenario: Text on path shorter than text truncates with ellipsis
    Given a path of length 100px
    And text rendering longer than 100px at the chosen size
    When I render text on the path
    Then the text is truncated with "…" at the end of the path

  @p0
  Scenario: text_to_shape converts glyphs to vector paths
    Given a text layer "T1"
    When I call text_to_shape on "T1"
    Then "T1" becomes a shape layer of kind PATH
    And the path commands trace the original glyph outlines
    And the layer can be filled, stroked, or path-op'd

  @p0 @security
  Scenario: Custom font with unknown tables is rejected
    Given a TTF with table "EVIL"
    When the user uploads it
    Then FontValidationError is raised
    And the font is not stored

  @p0 @security
  Scenario: Custom font with oversized prep table is rejected
    Given a TTF with prep table > 1KB
    When the user uploads it
    Then FontValidationError is raised

  @p0 @security
  Scenario: Tenant-uploaded font is tenant-scoped
    Given alice (tenant acme) uploads font "AcmeSans"
    When bob (tenant globex) lists fonts
    Then "AcmeSans" is not in bob's list

  @p1
  Scenario: Justify alignment distributes word spacing
    When I render a 3-word paragraph with alignment=JUSTIFY, max_width_px=400
    Then word spacing is distributed so the line ends at 400px

  @p1
  Scenario: Vertical alignment within a fixed bbox
    Given a max_width and max_lines bounding the text
    When alignment is MIDDLE vertical
    Then the text is centred vertically inside the bbox
