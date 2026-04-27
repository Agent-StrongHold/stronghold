# 26 — Localization (i18n)

**Status**: P1 / Content phase. Multilingual books = a multiplier.
**One-liner**: same Document, N languages; auto-translate text, re-flow per
language metrics, preserve illustration consistency.

## Problem it solves

Selling a children's book in 5 languages is 5× the audience. Doing each
language by hand: 5× the work. Da Vinci should automate translation,
typography per script, and re-flow without breaking layouts.

## Data model

```
DocumentLocalization (frozen):
  source_document_id: str
  target_language: str             # BCP-47 e.g. "es", "ja", "ar-SA"
  target_document_id: str          # the localized document
  status: LocalizationStatus       # DRAFT | REVIEWED | PUBLISHED
  translation_model: str
  reviewer_id: str | None
  created_at, updated_at

LocalizationStatus (StrEnum):
  DRAFT       # auto-translation done, not reviewed
  REVIEWED    # human (or expert) accepted
  PUBLISHED   # exported / shipped
```

## Flow

```
1. SOURCE              user picks source Document + target language(s)
2. TRANSLATE           agent translates every text layer via LLM (translation-tuned)
3. REFLOW              text re-flows within slot bboxes (German is longer, CJK shorter)
4. TYPOGRAPHY          script-appropriate font fallback chain selected
5. REVIEW              user (or expert) reviews translations inline
6. PUBLISH             new Document version finalised; export available
```

## Translation engine

LLM-based, routed via existing LiteLLM. Translation-aware prompt:

```
Translate the following children's-book text from {source_lang} to {target_lang}.
Maintain reading level appropriate for ages {age_band}.
Preserve names and proper nouns unless transliteration is conventional in {target_lang}.
Match sentence rhythm where possible.
Output translation only, no explanation.

Text: "{source_text}"
```

Per-text-layer translation; preserves line breaks. Long text is chunked.

## Typography per script

| Script | Font default | Notes |
|---|---|---|
| Latin (en, es, fr, de, pt) | Atkinson Hyperlegible | as English |
| Cyrillic (ru, uk, sr) | Inter | Latin family with Cyrillic glyphs |
| Greek | Inter | similar |
| Arabic | Cairo | RTL; ligature shaping (uharfbuzz) |
| Hebrew | Frank Ruhl | RTL |
| Devanagari (hi) | Mukta | conjunct shaping |
| CJK (zh, ja, ko) | Noto Sans CJK | per region: zh-Hans, zh-Hant, ja, ko |
| Thai | Noto Sans Thai | dotless line breaking |

Bundled font set must cover these (cross-ref §05). Missing-glyph rule (§05)
auto-falls through chain.

## Re-flow per language

Different languages have different text metrics:

| Language | Avg expansion vs English |
|---|---|
| English | 1.0× |
| Spanish | 1.2× |
| French | 1.2× |
| German | 1.3× |
| Russian | 1.1× |
| Japanese | 0.6× |
| Korean | 0.7× |
| Chinese | 0.5× |
| Arabic | 1.2× (with RTL flip) |

Re-flow procedure:
1. Try same font_size and bbox: if fits, done
2. Try shrinking font_size by 5–15%: if fits and ≥ accessibility minimum, done
3. Try wrapping to more lines: if bbox allows, done
4. Try alternate text style (condensed variant): if available
5. Surface to user: "Spanish translation overflows on page 4 — manual review"

## RTL handling

For Arabic / Hebrew / RTL scripts:
- Each text layer's `direction` flag flips
- Layouts with verso/recto bind margins: binding side reverses
- Master pages: re-flowed for RTL reading order
- Page strip: pages still ordered ascending (page 1 reads first), but the
  *binding side* moves to the other edge

## Illustration consistency

Illustrations are NOT translated. Same character refs, same style lock,
same brand kit applied across languages. This is the magic: language
multiplies output without exploding generative cost.

Exceptions (worth flagging):
- Text *baked into illustrations* (signs, posters within the scene): per
  Da Vinci's MUST-NEVER rule, this shouldn't exist. If imported content has
  it, the localization flow surfaces it for user decision.
- Culture-specific imagery (e.g. specific holiday scenes): user-flagged for
  per-language regen.

## Per-language brand kit

Brand kits can be language-overridden:
- Different display fonts (e.g. Noto Sans CJK for Chinese editions)
- Different palette (rare; usually shared)
- Different logo variants (e.g. localized wordmark)

`BrandKit` gains `localized_variants: Mapping[str, BrandKit]` in P1.

## API surface

| Action | Args | Returns |
|---|---|---|
| `localization_create` | `source_document_id, target_languages` | tuple[DocumentLocalization, ...] |
| `localization_translate_layer` | `localization_id, layer_id` | layer with translated content |
| `localization_review` | `localization_id, accepted: bool` | DocumentLocalization |
| `localization_repaginate` | `localization_id` | re-flowed Document |
| `localization_list` | `source_document_id` | tuple[DocumentLocalization, ...] |
| `language_supported` | `lang_code` | bool + capabilities |

## Edge cases

1. **Translation contains markup the source didn't** — strip; warn.
2. **Translation refuses** (LLM safety) — surface; user supplies manually.
3. **Translation lengths cause text overflow on > 5 pages** — recommend
   per-language layout adjustment (e.g. shrink hero illustration to grow
   text bbox).
4. **Right-to-left language with embedded latin** (e.g. brand name) —
   bidi-isolate the latin run; no flip.
5. **Number formatting** (1,000 vs 1.000) — locale-aware; per text layer.
6. **Date formatting** — locale-aware in `text_format_date` helper.
7. **Currency symbols** — locale-aware; warn if currency inappropriate for
   target market.
8. **Hyphenation rules per language** — Pyphen library; per-locale.
9. **Translation review by reviewer not in tenant** — outside scope (P2
   collaboration §24).
10. **Re-paginating an already-localized doc** — preserves translations;
    re-flows only.
11. **CJK line-breaking** — no spaces; break per character / phrase
    boundary; uses uax14.

## Errors

- `LanguageUnsupportedError(ConfigError)`
- `TranslationFailedError(RoutingError)` — LLM refused / errored
- `LocalizationOverflowError(ConfigError)` — text won't fit anywhere
- `BiDiError(ToolError)` — bidi algorithm failure (rare)

## Test surface

- Unit: translation prompt construction; re-flow shrink algorithm; per-script
  font selection; bidi flipping.
- Integration: localize fixture book to es/ja/ar → expected page count and
  text layer changes; illustrations unchanged.
- Property: re-pagination is idempotent.
- Security: source documents and translations are tenant-scoped; LLM call
  cost-gated per §31.

## Dependencies

- existing LiteLLM (translation-tuned model option)
- `python-bidi`, `uharfbuzz` (already in §05)
- `Pyphen` (hyphenation)
- `Babel` (locale data)
- bundled font set covering scripts above
