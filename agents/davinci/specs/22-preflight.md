# 22 — Pre-flight & Validation

**Status**: P0 / Trust phase. Gate to every export.
**One-liner**: a structured lint pass over a Document that catches
print-/screen-readiness problems before delivery.

## Problem it solves

Non-technical users cannot diagnose why a printed book has text in the bleed,
why a poster has missing fonts, or why a Whisper-captioned video has untimed
captions. Pre-flight runs every check up-front and produces a structured
report keyed to specific layers/pages so it can be acted on (by the agent or
by the user via the UI's "fix" button).

## Data model

```
PreflightReport (frozen):
  document_id: str
  generated_at: datetime
  level: ReportLevel        # OK | WARN | FAIL
  checks: tuple[CheckResult, ...]
  summary: PreflightSummary

CheckResult (frozen):
  rule_id: str              # "text_in_safe_area"
  scope: CheckScope         # DOCUMENT | PAGE | LAYER
  scope_id: str             # the page or layer id; empty for DOCUMENT
  level: ReportLevel        # OK | WARN | FAIL
  message: str              # human-readable
  detail: Mapping[str, Any] # structured (e.g. {"text_bbox": [...], "safe": [...]})
  fix_suggestion: FixSuggestion | None

FixSuggestion (frozen):
  action: str               # canvas tool action name to invoke
  arguments: Mapping[str, Any]
  reasoning: str

PreflightSummary (frozen):
  total: int
  ok: int
  warnings: int
  failures: int
```

## Rule catalogue

P0 rules grouped by concern.

### Print-readiness (only for Pages whose `print_spec.color_mode != SRGB` or DPI ≥ 300)

| rule_id | Level | Check |
|---|---|---|
| `text_in_safe_area` | FAIL | every text layer bbox ⊂ safe-area rect |
| `bg_covers_bleed` | FAIL | union of background layers ⊇ bleed rect |
| `dpi_minimum` | FAIL | every raster layer ≥ page DPI at rendered scale |
| `fonts_embeddable` | FAIL | every used font has embedding rights ≥ editable |
| `colors_in_gamut` | WARN | if CMYK, no rendered pixel out of CMYK gamut beyond threshold |
| `page_count_parity` | WARN | picture_book pages divisible by 4 |
| `binding_creep_safe` | WARN | saddle-stitch ≤ 64 pages |
| `page_count_min_max` | FAIL | document kind has min/max pages (board book 8-24, picture book 24-48, etc.) |

### Generative-quality

| rule_id | Level | Check |
|---|---|---|
| `no_draft_in_proof_set` | FAIL | every layer marked "delivery" must be tier=proof or upload |
| `style_lock_drift` | WARN | per page, vision-LLM drift score vs. style lock < threshold |
| `character_consistency` | WARN | named character refs match references on the page (face-embedding cosine) |
| `aspect_ratio_match` | WARN | layer aspect ratio ≈ container slot ratio (no stretched faces) |

### Text quality

| rule_id | Level | Check |
|---|---|---|
| `spelling_check` | WARN | spell-check via `pyspellchecker` against locale dict |
| `reading_level_match` | WARN | Flesch-Kincaid grade matches doc's `age_band` (within 1 grade) |
| `text_overflow` | FAIL | no `TextOverflowWarning` left unresolved on any text layer |
| `missing_glyph` | FAIL | no `MissingGlyphWarning` left unresolved |
| `orphan_widow` | WARN | typographic orphans/widows in body paragraphs |
| `untimed_caption` | FAIL | (video docs) all caption tracks have timestamps |

### Security / correctness

| rule_id | Level | Check |
|---|---|---|
| `warden_clean` | FAIL | every layer's source content has clean Warden verdict |
| `tenant_assets_only` | FAIL | every blob/font/asset is tenant-scoped to the document's tenant |
| `pdf_metadata_no_pii` | WARN | exported PDF metadata has no user/tenant id (unless opted in) |
| `external_link_safe` | WARN | embedded URLs are http(s), not `file://`/`javascript:` |

### Accessibility (cross-ref §25)

| rule_id | Level | Check |
|---|---|---|
| `wcag_text_contrast` | WARN | text contrast ratio ≥ 4.5:1 (normal) / 3:1 (large) |
| `alt_text_present` | WARN | every illustration layer has alt-text (auto-gen + user-editable) |
| `heading_hierarchy` | WARN | text styles map to a sensible heading hierarchy |
| `colorblind_safe_palette` | WARN | brand kit palette passes Daltonism simulation (deutan/protan/tritan) |

## API surface

| Action | Args | Returns |
|---|---|---|
| `preflight_run` | `document_id, [rule_ids]` | PreflightReport |
| `preflight_fix` | `report_id, check_id` | new state after applying FixSuggestion |
| `preflight_silence` | `document_id, rule_id, [scope_id]` | adds a documented exception |

A `preflight_run` is automatically called by `export` (§13); a FAIL aborts
export with the report attached to the error.

## Edge cases

1. **Rule depends on missing data** (e.g. `colors_in_gamut` on a page with no
   ICC profile set) — skip with `OK` and a `not_applicable` flag, not WARN.
2. **Massive report** (1000+ pages × 15 rules) — paginate; cap at 200
   findings per scope; group identical findings under a representative.
3. **User silenced rule comes back** — silenced exceptions are scoped (per
   layer or per page); resurface if the underlying scope changes.
4. **Fix suggestion not always available** — required for FAIL only when
   trivially repairable; otherwise message must say what manual step is
   needed.
5. **Race on autofix** — preflight result includes a snapshot version;
   `preflight_fix` requires expected_version match; fail loudly if stale.
6. **Spell-check across mixed locales** — per text layer locale; book-level
   default; locale unset → use doc default → use document language guess.
7. **Vision-LLM drift score is non-deterministic** — cache score per
   `(layer_source_hash, lock_version)`; recompute on either change.
8. **Reading-level rule on non-prose pages** (cover, title) — skip.

## Errors

- `PreflightFailedError(ConfigError, code="PREFLIGHT_FAILED")` — wraps the
  report; raised by `export` if FAIL count > 0.
- `RuleNotFoundError(ConfigError, code="PREFLIGHT_RULE_UNKNOWN")`

## Test surface

- Unit: each rule independently against fixture documents (golden reports);
  PreflightReport defaults; CheckResult immutability.
- Integration: `export` blocks on FAIL; `preflight_fix` resolves a known
  FAIL fixture; silenced exceptions persist across runs.
- Property: `preflight_run` is monotone in scope (running on subset = subset
  of full report).
- Security: tenant-isolation rule cannot be silenced.

## Dependencies

- `pyspellchecker` (P0 dep)
- `colormath` or builtin matrix for CMYK gamut + Daltonism simulations
- Vision-LLM endpoint (existing) for drift score
- Face-embedding model (e.g. ArcFace) via Replicate for character consistency
