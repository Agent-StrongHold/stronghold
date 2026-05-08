# Main Character Press — Complete Specification & Review Plans

**Project:** Personalized children's book production platform
**Location:** `canvas-studio-poc/server/mcp/` + `src/stronghold/tools/canvas_book.py`
**Last Updated:** 2026-04-30
**Status:** Active development — Phase 2 complete (porting + wiring)

---

## Table of Contents

1. [Full Specification](#1-full-specification)
2. [Gherkin Acceptance Scenarios](#2-gherkin-acceptance-scenarios)
3. [Test Coverage Matrix](#3-test-coverage-matrix)
4. [API Contracts](#4-api-contracts)
5. [Implementation Plan](#5-implementation-plan)
6. [Audit Plan](#6-audit-plan)
7. [PR Review Plan](#7-pr-review-plan)
8. [CI Review Plan](#8-ci-review-plan)
9. [Preflight Review Plan](#9-preflight-review-plan)

---

## 1. Full Specification

### 1.1 Products

| Product | Format | Pages | Print Cost | Retail | Margin | Lulu SKU |
|---------|--------|-------|-----------|--------|--------|----------|
| Picture Book | 7.5x7.5, FC Premium, 80# Coated, PB | 32 | $8.68 | $24.99 | 49% | `0750X0750.FC.PRE.PB.080CW444.MXX` |
| Picture Book (Landscape) | 9x7, FC Premium, 80# Coated, PB | 32 | $8.68 | $24.99 | 49% | `0900X0700.FC.PRE.PB.080CW444.MXX` |
| Coloring Standard | 8.5x11, BW Standard, 60# Uncoated, PB | 32 | $3.25 | $9.99 | 67% | `0850X1100.BW.STD.PB.060UW444.MXX` |
| Coloring Premium | 8.5x11, BW Standard, 60# Uncoated, Coil | 150 | $12.23 | $25.99 | 51% | `0850X1100.BW.STD.CO.060UW444.MXX` |

### 1.2 Module Inventory

| Module | File | Ported From | Purpose |
|--------|------|-------------|---------|
| `products` | `server/mcp/products.py` | Original | Product catalog, SKU specs, pricing, margins |
| `pdf_composer` | `server/mcp/pdf_composer.py` | Original | Interior + cover PDF generation (reportlab) |
| `character` | `server/mcp/character.py` | bookApi.js + renderingPipeline.js | Photo analysis (vision LLM), reference image (Pillow), character sheet (single AI call), pose extraction |
| `canvas_templates` | `server/mcp/canvas_templates.py` | templateEngine.js | 14 poses, 7 composition zones, 7 style tokens, 6 mood tokens, 6 lighting tokens, prompt builders |
| `story` | `server/mcp/story.py` | storyApi.js | Story generation, validation, structured storyboard decomposition |
| `illustration` | `server/mcp/illustration.py` | renderingPipeline.js | Page illustration generation (FC + BW), prompt builders, post-processing |
| `image_provider` | `server/mcp/image_provider.py` | renderingPipeline.js | Multi-provider image gen: CF (primary), Azure (fallback), Gemini (fallback) |
| `pipeline` | `server/mcp/pipeline.py` | Original | Full orchestrator: char sheet -> story -> illustrations -> PDF -> archive |
| `bg_removal` | `server/mcp/bg_removal.py` | renderingPipeline.js:removeBackground | BFS flood-fill bg removal with alpha feathering |
| `feature_extractor` | `server/mcp/feature_extractor.py` | featureExtractor.js | Local pixel-based hair/skin/eye classification (no AI) |
| `character_normalizer` | `server/mcp/character_normalizer.py` | characterNormalizer.js | Silhouette detection, scale normalization, head region, face mask |
| `refinement` | `server/mcp/refinement.py` | refinementPass.js | Edge softening, palette unification, contrast normalization, face protection |
| `canvas_book` (Stronghold) | `src/stronghold/tools/canvas_book.py` | Original | Stronghold tool: 6 actions exposing pipeline to agents |

### 1.3 Pipeline Stages

```
OrderSpec (photo + name + age + book_type)
  │
  ├─ Stage 1: Character Sheet
  │   ├─ analyze_photo() → CharacterFeatures (vision LLM)
  │   ├─ extract_features() → local pixel features (Pillow, no AI)
  │   ├─ generate_reference_image() → Pillow grid (13 poses, deterministic)
  │   ├─ generate_character_sheet() → single AI call → 13-pose image
  │   └─ extract_poses() → pose crops dict
  │
  ├─ Stage 2: Story (picture books only)
  │   ├─ generate_story() → 32-page Story via LLM
  │   └─ validate_story() → word count, age-appropriateness, pose validity
  │
  ├─ Stage 3: Illustrations
  │   ├─ generate_picture_book_illustrations() → per-page FC images
  │   ├─ generate_coloring_book_illustrations() → per-page BW line art
  │   └─ _post_process_coloring() → threshold to pure B&W
  │
  ├─ Stage 4: PDF Composition
  │   ├─ compose_interior() → Lulu-spec PDF (bleed, spine, safety margins)
  │   ├─ compose_cover() → back + spine + front cover PDF
  │   └─ _archive_pages() → move temp PNGs to archive/
  │
  └─ Stage 5: (Future) Lulu Submission
      └─ submit to Lulu POD API
```

### 1.4 Key Design Decisions

1. **Character sheet = ONE generation call** — not 13 separate calls. Pillow reference image encodes structural info only; character features come from prompt only.
2. **Text overlay is compositing advantage** — story text rendered as separate PDF layer, not baked into illustrations. Allows name swaps.
3. **Golden samples for AI resilience** — one perfect generation per step as fallback so downstream stages testable even if AI fails.
4. **Three consumers, one engine** — Stronghold (in-process), conductor-router (vendored), Canvas Studio (HTTP).
5. **Temp pages archived, never deleted** — `_page_*.png` moved to `archive/pages/` after PDF composition.
6. **Image provider fallback chain** — Cloudflare (free, primary) → Azure (fallback) → Gemini (fallback). All return PIL Image.

### 1.5 Invariants

| ID | Invariant | Kind | Severity |
|----|-----------|------|----------|
| INV-01 | `generate_image()` always returns PIL Image or raises RuntimeError — never returns None | postcondition | critical |
| INV-02 | Character sheet reference image contains NO character-specific features (hair, skin, eyes, clothing) | precondition | critical |
| INV-03 | Text overlay only on picture books — coloring books get no text overlay | state | high |
| INV-04 | PDF dimensions match Lulu spec exactly (trim + bleed + spine) | postcondition | critical |
| INV-05 | Temp page images archived to `archive/pages/`, never deleted | postcondition | high |
| INV-06 | `remove_background()` always returns RGBA image | postcondition | high |
| INV-07 | `normalize_character()` always returns (image, silhouette, head, norm) tuple | postcondition | medium |
| INV-08 | Story validation catches invalid poses and replaces with `front_standing` | postcondition | high |
| INV-09 | Coloring pages post-processed to pure B&W (no gray, no fill) | postcondition | high |
| INV-10 | `canvas_book` tool never surfaces raw provider error messages to callers | postcondition | high |

---

## 2. Gherkin Acceptance Scenarios

### Feature: Character Sheet Generation

```gherkin
Feature: Character sheet from photo
  Background:
    Given a child photo at least 512x512 pixels
    And the child's name is "Luna"
    And the child's age is 5

  Scenario: Successful character sheet with all 13 poses
    When create_character_sheet_from_photo is called
    Then CharacterSheet.features.hair is not empty
    And CharacterSheet.features.skin_tone is not empty
    And CharacterSheet.features.eye_color is not empty
    And CharacterSheet.quality_score > 0

  Scenario: Reference image is structural-only
    When generate_reference_image is called
    Then the output image dimensions match GRID_COLS * cell_width by GRID_ROWS * cell_height
    And no pixel in the image represents specific hair color
    And no pixel in the image represents specific skin tone
    And skeleton outlines are visible at ~25% opacity
    And mannequin silhouettes are visible at ~15% opacity
    And grid cell borders and labels are present

  Scenario: Vision LLM fails, falls back to defaults
    Given the vision LLM endpoint returns 500
    When create_character_sheet_from_photo is called with fallback_to_golden=True
    Then CharacterSheet.features uses golden fallback values
    And the pipeline continues without crashing

  Scenario: Pose extraction from blank sheet
    Given a reference image with all white cells
    When extract_poses is called
    Then 13 pose crops are returned
    And each crop is a valid PIL Image
```

### Feature: Story Generation

```gherkin
Feature: 32-page story generation
  Background:
    Given child name "Luna" age 5
    And CharacterFeatures with hair="brown wavy" skin_tone="warm medium" eye_color="brown"

  Scenario: Valid story for early reader
    When generate_story is called
    Then Story.page_count == 32
    And Story.pages[0].scene_type == "title"
    And Story.pages[1].scene_type == "copyright"
    And Story.child_name appears in at least one page text

  Scenario: Story validation catches invalid pose
    Given a story with page 5 character_pose="invalid_pose"
    When validate_story is called
    Then the issues list contains "invalid pose"
    And the invalid pose is replaced with "front_standing"

  Scenario: Word count enforcement per age
    Given child age 3 (toddler)
    When generate_story is called
    Then each story page has 20-60 words

  Scenario: Storyboard decomposition
    When decompose_book is called with page_count=12 orientation="landscape"
    Then BookDecomposition.scenes has 12 entries
    And BookDecomposition.style_contract.art_style is not empty
    And first scene scene_type == "title_page"
    And last scene scene_type == "ending"
```

### Feature: Background Removal

```gherkin
Feature: Remove background from generated images
  Scenario: White background with centered foreground
    Given a 200x200 image with white background and colored rectangle at center
    When remove_background is called with threshold=240 feather=4
    Then corner pixels have alpha=0
    And center pixels have alpha=255
    And edge pixels have 0 < alpha < 255 (feathered)

  Scenario: All-foreground image
    Given a 100x100 image entirely filled with dark colors
    When remove_background is called
    Then no pixels become transparent

  Scenario: High saturation background preserved
    Given an image with bright red background (255, 100, 100)
    When remove_background is called with threshold=240
    Then the red background is NOT removed (high saturation delta)
```

### Feature: Character Normalization

```gherkin
Feature: Normalize character position and scale
  Scenario: Character on white background
    Given a 200x200 image with white background and colored rectangle at (60,30)-(140,180)
    When detect_silhouette is called
    Then Silhouette.bounds.x == 0.3 (approximately)
    And Silhouette.bounds.y == 0.15 (approximately)

  Scenario: Normalize with pose bounds
    Given a character image with silhouette at (0.2, 0.1, 0.6, 0.8)
    And pose bounds at (0.2, 0.1, 0.6, 0.8)
    When normalize_character is called
    Then the output image is target_width x target_height
    And Normalization.needs_correction == False

  Scenario: Face mask generation
    Given a HeadRegion with center at (0.5, 0.175) and radius 0.1
    When build_face_mask is called with canvas_size=256
    Then center of mask region has pixel value 255
    And corners of mask have pixel value 0
```

### Feature: Refinement Pass

```gherkin
Feature: Post-compositing refinement
  Scenario: Pillow fallback refinement
    Given a composite RGBA image
    When refine_scene is called
    Then RefinementResult.refined == True
    And RefinementResult.refinement_method == "pillow_fallback"
    And RefinementResult.composite dimensions match input

  Scenario: Edge softening at character slot
    Given a composite with character slot at (0.3, 0.2, 0.4, 0.7)
    When refine_scene is called with character_slot
    Then pixels at character slot edges are softened
    And pixels outside slot are unchanged

  Scenario: Face protection preserves original
    Given a refined composite and original composite with different face areas
    And a face mask with white ellipse at head region
    When apply_face_protection is called
    Then face area pixels match the original composite
    And non-face pixels match the refined composite
```

### Feature: Full Pipeline

```gherkin
Feature: End-to-end pipeline execution
  Scenario: Picture book with skip_ai
    Given OrderSpec for picture book age 5
    When run_pipeline is called with skip_ai=True
    Then PipelineResult.stages_completed contains "character_sheet"
    And PipelineResult.stages_completed contains "story"
    And PipelineResult.stages_completed contains "illustrations"
    And PipelineResult.stages_completed contains "pdf"
    And interior.pdf exists with non-zero size
    And cover.pdf exists with non-zero size

  Scenario: Coloring book with skip_ai
    Given OrderSpec for coloring-standard age 6
    When run_pipeline is called with skip_ai=True
    Then story is None
    And 32 illustrations are generated
    And illustrations are black and white

  Scenario: Golden fallback on AI failure
    Given OrderSpec for picture book
    And the AI endpoint is unavailable
    When run_pipeline is called with fallback_to_golden=True
    Then golden features are used for character sheet
    And golden story is used
    And PipelineResult.errors contains "golden_fallback"

  Scenario: Page archiving
    Given any pipeline run that completes the PDF stage
    Then _page_*.png files are moved to archive/pages/
    And no _page_*.png files remain in output root
```

### Feature: Image Provider

```gherkin
Feature: Multi-provider image generation
  Scenario: Cloudflare primary succeeds
    Given CLOUDFLARE_API_KEY and CLOUDFLARE_ACCOUNT_ID are set
    When generate_image is called
    Then the image is returned from Cloudflare
    And no Azure or Gemini calls are made

  Scenario: Cloudflare fails, Azure succeeds
    Given Cloudflare returns 500
    And AZURE_OPENAI_API_KEY is set
    When generate_image is called
    Then Azure is tried as fallback
    And the image is returned from Azure

  Scenario: All providers fail
    Given all providers are unavailable
    When generate_image is called
    Then RuntimeError is raised with "All image providers failed"
```

### Feature: PDF Composition

```gherkin
Feature: Lulu-spec PDF generation
  Scenario: Picture book interior with text overlay
    Given product picture-book-7.5 and 32 page images and story text
    When compose_interior is called with page_texts
    Then PDF page size is 7.75" x 7.75" (with bleed)
    And pages 3+ have semi-transparent white bar at bottom with story text
    And pages 1-2 have no text overlay

  Scenario: Coloring book interior without text overlay
    Given product coloring-standard and 32 page images
    When compose_interior is called
    Then no text overlay is applied to any page

  Scenario: Cover with correct spine width
    Given product picture-book-7.5 with 32 pages
    When compose_cover is called
    Then cover width == 0.125 + 7.5 + spine_width + 7.5 + 0.125 inches
    And spine_width == (32 / 444) + 0.06 inches
```

### Feature: Stronghold Canvas Book Tool

```gherkin
Feature: canvas_book tool for agents
  Scenario: create_character action
    Given a base64-encoded photo
    When canvas_book tool is called with action="create_character" photo_b64=...
    Then ToolResult.success == True
    And content contains ai_features with hair/skin_tone/eye_color
    And content contains local_features from pixel analysis

  Scenario: remove_bg action
    Given a base64-encoded image
    When canvas_book tool is called with action="remove_bg" image_b64=...
    Then ToolResult.success == True
    And content contains image dimensions and size

  Scenario: Missing photo_b64 for create_book
    When canvas_book tool is called with action="create_book" without photo_b64
    Then ToolResult.success == False
    And error contains "photo_b64 is required"

  Scenario: Unknown action
    When canvas_book tool is called with action="invalid"
    Then ToolResult.success == False
    And error contains "Unknown action"
```

---

## 3. Test Coverage Matrix

### 3.1 Test Inventory (113 tests, 0 failures)

| Test File | Tests | Module Covered | Coverage Areas |
|-----------|-------|----------------|----------------|
| `test_pipeline.py` | 32 | character, story, illustration, pipeline, products, golden, pdf | Prompt building, pipeline stages, golden fallback, archiving, age groups, text overlay |
| `test_e2e.py` | 9 | products, pdf_composer, lulu client | PDF composition, Lulu sandbox, product dimensions |
| `test_bg_removal.py` | 10 | bg_removal | Luminance, bg detection, removal, feathering, edge cases |
| `test_feature_extractor.py` | 18 | feature_extractor | HSL conversion, hair/skin/eye classification, region sampling, full extraction, design builder |
| `test_character_normalizer.py` | 12 | character_normalizer | Silhouette detection, head region, normalization, face mask, edge cases |
| `test_refinement.py` | 16 | refinement | Edge mask, dominant color, edge soften, palette unify, face protection, prompt building, full refinement |

### 3.2 Coverage Gaps (Tests Needed)

| Gap | Priority | Description |
|-----|----------|-------------|
| `decompose_book()` end-to-end | High | No test for structured storyboard (hits real LLM, needs `@pytest.mark.perf`) |
| `canvas_book` tool executor | High | No test for `CanvasBookExecutor.execute()` — the Stronghold tool |
| `image_provider` Azure path | Medium | No test for Azure fallback path |
| `image_provider` Gemini path | Medium | No test for Gemini fallback path |
| PDF text extraction verification | Medium | Verify PyPDF2 can extract text overlay from composed PDF |
| Character sheet quality check | Medium | No test for vision LLM quality validation |
| Lulu print job submission | Medium | No test for full print job creation (beyond cost calculation) |
| Error recovery full cycle | Low | Pipeline with real AI failures at each stage |
| Memory/performance bounds | Low | Large image processing (4K) should not OOM |

### 3.3 Test Tags

- `@pytest.mark.perf` — gates tests that hit real LLM/image APIs (5 tests currently)
- Default — deterministic tests using Pillow-generated images (113 tests)

---

## 4. API Contracts

### 4.1 Internal Module Interfaces

#### `character.py`

```python
def analyze_photo(image: PIL.Image) -> CharacterFeatures
def generate_reference_image(art_style: str = "warm watercolor") -> PIL.Image
def generate_character_sheet(features, child_name, child_age, art_style, reference_image=None) -> CharacterSheet
def create_character_sheet_from_photo(photo_path, child_name, child_age, art_style) -> CharacterSheet
def extract_poses(sheet_image: PIL.Image) -> dict[str, PIL.Image]
```

**Postconditions:**
- `analyze_photo` returns non-empty `CharacterFeatures` with all fields populated
- `generate_reference_image` returns deterministic image (same output for same `art_style`)
- `extract_poses` returns exactly 13 pose crops (one per POSE_BODY key)

#### `story.py`

```python
def generate_story(child_name, child_age, features, interests=None, theme_hint="", model=STORY_MODEL) -> Story
def validate_story(story: Story, child_age: int) -> list[str]
def decompose_book(child_name, child_age, features, page_count=12, orientation="landscape (wide)", ...) -> BookDecomposition
```

**Postconditions:**
- `generate_story` returns Story with exactly 32 pages
- `validate_story` returns empty list for valid stories
- `decompose_book` returns scenes with valid pose/composition values

#### `illustration.py`

```python
def generate_picture_book_illustrations(story, features, product, character_sheet=None, style="warm watercolor") -> list[IllustrationResult]
def generate_coloring_book_illustrations(features, child_name, product, art_style="bold_simple", ...) -> list[IllustrationResult]
```

**Postconditions:**
- All illustrations have correct resolution for product (300 DPI)
- Coloring illustrations are pure B&W after post-processing
- Returns exactly `product.page_count` illustrations

#### `image_provider.py`

```python
def generate_image(prompt, reference_image=None, preferred_provider=None, timeout=None) -> PIL.Image
```

**Postconditions:**
- Returns PIL Image or raises `RuntimeError("All image providers failed")`
- Never returns None
- Tries providers in priority order: cloudflare → azure → gemini

#### `bg_removal.py`

```python
def remove_background(image, threshold=240, feather=4, max_saturation_delta=50) -> PIL.Image
```

**Postconditions:**
- Returns RGBA image same dimensions as input
- Background pixels have alpha=0
- Foreground pixels preserved
- Edge pixels have soft alpha transitions when feather > 0

#### `character_normalizer.py`

```python
def detect_silhouette(image) -> Silhouette | None
def detect_head_region(image, silhouette) -> HeadRegion | None
def compute_normalization(silhouette, head_region, pose_bounds, canvas_size=1024) -> Normalization | None
def normalize_character(image, pose_bounds=None, target_width=1024, target_height=1024) -> tuple[PIL.Image, Silhouette | None, HeadRegion | None, Normalization | None]
def build_face_mask(head_region, canvas_size=1024) -> PIL.Image | None
```

#### `refinement.py`

```python
def refine_scene(composite, character_slot=None, head_region=None, style_token=None) -> RefinementResult
```

**Postconditions:**
- Always returns `RefinementResult` with `refined=True`
- `composite_original` is a copy of the input (input never mutated)
- `refinement_method` is `"pillow_fallback"`

#### `pipeline.py`

```python
def run_pipeline(order: OrderSpec, output_dir, skip_ai=False, fallback_to_golden=False, max_retries=3) -> PipelineResult
```

**Postconditions:**
- Returns `PipelineResult` (never raises for recoverable failures)
- `stages_completed` lists all stages that ran
- `errors` lists all failures
- Temp page images archived to `output_dir/archive/pages/`

### 4.2 Stronghold Tool Contract (`canvas_book`)

**Tool name:** `canvas_book`
**Groups:** `creative`, `canvas`

| Action | Required Params | Optional Params | Returns |
|--------|----------------|-----------------|---------|
| `create_book` | `photo_b64`, `child_name`, `child_age` | `book_type`, `art_style`, `interests`, `theme_hint` | JSON: success, stages, pdf sizes |
| `create_character` | `photo_b64` | `child_name`, `child_age`, `art_style` | JSON: ai_features, local_features |
| `create_story` | `child_name`, `child_age` | `hair`, `skin_tone`, `eye_color`, `interests`, `theme_hint` | JSON: title, pages, validation_issues |
| `create_storyboard` | `child_name`, `child_age` | `hair`, `skin_tone`, `eye_color`, `page_count`, `orientation`, `theme_hint` | JSON: title, style_contract, scenes |
| `generate_illustration` | `prompt` | — | JSON: image metadata |
| `remove_bg` | `image_b64` | — | JSON: image metadata |

**Error contract:**
- All errors return `ToolResult(success=False, error="<safe message>")`
- Raw provider exceptions never surface to callers
- Missing required params return descriptive error

### 4.3 Lulu API Contract

| Endpoint | Method | Purpose | Used By |
|----------|--------|---------|---------|
| `/print-job-cost-calculations/` | POST | Calculate print cost | `client.calculate_cost()` |
| `/print-jobs/` | POST | Create print job | Future: Stage 8 |
| `/print-jobs/{id}/` | GET | Check job status | Future: Stage 9 |
| `source_url` | — | PDF uploaded to public URL, Lulu fetches | Future: Stage 8 |

---

## 5. Implementation Plan

### Phase 1: Core Pipeline (DONE)

- [x] Product catalog (`products.py`) — 4 products, SKU specs, pricing
- [x] PDF composer (`pdf_composer.py`) — interior + cover with text overlay
- [x] Character generation (`character.py`) — photo analysis, reference image, char sheet
- [x] Story generation (`story.py`) — 32-page story + validation + storyboard decomposition
- [x] Illustration generation (`illustration.py`) — FC + BW, prompt builders, post-processing
- [x] Image provider (`image_provider.py`) — multi-provider with fallback chain
- [x] Pipeline orchestrator (`pipeline.py`) — 4 stages with golden fallback
- [x] Canvas templates (`canvas_templates.py`) — 14 poses, composition zones, style tokens
- [x] Golden samples infrastructure

### Phase 2: Post-Processing (DONE)

- [x] Background removal (`bg_removal.py`) — BFS flood fill with alpha feathering
- [x] Feature extractor (`feature_extractor.py`) — local pixel hair/skin/eye classification
- [x] Character normalizer (`character_normalizer.py`) — silhouette, head region, face mask
- [x] Refinement pass (`refinement.py`) — edge soften, palette unify, face protect

### Phase 3: Stronghold Integration (DONE)

- [x] `canvas_book` tool definition (`CANVAS_BOOK_TOOL_DEF`)
- [x] `CanvasBookExecutor` with 6 actions
- [x] Registration in `container.py`

### Phase 4: Quality & Coverage (NEXT)

- [ ] Add `@pytest.mark.perf` tests for `decompose_book()`
- [ ] Add tests for `CanvasBookExecutor` (mocked)
- [ ] Add tests for Azure/Gemini image provider fallback paths
- [ ] Add PDF text extraction validation test
- [ ] Run `ruff check`, `ruff format --check`, `mypy --strict` on new modules
- [ ] Run `bandit -r server/mcp/ -ll` security scan

### Phase 5: Lulu Production Integration

- [ ] Full print job creation (not just cost calculation)
- [ ] Job status polling + webhook
- [ ] PDF preflight validation (Lulu's requirements)
- [ ] Real PDF submission to Lulu sandbox

### Phase 6: Go-to-Market

- [ ] Build sample books using nieces' photos
- [ ] Set up dedicated Cloudflare account for MCP
- [ ] Set up dedicated Azure account + Azure for Startups
- [ ] Submit pipeline-generated PDF to Lulu sandbox validation
- [ ] Build wizard form (React frontend)
- [ ] Domain registration, Etsy store, KDP account

---

## 6. Audit Plan

### 6.1 Security Audit

| Check | Tool | Command | Scope |
|-------|------|---------|-------|
| Secret scanning | `bandit` | `bandit -r server/mcp/ -ll` | All new modules |
| Secret scanning | `bandit` | `bandit -r src/stronghold/tools/canvas_book.py -ll` | Stronghold tool |
| Hardcoded keys | grep | `rg -i "api.key|api_key|secret|password" server/mcp/` | No keys in source |
| Input validation | manual | Review all public functions | Photo size, age range, name length |
| Error information leak | manual | Review ToolResult.error messages | No provider details leaked |
| File path traversal | manual | Review `photo_path`, `output_dir` usage | No unsanitized paths |

**Acceptable risks:**
- API keys in environment variables (standard pattern)
- `photo_b64` decoded in memory (no disk persistence of raw photos in current impl)

### 6.2 Quality Audit

| Check | Tool | Command | Threshold |
|-------|------|---------|-----------|
| Lint | `ruff` | `ruff check server/mcp/` | 0 errors |
| Format | `ruff` | `ruff format --check server/mcp/` | 0 files changed |
| Type check | `mypy` | `mypy server/mcp/ --strict` | 0 errors (or documented exceptions) |
| Security | `bandit` | `bandit -r server/mcp/ -ll` | 0 high/critical |
| Test pass | `pytest` | `pytest server/mcp/tests/ -m "not perf"` | 100% pass |
| Test count | `pytest` | `pytest --co -q` | >= 113 tests |
| Import hygiene | manual | No circular imports between modules | Verified |

### 6.3 Performance Audit

| Check | Method | Threshold |
|-------|--------|-----------|
| BG removal 1MP image | `time remove_background(1024x1024)` | < 2s |
| Silhouette detection | `time detect_silhouette(1024x1024)` | < 1s |
| Refinement pass | `time refine_scene(1536x1024)` | < 3s |
| Pipeline skip_ai | `time run_pipeline(skip_ai=True)` | < 30s |
| Memory usage | Large image processing | < 500MB peak |

### 6.4 Audit Schedule

1. **Pre-PR audit** — run all quality checks, fix findings before PR
2. **Post-merge audit** — verify CI passes, run security scan on merged code
3. **Pre-production audit** — before first real order: full security review, pen test Lulu API keys handling, GDPR review for child photos

---

## 7. PR Review Plan

### 7.1 Review Checklist

For any PR touching the canvas book pipeline:

#### Correctness
- [ ] All 113 existing tests still pass
- [ ] New tests added for new functionality
- [ ] Golden samples still loadable
- [ ] PDF dimensions match Lulu spec (check `constants.py`)
- [ ] Text overlay only on picture books, not coloring books

#### Architecture
- [ ] No new external dependencies without approval
- [ ] No circular imports between `server/mcp/` modules
- [ ] Stronghold tool (`canvas_book.py`) uses proper `ToolResult` contract
- [ ] Image provider fallback chain preserved
- [ ] Pipeline stages independent (any stage can fail gracefully)

#### Security
- [ ] No API keys in source code
- [ ] No child photo data persisted to disk beyond pipeline execution
- [ ] Error messages don't leak provider details
- [ ] `photo_b64` validated before decode (size limit, format check)

#### Style
- [ ] `ruff check` passes
- [ ] `ruff format --check` passes
- [ ] No comments unless explicitly requested
- [ ] Follows existing module patterns (dataclass types, `from __future__ import annotations`)

#### Documentation
- [ ] If new module, added to `__init__.py` exports
- [ ] If new product, added to `products.py` catalog and test coverage
- [ ] If new tool action, added to `CANVAS_BOOK_TOOL_DEF` schema

### 7.2 Review Priority

| PR Type | Required Reviewers | Max Review Time |
|---------|-------------------|-----------------|
| New module | 1 (architect) | 48h |
| Bug fix | 1 (any) | 24h |
| Test only | Self-merge OK | — |
| Stronghold integration | 1 (architect) | 48h |
| PDF/Lulu changes | 1 (architect) | 48h |

---

## 8. CI Review Plan

### 8.1 CI Pipeline

```yaml
# .github/workflows/canvas-pipeline.yml (PROPOSED)
name: Canvas Pipeline CI
on: [push, pull_request]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: '3.12' }
      - run: pip install -r requirements.txt
      - run: python -m pytest server/mcp/tests/ -v -m "not perf" --tb=short
      - run: ruff check server/mcp/
      - run: ruff format --check server/mcp/
      - run: bandit -r server/mcp/ -ll
```

### 8.2 CI Gates

| Gate | Command | Blocking? | Bypass? |
|------|---------|-----------|---------|
| Unit tests (113) | `pytest -m "not perf"` | YES | Never |
| Lint | `ruff check` | YES | `# noqa` with justification |
| Format | `ruff format --check` | YES | Never |
| Security | `bandit -r -ll` | YES | `# nosec` with justification |
| Perf tests (5) | `pytest -m perf` | NO | N/A (manual) |
| Type check | `mypy --strict` | Soft | Document exceptions |

### 8.3 CI Failure Protocol

1. **Test failure** — Fix the test or the code. Never skip a failing test.
2. **Lint failure** — Fix the code. `# noqa` only for false positives with comment explaining why.
3. **Security failure** — Fix the vulnerability. `# nosec` only for confirmed false positives with security team approval.
4. **Format failure** — Run `ruff format server/mcp/` and commit.

---

## 9. Preflight Review Plan

### 9.1 Pre-Deployment Checklist

Before any change hits production (real customer orders):

#### Code Quality
- [ ] All 113+ tests pass (`pytest server/mcp/tests/ -m "not perf"`)
- [ ] `ruff check server/mcp/` — 0 errors
- [ ] `ruff format --check server/mcp/` — clean
- [ ] `bandit -r server/mcp/ -ll` — 0 high/critical
- [ ] Stronghold test suite passes (`pytest tests/ -x`)
- [ ] No new `# noqa` or `# nosec` without documented justification

#### PDF Validation
- [ ] Interior PDF matches Lulu spec for each product (dimensions, bleed, safety)
- [ ] Cover PDF spine width correct for page count
- [ ] Text overlay renders correctly (readable, positioned, not overlapping images)
- [ ] Coloring pages are pure B&W (no gray artifacts)
- [ ] PDF file size within limits (interior ≤ 100MB, cover ≤ 20MB)

#### Pipeline Integrity
- [ ] Golden samples exist and load correctly
- [ ] `fallback_to_golden=True` works for each stage independently
- [ ] Archive directory receives all temp pages after PDF composition
- [ ] No temp files left in output root
- [ ] Error messages are safe (no provider details, no stack traces)

#### API Integration
- [ ] Lulu cost calculation returns correct prices for all 4 products
- [ ] Image provider fallback chain works (CF → Azure → Gemini)
- [ ] `canvas_book` tool registered and callable from Stronghold
- [ ] All 6 tool actions return proper `ToolResult`

#### Security
- [ ] No API keys in source code or committed files
- [ ] `photo_b64` decoded in memory only (no disk persistence of raw photos)
- [ ] Error responses don't leak internal details
- [ ] Environment variables documented in this spec

#### Performance
- [ ] Pipeline `skip_ai` completes in < 30 seconds
- [ ] Background removal on 1MP image < 2 seconds
- [ ] No memory leaks in long-running processes (image handles closed)

#### Go/No-Go Decision

| Condition | Must Pass? |
|-----------|-----------|
| All 113+ tests green | YES |
| PDF dimensions match Lulu spec | YES |
| No security findings (bandit) | YES |
| Golden fallback works | YES |
| Perf tests pass (manual) | Recommended |
| Lulu sandbox PDF submission succeeds | YES (for production) |

**If any MUST-PASS condition fails: STOP. Fix before proceeding.**
