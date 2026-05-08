# Main Character Press — End-to-End Pipeline Spec

**Last Updated:** 2026-04-29
**Status:** Active development

---

## Overview

Main Character Press produces personalized children's books where the customer's child is the illustrated main character. The pipeline accepts a customer order (photo + preferences) and produces a print-ready PDF submitted to Lulu's POD API.

Three products:

| Product | Pages | Binding | Size | Print Cost | Retail |
|---------|-------|---------|------|-----------|--------|
| Picture Book | 32 | Perfect Bind | 7.5×7.5 or 9×7 | $8.68 | $24.99 |
| Coloring Book Standard | 32 | Perfect Bind | 8.5×11 | $3.25 | $9.99 |
| Coloring Book Premium | 150 | Coil | 8.5×11 | $12.23 | $25+ |

---

## Pipeline Stages

### Stage 1: Order Intake

**Input:** Customer submission
**Output:** `OrderSpec` (typed dict)

Customer provides:
- Child photo (front-facing, good lighting)
- Child first name
- Child age (determines reading level and art complexity)
- Book type (picture / coloring-standard / coloring-premium)
- Book size (7.5×7.5 / 9×7 / 8.5×11)
- Art style: `bold_simple` (ages 3-6) or `detailed_ornate` (ages 7+)
- 3 interest themes from menu (for coloring books: 25 pages each)
- Optional free-text interest alternates
- Shipping address

Validation:
- Photo: min 512×512px, max 10MB, JPEG/PNG
- Age: 2-12
- Name: 1-30 chars, no special characters
- Interests: exactly 3 from menu OR 2 from menu + 1 free-text

### Stage 2: Character Sheet Generation

**Input:** Child photo, art style, age
**Output:** `CharacterSheet` (13 pose images + metadata)

This is the Canvas Engine's core differentiator. Single generation call produces all 13 poses.

1. **Analyze photo** — Extract visual features: hair color/style, skin tone, eye color, build, distinguishing features. Use vision LLM (Gemini 2.5 Flash via conductor-router).
2. **Generate Pillow reference image** — Create structural-only reference:
   - Grid layout (4×3 + 1 large hero pose)
   - Skeleton outlines at ~25% opacity (pose, facing, scale, proportions)
   - Featureless grey mannequins at ~15% opacity
   - Grid cell borders + pose labels
   - NO character-specific features (no hair, skin, eyes, clothing, style)
3. **Single AI generation call** — Reference image + ultra-precise prompt containing:
   - All character features from step 1 (hair, skin, eyes, build)
   - Art style directive (bold_simple or detailed_ornate)
   - Instruction to match each grid cell's pose/proportion exactly
   - Instruction: character features from prompt only, structural layout from reference
4. **Extract individual poses** — Crop the 13 poses from the generated grid image
5. **Quality check** — Verify all 13 cells populated, character consistent across poses, no artifacts

13 poses:
- front_standing, front_waving, front_running, front_sitting
- side_walking_left, side_walking_right, side_running
- back_standing, back_waving
- three_quarter_left, three_quarter_right
- looking_up, looking_down

### Stage 3: Story Generation (Picture Book only)

**Input:** Child name, age, interests, character sheet
**Output:** `StorySpec` (28 pages of text + illustration prompts)

1. **Generate story** — LLM (via conductor-router) produces 28 story pages
   - Page 1: Title page (book title + child's name)
   - Page 2: Copyright/dedication page
   - Pages 3-28: Story (26 story pages, ~50-100 words each for ages 3-6, ~100-150 for 7+)
   - Every page includes illustration prompt referencing character poses
2. **Validate story** — Check word count per page, age-appropriateness, no copyright issues
3. **Map poses** — Assign character poses to each page from the 13-pose sheet

Coloring books skip this stage — pages are just line art scenes with the character.

### Stage 4: Illustration Generation

**Input:** Character sheet + story/scene specs
**Output:** 28-150 illustration images

**Picture Book (28 illustrations):**
For each story page:
1. Build illustration prompt: scene description + character pose + art style + mood + lighting
2. Use character sheet reference (relevant pose crop) as image reference
3. Generate full-bleed illustration at 300 DPI (2250×2250 px for 7.5×7.5)
4. QA: verify character present, no extra limbs, consistent appearance

**Coloring Book (32 or 150 illustrations):**
For each coloring page:
1. Select scene template based on interest theme
2. Build prompt: scene + character pose + "black and white line art, clean outlines, suitable for coloring, no shading, no fill"
3. Generate line art at 300 DPI (2550×3300 px for 8.5×11)
4. Post-process: threshold to pure B&W, remove gray artifacts, ensure clean lines
5. QA: verify clean outlines, no filled areas, character recognizable

### Stage 5: PDF Composition

**Input:** Illustrations + story text + product spec
**Output:** Interior PDF + Cover PDF (both passing Lulu validation)

**Interior PDF specs (ALL formats):**
- Single-page layout (not spreads)
- PDF/X-1a or PDF 1.4 minimum
- All fonts embedded
- Images at 300 DPI minimum
- RGB color space (sRGB IEC61966-2.1)
- No trim marks, bleed marks, or margin lines
- No password protection
- Transparent layers flattened

**Picture Book interior (7.5×7.5, 32 pages):**
- Page size: 7.75" × 7.75" (trim + 0.125" bleed all sides) = 558 × 558 pt
- Full bleed on every page
- Safety margin: 0.5" (36pt) from trim edge for text
- Gutter: 0.125" (9pt) on spine side for 32 pages

**Coloring Book interior (8.5×11, 32 or 150 pages):**
- Page size: 8.75" × 11.25" (trim + 0.125" bleed) = 630 × 810 pt
- Full bleed, line art extends to bleed edge
- Single-sided printing consideration (even page count)

**Cover PDF specs:**
- Single-page spread: back cover + spine + front cover
- Bleed: 0.125" on all sides
- Safety margin: 0.5" from trim edge for text/ISBN

**Picture Book cover (7.5×7.5, 32 pages):**
- Spine width: (32 / 444) + 0.06 = 0.132" (9.5pt)
- Total width: 0.125 + 7.5 + 0.132 + 7.5 + 0.125 = 15.382" = 1107.5pt
- Total height: 0.125 + 7.5 + 0.125 = 7.75" = 558pt

**Coloring Book cover (8.5×11):**
- Spine width (32pg): 0.132"; spine width (150pg): (150/444) + 0.06 = 0.398"
- Total width (32pg): 0.125 + 8.5 + 0.132 + 8.5 + 0.125 = 17.382" = 1251.5pt
- Total width (150pg): 0.125 + 8.5 + 0.398 + 8.5 + 0.125 = 17.648" = 1270.7pt
- Total height: 0.125 + 11.0 + 0.125 = 11.25" = 810pt

### Stage 6: Quality Assurance

**Input:** Interior PDF + Cover PDF + OrderSpec
**Output:** Pass/Fail + report

Automated checks:
1. **Page count** — matches product spec (32 or 150)
2. **PDF dimensions** — interior trim size matches SKU, cover dimensions match spine calc
3. **Image resolution** — all images ≥ 300 DPI
4. **Color space** — RGB (sRGB), not CMYK
5. **Fonts embedded** — no missing font references
6. **Bleed** — content extends to bleed edge where required
7. **Safety margins** — text within 0.5" of trim edge
8. **Character consistency** — sample 5 random pages, verify character features match across all 5
9. **File size** — interior ≤ 100MB, cover ≤ 20MB

### Stage 7: Pricing & Cost Calculation

**Input:** Product spec + shipping address
**Output:** Cost breakdown

1. Calculate print cost from spec sheet formula: `base + (pages × per_page)`
2. Call Lulu `/print-job-cost-calculations/` for live pricing (includes shipping + tax + fulfillment)
3. Compare formula vs live (should match within $0.50)
4. Return full cost breakdown to customer for approval

### Stage 8: Print Job Submission

**Input:** Validated PDFs + cost approval + shipping address
**Output:** Lulu order ID + tracking info

1. Upload interior PDF to Lulu
2. Upload cover PDF to Lulu
3. Create print job via `/print-jobs/` with:
   - `pod_package_id` (dotted format)
   - `interior_file` URL
   - `cover_file` URL
   - Shipping address
   - Shipping level (GROUND_HD default)
   - Quantity (1 for custom, multi for craft fair)
4. Receive order confirmation + estimated delivery
5. Send confirmation email to customer

### Stage 9: Fulfillment Tracking

**Input:** Lulu order ID
**Output:** Status updates → customer notification

Poll Lulu `/print-jobs/{id}/` for status transitions:
- `CREATED` → `IN_PRODUCTION` → `SHIPPING` → `DELIVERED`
- On `SHIPPING`: capture tracking number, notify customer
- On error: alert ops, offer reprint or refund

---

## Error Handling

| Stage | Failure | Recovery |
|-------|---------|----------|
| Character Sheet | AI generates inconsistent poses | Retry with adjusted prompt (max 3 attempts) |
| Character Sheet | All retries fail | Fall back to simpler 4-pose sheet, notify customer of delay |
| Story Gen | LLM produces inappropriate content | Content filter catches, regenerate with constraints |
| Illustration | Character missing/extra limbs | Retry with stricter prompt (max 2 per page) |
| Illustration | Character inconsistent with sheet | Re-reference character sheet crop, retry |
| PDF Composition | Font/image embedding fails | Fall back to Pillow rasterization |
| Lulu Validation | PDF rejected | Parse error, fix issue, re-compose, re-submit |
| Lulu Submission | API timeout | Retry with exponential backoff (max 3) |
| Lulu Production | Print quality complaint | Offer free reprint or full refund |

---

## Demo Test Plan (Lulu Sandbox)

The e2e demo test exercises stages 5-8 with placeholder content:

1. Generate valid interior PDF (32 pages, proper dimensions, embedded images)
2. Generate valid cover PDF (correct spine width, bleed, barcode area)
3. Submit cost calculation to Lulu sandbox
4. Upload both PDFs
5. Create print job on Lulu sandbox
6. Verify job status is `CREATED`
7. Cancel test job

This validates that our PDFs pass Lulu's file validation and our API integration works end-to-end.

Products to test:
- Picture Book (7.5×7.5, 32pg, FC Premium, PB)
- Coloring Book Standard (8.5×11, 32pg, BW, PB)
- Coloring Book Premium (8.5×11, 150pg, BW, Coil)

---

## File Layout

```
server/
├── lulu/                          # Lulu API client (existing)
│   ├── client.py
│   ├── constants.py
│   ├── service.py
│   └── tests/
├── mcp/                           # Main Character Press pipeline
│   ├── __init__.py
│   ├── products.py                # Product catalog (SKUs, pricing, specs)
│   ├── pdf_composer.py            # Interior + cover PDF generation
│   ├── pipeline.py                # Full pipeline orchestrator
│   └── tests/
│       ├── test_products.py
│       ├── test_pdf_composer.py
│       └── test_e2e_lulu.py       # Sandbox e2e test
└── ...
```
