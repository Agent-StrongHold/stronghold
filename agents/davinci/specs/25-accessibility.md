# 25 — Accessibility

**Status**: P0 / Trust phase. Children's content has higher accessibility
duty than general design.
**One-liner**: bake accessibility defaults into the system, validate every
deliverable, default to the more accessible option.

## Problem it solves

Kids' books and educational materials must be readable for children with
dyslexia, low vision, colour-blindness. Posters and infographics must meet
WCAG contrast for public display. Without an accessibility layer:
- A LoRA trained on inaccessible defaults bakes them in
- A template marketplace ships inaccessible templates
- A "looks fine" cover fails screen readers

## Defaults (P0)

The system ships with accessibility-first defaults that the user can override
but must do so explicitly.

| Concern | Default | Override required to lower |
|---|---|---|
| Body font (kids' books) | Atkinson Hyperlegible | yes |
| Body font (general) | Inter Regular | no |
| Body size (age 3-5) | 24pt minimum | yes |
| Body size (age 5-7) | 18pt minimum | yes |
| Body size (age 7-9) | 14pt minimum | yes |
| Body size (general) | 12pt minimum | no |
| Text contrast | WCAG AA (4.5:1 normal, 3:1 large) | yes (warn) |
| Line height | 1.4× (kids 1.6×) | no |
| Justify alignment | off (ragged-right preferred) | no |
| Link colour | distinct from body, not red/green only | no |
| Brand-kit palette | colour-blind-safe (Daltonism check) | warn-only |
| Alt-text per illustration | required (auto-generated) | warn at export |

## Pre-flight rules contributed (cross-ref §22)

| rule_id | Level | Implementation |
|---|---|---|
| `wcag_text_contrast` | WARN/FAIL | YIQ luminance ratio per text layer over its background composite |
| `body_size_age_appropriate` | WARN | size_px vs age_band table |
| `dyslexia_font_used` | INFO | recommend Atkinson Hyperlegible for kids' books |
| `alt_text_present` | WARN | every illustration layer has non-empty alt |
| `colorblind_safe_palette` | WARN | brand kit through deutan/protan/tritan simulation; pairwise distance check |
| `heading_hierarchy_present` | WARN | text styles map to logical hierarchy (no h3 without h2) |
| `language_declared` | WARN | document language tag set (for screen readers) |
| `tab_order_sensible` | INFO | (interactive PDF/ePub) reading order matches visual order |

## Alt-text generation

Every illustration layer auto-generates an alt-text via vision-LLM:

```
def generate_alt_text(layer, page_context, doc_audience) -> str:
    prompt = f"""
    Describe this illustration for a screen reader, in 1-2 sentences.
    Audience: {doc_audience}.
    Context: this appears on a {page_context.page_kind} of a
    {doc.kind} titled "{doc.name}".
    Be concrete; avoid "an image of"; do not editorialise.
    """
    return vision_llm.describe(layer.rendered_bytes, prompt)
```

User can edit; saved per-layer. Re-generated on layer source change.

## Color-blind safe palette

Brand kit creation (§11) and style brief (§32) run a Daltonism check:

```
def colorblind_safe(palette: tuple[Color, ...]) -> CheckResult:
    for kind in (DEUTAN, PROTAN, TRITAN):
        simulated = [simulate(c, kind) for c in palette]
        # check pairwise CIE76 ΔE distances stay above threshold
        for i, j in pairwise(simulated):
            if delta_e(i, j) < 10.0:
                return WARN with details
    return OK
```

`simulate()` uses `colormath` matrices; `delta_e()` is CIEDE2000 from same lib.

## Reading-level matching

For text-heavy children's books and early readers, the body text's
Flesch-Kincaid grade level is computed and compared to the document's
declared age band:

| AgeBand | Target FK grade |
|---|---|
| 0_3 | 0-1 |
| 3_5 | 1-2 |
| 5_7 | 2-3 |
| 7_9 | 3-5 |
| 9_12 | 5-7 |

Drift > 1 grade = WARN with "consider simpler/more advanced wording".

## Dyslexia-friendly mode

Toggle on the document or globally per user. When on:
- Body font defaults to Atkinson Hyperlegible (or OpenDyslexic if user prefers)
- Letter spacing increased by 0.05em
- Line height ≥ 1.6×
- Background colour shifted to off-white (#FFF8E7 cream by default)
- Justified alignment disabled
- Italic body text disabled

## Document language declaration

Every Document declares a `language` (BCP-47 tag, e.g. "en-US", "es", "ar").
- Affects spell-check dict, hyphenation, line-breaking
- Embedded in PDF /Lang attribute for screen readers
- Embedded in ePub/HTML lang attribute
- Rendered glyphs use script-appropriate fallbacks

## Export accessibility

PDF/UA export (P1) — tagged PDF for accessibility:
- `/StructTreeRoot` with reading order
- Image alt-text in `/Alt` properties
- Language declared in catalog
- Tab order in `/Tabs`

ePub export (P1, §13) — built-in accessibility via XHTML structure.

## API surface

| Action | Args | Returns |
|---|---|---|
| `alt_text_generate` | `layer_id` | str |
| `alt_text_set` | `layer_id, text` | layer with alt |
| `accessibility_report` | `document_id` | PreflightReport (filtered to access rules) |
| `dyslexia_mode_toggle` | `document_id, on/off` | document with overrides |
| `palette_colorblind_check` | `colors` | CheckResult |

## Edge cases

1. **Auto alt-text describes inappropriate content** — Warden scan; redact;
   user prompted to author manually.
2. **Brand kit palette tested colour-blind safe but a layer's prominent
   non-brand colour fails** — per-page warning, not document-level.
3. **Reading level fails because of one technical word** — allow per-doc
   "vocabulary exception list".
4. **Justified text turned on by user** — show inline accessibility warning;
   do not block.
5. **Text on a busy illustration background** — contrast check sees average;
   add a check for *minimum local contrast* over a sliding window.
6. **Variable-font weight chosen below W400 for body text** — auto-bump or
   warn; legibility falls off below regular weight.
7. **Image-only book (wordless)** — alt-text required per spread; auto-gen
   produces longer descriptions for wordless books.
8. **Right-to-left language** — reading order must reverse; test via screen
   reader fixture.

## Errors

- `AltTextRequiredError(SecurityError, code="ALT_TEXT_REQUIRED")` — only
  raised on export with strict accessibility mode
- `ContrastFailedError(ConfigError, code="CONTRAST_FAILED")` — strict mode

## Test surface

- Unit: every WCAG ratio computation against a known table; FK grade match;
  Daltonism simulation correctness vs reference matrices.
- Integration: full doc through accessibility_report → expected findings;
  dyslexia mode flips fonts everywhere.
- Property: contrast(A, B) == contrast(B, A); auto alt-text never empty
  for non-empty layers.
- Real assets: Atkinson Hyperlegible bundled; OpenDyslexic optional via
  font upload.

## Dependencies

- `colormath` (Daltonism, ΔE)
- `textstat` (Flesch-Kincaid)
- vision-LLM (existing)
- Atkinson Hyperlegible font (Apache-2.0 license)
- OpenDyslexic (Bitstream Vera license, optional)
