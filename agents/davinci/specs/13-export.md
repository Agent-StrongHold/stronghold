# 13 — Export

**Status**: P0 / Output phase. The deliverable.
**One-liner**: Document → bytes in PNG, JPG, WebP, PDF, SVG, ePub, PPTX
formats; pre-flight gate; embedded metadata; print specifications honoured.

## Problem it solves

Internal canvas state must become a file the user can print, share, or
publish. PDF must be print-ready. SVG must be valid. ePub must pass an ePub
validator. Every export must run pre-flight first.

## Formats

| Format | P-level | Backend | Notes |
|---|---|---|---|
| PNG (single page) | P0 | Pillow | with alpha; per-page DPI |
| PNG (multi-page → ZIP) | P0 | Pillow + zipfile | for books |
| JPG | P0 | Pillow | quality param 0-100 |
| WebP | P0 | Pillow | smaller files; lossy/lossless |
| PDF (raster) | P0 | Pillow `save(format=PDF)` | quick path |
| PDF (vector + raster) | P0 | reportlab | shape/text vectors preserved |
| PDF/A (archival) | P1 | reportlab + flagging | for libraries |
| PDF/UA (accessible) | P1 | reportlab + tagged structure | per §25 |
| SVG (single page, vector-friendly) | P0 | svgwrite + Pillow embed | only when page is mostly vector |
| ePub | P1 | Sigil-style XHTML build | reflowable books |
| PPTX | P1 | python-pptx | one page → one slide |
| MP4 | reach (§15) | ffmpeg | video docs |

## Pipeline

```
def export(document_id, format, options) -> bytes:
    doc = load(document_id)
    report = preflight_run(doc.id)
    if report.summary.failures > 0 and not options.ignore_preflight:
        raise PreflightFailedError(report)
    pages = sorted(doc.pages, key=ordering)
    rendered = [render_page(p, target=format, options) for p in pages]
    blob = pack(rendered, format, options)
    audit_entry("export", doc.id, format, options.dpi, ...)
    return blob
```

## PDF specifics

| Concern | Default |
|---|---|
| Page size | per Page.print_spec.trim |
| Bleed canvas | painted; PDF crop box = trim, media box = bleed |
| Color mode | per Page.print_spec.color_mode (sRGB or CMYK) |
| ICC profile | embedded if CMYK or non-sRGB |
| Fonts | embedded as subsets (always); FontValidationError if not embeddable |
| Vector layers | rendered as PDF vector ops, not flattened |
| Raster layers | embedded as JPEG (quality 90) for non-alpha, PNG for alpha |
| Transparency | flattened or preserved per print pipeline |
| Hyperlinks | (P1) preserved if document has them |
| Metadata | author/title from doc; PII stripped unless opted in |
| Tagged structure | (P1) /StructTreeRoot for accessibility |

## SVG specifics

SVG export only emits a clean output when the page is "vector-friendly":
- All raster layers are referenced (not embedded as data URIs unless
  `inline_raster=True`)
- All text is vectorized (text_to_shape) OR fonts are linked (with caveat)
- Vector shapes pass through with their geometry

If a page has mostly raster content, SVG export emits raster wrapped in an
`<image>` element with a warning.

## ePub specifics

For early-reader / illustrated novel books:
- One Document → one ePub3 file
- Each Page → one XHTML chapter file with embedded image references
- Body text extracted with markup (h1, p, etc.)
- Reading order from page ordering
- Manifest, spine, navigation built per ePub3 spec
- Validates against `epubcheck` in test
- DRM: not added (open file)

## Metadata

```
ExportOptions (frozen):
  format: ExportFormat
  page_range: tuple[int, int] | None  # None = all
  dpi: int | None                      # override per Page.print_spec.dpi
  quality: int = 90                    # JPG / WebP quality
  embed_fonts: bool = True             # PDF
  ignore_preflight: bool = False
  embed_metadata_pii: bool = False     # author/email/etc.
  color_profile: str | None = None     # override
  inline_raster: bool = False          # SVG-only
  pdf_subtype: PDFSubtype = STANDARD   # STANDARD | PDFA | PDFUA
```

## Audit

Every export logs:
- export id, doc id, format, page range, dpi, color mode
- byte size, sha256
- preflight outcome (cached if same doc version)
- user, tenant, timestamp

## API surface

| Action | Args | Returns |
|---|---|---|
| `export` | `document_id, format, [options]` | bytes |
| `export_async` | `document_id, format, [options]` | job_id (for large) |
| `export_status` | `job_id` | progress, result_blob_id when done |
| `export_history` | `document_id` | list of past exports |

`export_async` returns immediately with a job id; polling or webhook on done.

## Edge cases

1. **Page size larger than format max** (PDF supports up to ~5m square; PNG
   limited by Pillow) — reject with `ExportSizeError`.
2. **Empty document** — `EmptyDocumentError` from §02.
3. **Pre-flight FAIL with `ignore_preflight=False`** — `PreflightFailedError`
   with report attached.
4. **Pre-flight WARN** — proceeds with warnings logged.
5. **Vector text export to PDF with non-embeddable font** —
   `FontNotEmbeddableError`; user must change font or accept rasterization.
6. **CMYK with sRGB-only ICC** — `ConfigError`; profile mismatch.
7. **PDF/UA without alt-text** — fail (alt-text required for /Alt
   attributes); cross-ref §25.
8. **Multi-page PNG export without ZIP requested** — first page only with
   warning OR auto-ZIP; default to ZIP.
9. **Memory pressure on huge book exports** — stream pages instead of
   in-memory composite; chunked PDF assembly.
10. **Concurrent export of same doc** — both succeed; deduped by job
    cache when input identical.
11. **Watermarked draft export** — when not all layers are proof-tier and
    `enforce_proof=True`, watermark "DRAFT" in safe area.

## Errors

- `ExportFormatUnsupportedError(ConfigError)`
- `ExportSizeError(ConfigError)` — size beyond format limits
- `PreflightFailedError(ConfigError, code="PREFLIGHT_FAILED")` (re-raised)
- `ExportBackendError(ToolError)` — reportlab / vl-convert failures

## Test surface

- Unit: ExportOptions defaults; format inference; metadata redaction.
- Integration: export each format on fixture doc → byte-size sanity check;
  PDF embeds expected fonts; SVG validates against XSD; ePub passes
  epubcheck; PNG dims match.
- Property: round-trip PNG export → import as raster layer → re-export →
  byte-equivalent (within JPEG/WebP tolerance).
- Security: metadata PII not in output unless opt-in; bandit clean.
- Performance (`@perf`): 32-page picture book PDF export < 30s.

## Dependencies

- Pillow (existing)
- `reportlab` (P0 dep) for vector PDF
- `svgwrite` (P0 dep) for SVG
- `python-pptx` (P1)
- `epubcheck` (test-only) for validation
