# Canvas Engine Spec

**Project**: Main Character Press — personalized children's book production platform
**Engine Ships From**: `/root/github/stronghold/` (open-source Stronghold codebase)
**Deployed Via**: Conductor-router (`/root/docker/conductor-router/`) + Canvas Studio (`canvas-studio-poc/`)
**Status**: Planning — approved for implementation
**Last Updated**: 2026-04-29

---

## Architecture

```
                   Canvas Engine (Python)
        stronghold/tools/canvas{,_templates,_bg,_refine,_charsheet}.py
                   stronghold/types/canvas.py
                   stronghold/protocols/canvas.py
        ┌──────────────┬───────────────────┬──────────────────┐
        │              │                   │                  │
   Stronghold    Conductor-Router     Canvas Studio       Will spin
   Agent Tool     In-Process          (React + Express)    off someday
   Registry       _execute_canvas()   Owns its own DB      │
   In-process     In-process          HTTP only ◄───────────┘
                       │                   │
                       └───── REST ────────┘
                         POST /v1/tools/canvas
```

Three consumers, one engine. The Studio talks one HTTP contract — today it hits
conductor-router, someday wherever. Zero refactoring to detach.

| Consumer | Interface | Use Case | Spin-off? |
|----------|-----------|----------|-----------|
| **Stronghold** | `from stronghold.tools.canvas import execute_canvas` | Da Vinci / Fabulist agents call during react loops | No — OSS project |
| **Conductor-router** | `_execute_canvas()` — vendors `stronghold/tools/canvas_*.py` into `app/canvas/` | "draw me a logo" → canvas tool fires in-process | No — homelab gateway |
| **Canvas Studio** | HTTP to `POST /v1/tools/canvas` | Full storybook wizard, phased pipeline, own DB | **Yes** — clean HTTP boundary from day one |

---

## Phase 1: Wire Canvas Tool + Task Types

**Unblocks**: Da Vinci and Fabulist agents (both declare `tools: [canvas]` but crash at runtime)

### 1a. CANVAS_TOOL_DEF + registration

File: `src/stronghold/tools/canvas.py`

Append a `ToolDef` with JSON schema for all 9 actions:
- `generate`, `refine`, `reference`, `composite`, `text` (core 5)
- `upload`, `list_layers`, `transform`, `delete`/`duplicate` (extended 4)

Parameters per action:
- `generate`: prompt, tier (draft|proof), layer_type, model_id, negative_prompt, count, seed, width, height, style_token, pose, composition, mood, lighting, character_design, setting_desc, layer_role
- `refine`: prompt, layer_id, model_id, input_fidelity (0.0-1.0)
- `reference`: prompt, reference_images (base64[]), tier
- `composite`: canvas_id, include_layers (optional), format, quality, refine (bool)
- `text`: text, font, size, color, x, y
- `upload`: image_b64, name, layer_type
- `list_layers`: canvas_id
- `transform`: layer_id, x, y, scale, rotation, opacity, blend_mode
- `delete`: layer_id
- `duplicate`: layer_id
- `charsheet`: character_design, style_token, mood, lighting, tier, resolution, reference_images
- `remove_bg`: layer_id
- `refine_scene`: canvas_id, style_token, face_mask (optional)

File: `src/stronghold/container.py`

Register after quality gate tools (~line 384):
```python
from stronghold.tools.canvas import CANVAS_TOOL_DEF, execute_canvas
tool_registry.register(CANVAS_TOOL_DEF)
```

### 1b. Startup parity check

After all tools registered, iterate `agents_dir`:
1. Load each `agent.yaml`
2. For each tool in `agent.tools[]`, verify it resolves in `tool_registry`
3. Log: `"Tool parity check: OK (N agents, all tools resolve)"`
4. On mismatch: log specific agent+tool pair, raise `ConfigError`

### 1c. Task types + intent routing

| File | Change |
|------|--------|
| `src/stronghold/agents/intents.py` | Add `"image_gen": "davinci"`, `"storybook": "fabulist"` |
| `src/stronghold/classifier/keyword.py` | Add `storybook` strong indicators: `"make a storybook"`, `"create a picture book"`, `"children's book"`, `"illustrated story"`, `"make a book for my kid"` |
| `src/stronghold/classifier/llm_fallback.py` | Add `image_gen`, `storybook` to `_VALID_CATEGORIES`, update prompt |
| `config/example.yaml` | Add `image_gen` and `storybook` task_types with keywords |

### Acceptance

- `pytest tests/tools/test_canvas_executor.py tests/api/test_canvas_routes.py -v` passes
- Startup parity check OK with all agents
- `"make me a children's book about a brave fox"` → `storybook` → `fabulist`
- `"draw me a logo"` → `image_gen` → `davinci`

---

## Phase 2: Template Engine + Character Sheet

### 2a. Port template engine

**Source**: `canvas-studio-poc/src/lib/templateEngine.js` (568 lines)
**Target**: `src/stronghold/tools/canvas_templates.py` (NEW)

Port all token dictionaries as frozen dataclasses:

| JS Export | Python | Contents |
|-----------|--------|----------|
| `POSES` (14) | `POSES: dict[str, PoseTemplate]` | id, label, body, facing, angle, anchor, scale, arm_position, geo (bounds, head_center, face_box, shoulder_center, hip_center, ground_y) |
| `COMPOSITION_ZONES` (7) | `COMPOSITION_ZONES: dict[str, CompositionZone]` | character_slot, text_safe, focus_area (all ratios 0-1) |
| `STYLE_TOKENS` (7) | `STYLE_TOKENS: dict[str, StyleToken]` | line_weight, edge_softness, palette, contrast, detail_level, technique, bg_complexity |
| `MOOD_TOKENS` (6) | `MOOD_TOKENS: dict[str, MoodToken]` | saturation, brightness, warmth, tension |
| `LIGHTING_TOKENS` (6) | `LIGHTING_TOKENS: dict[str, LightingToken]` | direction, intensity, color_temp, shadow_softness |
| `SCENE_TYPES` (6) | `SCENE_TYPES: dict[str, SceneTypeDef]` | has_text, has_character, default_composition, prompt_hint |

Port prompt builders:
- `build_background_prompt(template, setting_desc) -> str` — must contain "NO CHARACTERS"
- `build_character_prompt(template, character_design, scene_action, handheld_props) -> str` — must contain "PURE WHITE background"
- `build_prop_prompt(template, prop, scene_action) -> str` — "NO characters"
- `build_character_design(char: dict) -> str`
- `generate_scene_plan(decomposition, book_spec) -> ScenePlan`
- `build_scene_template(scene_def, style, mood, lighting) -> SceneTemplate`

### 2b. Character reference sheet — single generation

**Source**: Concept from `renderingPipeline.js` + `bookApi.js` (both fail at reliable layout)
**Target**: `src/stronghold/tools/canvas_charsheet.py` (NEW)

**Core principle**: ONE image generation call. The AI produces the entire character sheet in a single shot. Reliability is achieved through a Pillow-generated reference image + ultra-precise prompt.

**Layout** (all positions are ratios 0-1, scales to any resolution):

```
┌───────────┬───────────┬───────────────────┐
│           │           │  walk_left         │
│  FRONT    │  3/4 LEFT │───────────────────│
│  (large)  │  (large)  │  walk_right        │
│           │           │───────────────────│
│           │           │  sitting           │
├───────────┼───────────┤───────────────────│
│           │           │  crouching         │
│  RUNNING  │  AWE      │───────────────────│
│  (large)  │  (large)  │  arms_raised       │
│           │           │───────────────────│
│           │           │  hugging           │
├───────────┴───────────┤───────────────────│
│ looking_up  pointing  edge_sit  cross_leg │
│ (small, bottom row)                        │
└───────────────────────────────────────────┘
```

- **4 large** (upper-left, ~37% width × 37% height): front, 3/4 left, running, looking up (awe)
- **5 medium** (right column, ~26% width × ~15% height): walk_left, walk_right, sitting, crouching, arms_raised
- **4 small** (bottom row, ~19% width × 26% height): looking_up, pointing, sitting_edge, cross_legged
- **Total: 13 poses** in one image

**Supported resolutions** (parameter on `charsheet` action):

| Resolution | Small-slot px size | Cost (draft) | Use Case |
|---|---|---|---|
| `1024` | ~170×130 | ~$0.01 | Quick drafts, previews |
| `1536` (default) | ~250×195 | ~$0.02 | Standard digital books |
| `2048` | ~340×260 | ~$0.04 | Print-quality reference |
| `4096` | ~680×520 | ~$0.10 | Poster/large-format |

#### Reference image generation (Pillow, zero AI cost)

The reference image is generated programmatically. It encodes **structural** information only — everything that's constant across all character sheets. Nothing that varies per character.

**In the reference image (structural, always the same):**
- Grid layout positions per resolution
- Per-slot scale (large/medium/small)
- Pose (joint positions, limb angles, body orientation)
- Facing direction
- Body proportions (child-sized head-to-body ratio)
- Ground contact points

**NOT in the reference image (character-specific, from the prompt):**
- Hair color, texture, style
- Skin tone, eye color, face shape
- Clothing, expression
- Style technique, lighting, color palette

**Drawing layers (bottom to top):**

1. **Background**: Light grey (#E8E8E8)
2. **Tier color tinting**: Faint tint per tier — large slots faint blue (#E8EEF4), medium faint green (#E8F4EC), small faint yellow (#F4F4E8)
3. **Grid cell borders**: Thin dashed lines (#C0C0C0), 4-6px gap between cells
4. **Labels**: Numbered pose labels ("1: FRONT", "2: 3/4 LEFT", etc.) at top-left of each slot, small sans-serif, ~40% opacity
5. **Facing arrows**: Small arrow near each mannequin's feet showing facing direction
6. **Skeleton**: Joint circles + limb lines at ~25% opacity. Slightly more solid than the mannequin.
7. **Mannequin**: Featureless grey body silhouettes at ~15% opacity. Head oval, torso trapezoid, limb cylinders. No face features, no hair, no skin color, no clothing, no details.

**Why skeleton more opaque than mannequin**: The skeleton is the primary structural guide (joint positions, limb angles). The mannequin is a volume/proportion hint only. The AI should follow the skeleton's pose, using the mannequin for scale.

**The mannequin is deliberately featureless**: It must not compete with character-specific features from the prompt. No hair, no skin tone, no eyes, no clothing — only body mass and limb position.

#### Prompt strategy

```
Character turnaround reference sheet for a children's book character.

Art style: {style_token.technique}
{character_design}

The reference image shows a layout with 13 pose positions.
Render the SAME child in EVERY pose position shown.
Follow the exact body pose, facing direction, and position of each figure in the reference.

4 LARGE POSES (upper-left):
  1. Front view — facing the viewer, standing neutral
  2. 3/4 turn left — slight angle showing depth
  3. Running — high energy, mid-stride, dynamic
  4. Standing in awe — head tilted up, arms slightly out

5 MEDIUM POSES (right column):
  Walking left, walking right, sitting cross-legged, crouching, arms raised in joy

4 SMALL POSES (bottom row):
  Looking up, pointing, sitting on edge, hugging

Each pose: full body head to toes. Consistent character across ALL poses.
NOT a sketch or wireframe — fully rendered {style_token.technique} illustration.
NO text, NO labels, NO watermarks.
```

#### Post-generation quality check

After generation, send the image to a cheap vision model (Gemini Flash, ~$0.001):
"Count the number of distinct character figures in this image. Are there approximately 13? Are 4 larger ones in the upper-left quadrant?"

If check fails, retry with reduced density (8 poses: 4 large + 4 key medium).

#### Faint labels on final output

After generation, Pillow composites faint labels (small sans-serif, ~40% opacity) on the final output along grid margins. These let the Studio UI identify poses programmatically without OCR.

#### API response

```json
{
  "image_b64": "...",
  "pose_map": {
    "front":      {"x": 0.0, "y": 0.0, "w": 0.37, "h": 0.37, "slot": "large_1"},
    "3q_left":    {"x": 0.37, "y": 0.0, "w": 0.37, "h": 0.37, "slot": "large_2"},
    "running":    {"x": 0.0, "y": 0.37, "w": 0.37, "h": 0.37, "slot": "large_3"},
    "awe":        {"x": 0.37, "y": 0.37, "w": 0.37, "h": 0.37, "slot": "large_4"},
    "walk_left":  {"x": 0.74, "y": 0.0, "w": 0.26, "h": 0.15, "slot": "med_1"},
    "walk_right": {"x": 0.74, "y": 0.15, "w": 0.26, "h": 0.15, "slot": "med_2"},
    "sitting":    {"x": 0.74, "y": 0.30, "w": 0.26, "h": 0.15, "slot": "med_3"},
    "crouching":  {"x": 0.74, "y": 0.45, "w": 0.26, "h": 0.15, "slot": "med_4"},
    "arms_up":    {"x": 0.74, "y": 0.60, "w": 0.26, "h": 0.15, "slot": "med_5"},
    "looking_up": {"x": 0.0, "y": 0.74, "w": 0.19, "h": 0.26, "slot": "sm_1"},
    "pointing":   {"x": 0.19, "y": 0.74, "w": 0.19, "h": 0.26, "slot": "sm_2"},
    "edge_sit":   {"x": 0.38, "y": 0.74, "w": 0.19, "h": 0.26, "slot": "sm_3"},
    "cross_leg":  {"x": 0.57, "y": 0.74, "w": 0.19, "h": 0.26, "slot": "sm_4"}
  },
  "poses_generated": 13,
  "resolution": 1536,
  "layout": "4_large_5_med_4_small"
}
```

The Studio uses `pose_map` to crop individual poses from the sheet for page composition.

### 2c. Storyboard reference wireframes

For each page in the scene plan, Pillow generates a wireframe reference showing:

- **Composition zone** (from `COMPOSITION_ZONES`) with faint blue tint
- **Text safe area** with faint yellow tint
- **Character slot** with the scene's pose skeleton + mannequin at correct position/scale
- **Environment prop placeholders** at their placement positions
- **Scene type label** ("STORY_BEAT", "EMOTIONAL_BEAT", etc.)
- **Facing arrow** for the character
- **Numbered label** for the page

Generation flow:
1. LLM decomposes story into scene plan
2. Pillow generates per-page wireframe references
3. Per-page: one AI call with wireframe reference + `build_background_prompt()` + scene description
4. Character and prop layers generated separately (background → character on white → composite)

### 2d. Integration with canvas tool

File: `src/stronghold/tools/canvas.py`

- `action="generate"` accepts optional `style_token`, `pose`, `composition`, `mood`, `lighting`, `character_design`, `setting_desc`, `layer_role` — routes through `build_*_prompt()` when provided, current behavior when absent
- `action="charsheet"` calls `canvas_charsheet.generate_character_sheet()`
- `action="storyboard_ref"` calls `canvas_templates.generate_storyboard_wireframe()`

### Tests

- `tests/tools/test_canvas_templates.py` — every prompt builder deterministic, correct content flags
- `tests/tools/test_canvas_charsheet.py` — reference image generation: 13 slots placed, no overlap, correct tiers, no character features on mannequin
- `tests/tools/test_canvas_storyboard.py` — wireframe per scene type, composition zones correct, character slot positioned

---

## Phase 3: Background Removal + Refinement

### 3a. Background removal

**Source**: `renderingPipeline.js` BFS flood-fill (~150 lines)
**Target**: `src/stronghold/tools/canvas_bg.py` (NEW)

`remove_background(image: bytes, threshold: float = 0.85, feather: int = 3) -> bytes`
- BFS from edges, luminance threshold, alpha feathering
- Pillow-based (PIL.Image, ImageDraw, ImageFilter)

### 3b. Refinement pass

**Source**: `refinementPass.js` (298 lines)
**Target**: `src/stronghold/tools/canvas_refine.py` (NEW)

`refine_scene(composite: bytes, style_token: StyleToken, face_mask: bytes | None) -> bytes`
- Edge softening (GaussianBlur at seam boundaries)
- Palette unification (dominant color shift)
- Contrast normalization
- Face mask protection
- Pillow-only — deterministic post-processing, no AI call

### 3c. New canvas actions

- `action="remove_bg"` — calls `canvas_bg.remove_background()`
- `action="composite"` gains `refine: bool = false`
- `action="refine_scene"` — standalone refinement pass

### Tests

- `tests/tools/test_canvas_bg.py` — synthetic white-bg → remove_bg → corners transparent, center preserved
- `tests/tools/test_canvas_refine.py` — harsh-edge composite → refine → edges softened, face mask unchanged

---

## Phase 4: Wire into Conductor-Router

### 4a. Vendor canvas modules

```
/root/docker/conductor-router/app/canvas/
    __init__.py
    executor.py       # from stronghold/tools/canvas.py
    templates.py      # from stronghold/tools/canvas_templates.py
    charsheet.py      # from stronghold/tools/canvas_charsheet.py
    bg.py             # from stronghold/tools/canvas_bg.py
    refine.py         # from stronghold/tools/canvas_refine.py
    types.py          # relevant types from stronghold/types/canvas.py (simplified, single-tenant)
```

Strip multi-tenant parts (org_id scoping, Warden scans, K8s config). Header comment noting upstream source.

### 4b. Tool dispatch

File: `/root/docker/conductor-router/app/tools.py`

```python
if tool_name == "canvas":
    return await _execute_canvas(arguments)
```

`_execute_canvas()` calls vendored `execute_canvas()` with LiteLLM config from env. No org_id, no Warden.

### 4c. Config

File: `/root/docker/conductor-router/config.yaml`

Add `canvas` tool definition under `tools:` with full action schema.

### 4d. Re-enable image_gen classifier

File: `/root/docker/conductor-router/app/classifier.py`

Uncomment `image_gen` strong indicators. Add `storybook` indicators.

### Acceptance

- `curl -X POST http://localhost:8100/v1/tools/canvas -d '{"action":"generate","prompt":"a sunset beach","tier":"draft","layer_type":"background"}'` returns image data
- `curl -X POST http://localhost:8100/v1/tools/canvas -d '{"action":"charsheet","character_design":"A girl named Luna...","style_token":"Warm watercolor childrens book"}'` returns composite with 13 poses + pose_map
- "draw me a sunset" → `image_gen` → canvas tool fires

---

## Phase 5: Evolve Canvas Studio POC

### 5a. Replace direct API calls

File: `canvas-studio-poc/src/lib/renderingPipeline.js`

Replace `azureImageGen()`, `azureImageEdit()`, `geminiImageGen()` with:

```javascript
async function conductorCanvasAction(params) {
  const res = await fetch(`${CONDUCTOR_URL}/v1/tools/canvas`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...(CONDUCTOR_KEY ? { Authorization: `Bearer ${CONDUCTOR_KEY}` } : {}),
    },
    body: JSON.stringify(params),
  });
  if (!res.ok) throw new Error(`Canvas API ${res.status}`);
  const data = await res.json();
  return data.image_b64 || data.image_url || null;
}
```

Keep `makePlaceholder()` as final fallback.

### 5b. Replace direct LiteLLM calls

File: `canvas-studio-poc/src/lib/storyApi.js`

`llm()` → calls conductor-router `/v1/chat/completions` instead of LiteLLM directly.

### 5c. Replace character sheet generation

Files: `CharacterSetup.jsx` + `bookApi.js` + `renderingPipeline.js`

Replace `generateCanonicalSheet()` and `renderCharacterReferences()` with single call:
`conductorCanvasAction({action: "charsheet", character_design, style_token, resolution: 1536})`

UI displays the single composite sheet with pose_map for cropping.

### 5d. Keep as-is

- `templateEngine.js` — stays for UI controls (pose/style pickers). Eventually fetches tokens from backend.
- `server.js` + Express — stays, owns book/character/template persistence in Postgres.
- `refinementPass.js` — stays as client-side fallback. Primary path: server-side via canvas tool.

### 5e. Docker deployment

File: `/root/docker/canvas-studio/docker-compose.yml` (NEW)

```yaml
services:
  canvas-studio:
    build: ../../github/stronghold/canvas-studio-poc
    ports:
      - "127.0.0.1:5174:5174"
    environment:
      VITE_CONDUCTOR_URL: "http://conductor-router:8100"
      VITE_CONDUCTOR_KEY: "${CONDUCTOR_ROUTER_KEY}"
      DATABASE_URL: "postgresql://..."
    networks:
      - traefik
```

Traefik: `https://studio.library.emeraldfam.org` → oauth2-proxy → canvas-studio `:5174`

### Acceptance

- Studio works identically to current POC
- Network tab: zero direct Azure/Gemini/LiteLLM calls from browser
- Character sheet: 13 poses in correct grid layout with labels
- All story + image calls route through conductor-router

---

## Dependency Graph

```
Phase 1 (wire canvas + task types)   ─── independent
Phase 2 (templates + charsheet)      ─── independent
Phase 3 (bg removal + refine)        ─── independent
     │
     ├── Phase 4 (conductor-router)   ─── depends on 1+2+3
     │         │
     │         └── Phase 5 (Studio)    ─── depends on 4
```

Phases 1-3 parallel. Phase 4 requires all three. Phase 5 requires Phase 4.

---

## What Ships Where

| Module | Stronghold (OSS) | Conductor-Router (vendored) | Studio (dependency) |
|--------|:-:|:-:|:-:|
| `canvas.py` executor | Original | Vendored copy | Calls via HTTP |
| `canvas_templates.py` | Original | Vendored copy | Calls via HTTP |
| `canvas_charsheet.py` | Original | Vendored copy | Calls via HTTP |
| `canvas_bg.py` | Original | Vendored copy | Calls via HTTP |
| `canvas_refine.py` | Original | Vendored copy | Calls via HTTP |
| `types/canvas.py` | Original (multi-tenant) | Simplified (single-tenant) | N/A |
| `protocols/canvas.py` | Original | N/A | N/A |
| Template engine tokens | `canvas_templates.py` | Same vendored copy | `templateEngine.js` (keeps local for UI) |
| Book persistence (Postgres) | N/A | N/A | Owns it |

---

## LOC Estimate

| Phase | New | Modified | Ported |
|-------|-----|----------|--------|
| 1: Wire + task types | ~120 | ~30 | 0 |
| 2a: Template engine | ~600 | ~30 | 568 from JS |
| 2b: Character sheet | ~350 | ~20 | 0 |
| 2c: Storyboard wireframes | ~200 | ~10 | 0 |
| 3: BG removal + refine | ~350 | ~25 | ~400 from JS |
| 4: Conductor-router | ~60 | ~50 | 0 |
| 5: Studio frontend | ~80 | ~100 | 0 |
| **Total** | **~1760** | **~265** | **~970** |

---

## Open Questions

1. **Vendor vs pip for conductor-router?** Defaulting to vendor. Revisit if Stronghold packages cleanly.
2. **Template token REST endpoint?** `GET /v1/tools/canvas/tokens` — lets Studio fetch available poses/styles. Low priority.
3. **Small-pose charsheet at lower resolution?** Could generate 9 smaller slots at 512×512 to halve cost. Optimize later.
