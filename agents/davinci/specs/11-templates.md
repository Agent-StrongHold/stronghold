# 11 — Templates & Brand Kits

**Status**: P0 / Document phase. Bundled set + tenant-authored.
**One-liner**: a Template is a Document with placeholders + locked layers; a
BrandKit is a tenant-/user-scoped set of palette, fonts, and logos applied
across documents.

## Problem it solves

The wizard (§32) needs concrete starting points; users want to capture their
own pages as reusable templates (§17 covers authoring, this covers the
structure + bundled set + apply mechanics).

## Data model

```
Template (frozen):
  id: str
  tenant_id: str | None            # null for built-in templates
  owner_id: str | None             # null for built-in
  name: str
  category: TemplateCategory
  doc_kind: DocumentKind
  thumbnail_blob_id: str | None
  document_skeleton: TemplateDocument   # the parameterized Document
  variables: tuple[TemplateVariable, ...]
  trust_tier: TrustTier            # T0=builtin, T2=admin, T3=user, T4=community
  provenance: Provenance
  created_at, updated_at
  uses_count: int = 0              # for popularity

TemplateDocument (frozen):
  pages: tuple[TemplatePage, ...]
  brand_kit_default: TemplateBrandKitRef | None
  style_lock_seed: TemplateStyleLockSeed | None

TemplatePage (frozen):
  ordering: int
  layout_kind: LayoutKind
  print_spec: PrintSpec
  layers: tuple[TemplateLayer, ...]

TemplateLayer (frozen):
  layer_type: LayerType
  source: TemplateLayerSource      # tagged: literal | placeholder | parametric
  effects, mask, blend_mode, opacity, x, y, scale, rotation, z_index
  slot_id: str | None
  locked: bool = False             # if true, instantiated layer is locked

TemplateLayerSource (tagged union):
  Literal:     {kind: "literal", source: LayerSource}
  Placeholder: {kind: "placeholder", placeholder_id: str, content_type: PlaceholderType}
  Parametric:  {kind: "parametric", prompt_template: str, generation_kind: "image"|"text"}

PlaceholderType (StrEnum):
  TEXT_TITLE | TEXT_SUBTITLE | TEXT_BYLINE | TEXT_BODY | TEXT_CTA
  IMAGE_HERO | IMAGE_BG | IMAGE_PORTRAIT | IMAGE_PROP
  COLOR_PRIMARY | COLOR_ACCENT
  SHAPE_DECORATION

TemplateVariable (frozen):
  id: str                          # "title", "hero_prompt", "subtitle"
  display_name: str
  required: bool
  default_value: Any | None
  type: TemplateVarType            # STR | INT | COLOR | IMAGE | ENUM
  enum_options: tuple[str, ...] = ()
```

```
BrandKit (frozen):
  id: str
  tenant_id: str
  owner_id: str
  name: str
  palette: tuple[Color, ...]        # 3-7
  fonts: BrandKitFonts              # display, body, mono, decorative
  logos: tuple[BrandLogo, ...]      # primary + secondary + monochrome
  voice_prompt: str = ""            # injection for tone consistency
  spacing_unit: int = 8             # design system base unit
  created_at, updated_at

BrandKitFonts (frozen):
  display: FontRef
  body: FontRef
  mono: FontRef | None
  decorative: FontRef | None

BrandLogo (frozen):
  blob_id: str
  variant: LogoVariant              # PRIMARY | SECONDARY | MONOCHROME | ICON
  color_mode: ColorMode             # SRGB | CMYK | GRAYSCALE
```

## Template categories (bundled set, P0)

| Category | Count | Examples |
|---|---|---|
| `picture_book` | 8 | classic 32pp, board book 16pp, square 8x8, landscape, half-page-illustration, wordless |
| `poster` | 6 | event A2, movie 24x36, propaganda, minimal, photo-hero, typographic |
| `infographic` | 6 | A2 vertical flow, A3 grid, social square, comparison side-by-side, timeline, statistics-list |
| `early_reader` | 3 | chapter book, illustrated novel, transitional reader |
| `cover_only` | 4 | minimal type, photo, illustrated, abstract |
| `social_media` | 6 (P1) | IG square, IG story, FB cover, LinkedIn header, TikTok cover, X post |

Total ~30 bundled templates at launch. Each ships with a thumbnail and
sample variables.

## Template apply flow

```
def template_apply(template, variables, target_doc=None):
    # 1. Validate variables: required present, types match
    # 2. If target_doc is None: create new Document of template's doc_kind
    #    Else: clear target_doc's pages (with versioning §23)
    # 3. For each TemplatePage: create Page with print_spec
    # 4. For each TemplateLayer:
    #    - Literal: copy source bytes/data
    #    - Placeholder: create empty layer with slot_id, marked for fill
    #    - Parametric: render prompt_template with variables, then generate
    #      (draft tier; user approves proof per §31 cost gate)
    # 5. If brand_kit chosen: apply via brand_kit_apply
    # 6. If style_lock_seed: instantiate StyleLock from seed
    # 7. Bump template.uses_count
    return new_doc
```

## BrandKit apply flow

Re-skin an existing Document:

```
def brand_kit_apply(doc, kit):
    # For each Page:
    #   For each text layer:
    #     map font_family → kit.fonts.body / display / mono per slot's role
    #     map color → nearest in kit.palette where color was a brand swatch
    #   For each shape layer:
    #     map fill, stroke colors that were brand swatches
    #   For each generative layer:
    #     append "in {kit.voice_prompt} aesthetic" to next regen prompt
    # Logo layers: replace blob with kit.logos[matching variant]
```

Idempotent: re-apply with same kit is no-op; apply with different kit
re-maps only previously-brand-mapped fields.

## Auto-extract brand kit

From a logo upload OR a website URL:

```
extract_from_logo(blob_id) → BrandKit:
  palette = extract_palette(blob, k=5)
  fonts = bundled defaults
  logos = (variant=PRIMARY)
  voice = ""

extract_from_url(url) → BrandKit:
  fetch HTML + screenshot
  extract palette from screenshot
  parse @font-face from CSS where licensable
  pull logo from <link rel=icon> or <meta og:image>
```

The fetch_url branch needs Warden scan on fetched content.

## API surface

| Action | Args | Returns |
|---|---|---|
| `template_list` | `[category, doc_kind, tenant_only]` | tuple of Template summaries |
| `template_get` | `template_id` | Template |
| `template_apply` | `template_id, variables, [target_doc_id]` | Document |
| `brand_kit_create` | `name, palette, fonts, logos, voice_prompt` | BrandKit |
| `brand_kit_extract_from_logo` | `blob_id` | BrandKit |
| `brand_kit_extract_from_url` | `url` | BrandKit (after Warden) |
| `brand_kit_apply` | `document_id, kit_id` | document |
| `brand_kit_save` | `kit_id, name` | persisted |

## Edge cases

1. **Apply template to non-empty document** — must specify
   `replace_pages=True`; versioning checkpoint created automatically.
2. **Required variable missing** — `TemplateApplyError`; no Document
   created/changed.
3. **Variable type mismatch** — coerce where safe, error otherwise.
4. **Parametric layer generation fails** — placeholder kept; pre-flight
   surfaces.
5. **Built-in template referenced from a tenant document** — fine; built-in
   templates are read-only and version-pinned in the document for
   reproducibility.
6. **Template trust tier mismatch** — user attempting to apply a T4
   community template with no review is gated by Stronghold's trust system
   (existing `Provenance` + `TrustTier`).
7. **BrandKit fonts not licensable** — extract_from_url only includes fonts
   with declared licensable status; otherwise references are dropped with
   warning.
8. **Logo extraction from URL of a competing service** — Warden /
   Sentinel may reject content (e.g. CSAM upload bypass attempt).
9. **Palette extraction from grey logo** — return single greyscale + warn.
10. **BrandKit palette and StyleLock palette conflict** — kit wins for UI/
    text/shape colours; lock wins for generated illustration colours;
    surfaced explicitly.

## Errors

- `TemplateNotFoundError`
- `TemplateApplyError(ConfigError)` — variable missing/invalid
- `TemplateTrustViolationError(SecurityError)` — trust tier mismatch
- `BrandKitExtractionError(ToolError)` — extract failed

## Test surface

- Unit: every TemplateVariable type round-trips; required-var enforcement;
  brand-kit immutability.
- Integration: apply each bundled template to fresh Document → expected
  page/layer count; brand_kit_apply remaps colours predictably; extract
  from URL with stubbed HTML produces expected kit.
- Security: cross-tenant template access denied; community template gating;
  Warden scan on URL fetches; bandit clean.
- Performance: template_apply < 2 s for any P0 bundled template.

## Dependencies

- §02 document, §08 print spec, §10 layouts, §17 template authoring,
  §22 preflight, §31 budget
- `extcolors` for palette extraction
- `httpx` (existing) for URL fetch
