# 04 — Generative Actions (Inpaint, Outpaint, ControlNet, Upscale)

**Status**: P0. Depends on 03 (masks), 09 (style lock).
**One-liner**: first-class generative ops beyond plain `generate` / `refine`.

## Problem it solves

Today's `refine` accepts a `region` crop box, no real mask, no controlnet, no
LoRA, no outpaint, no upscale. For book illustration iteration we need:

- **Inpaint** with arbitrary mask (fix a character's hands without touching face)
- **Outpaint** to extend a too-tight composition into bleed
- **ControlNet** (pose/depth/edge) so a generated character matches an existing pose
- **Upscale** so a draft 1024×1024 becomes a 4096×4096 print-ready hero
- **LoRA / IP-Adapter** style injection so all 32 pages share an art style

## Actions (canvas tool)

| Action | Args | Backend |
|---|---|---|
| `inpaint` | `layer_id, mask_id, prompt, [reference_images], [strength]` | FLUX Kontext Pro inpaint variant or SDXL inpaint |
| `outpaint` | `page_id, direction: up\|down\|left\|right\|all, pixels, prompt` | FLUX Kontext outpaint preset |
| `controlnet_generate` | `prompt, control_type: pose\|depth\|canny\|scribble\|reference, control_layer_id, [strength]` | SDXL+ControlNet via Replicate/fal |
| `style_reference` | (param on `generate`) `reference_images` or `lora_id` or `ip_adapter_id` | LiteLLM model that exposes the field |
| `upscale` | `layer_id, factor: 2\|4, model: realesrgan\|topaz\|flux-upscaler` | Replicate/fal endpoint |
| `relight` | `layer_id, light_direction, light_color, intensity` | FLUX Kontext "change lighting" or IC-Light endpoint |
| `variation` | `layer_id, count: 1..4` | thin wrapper over `refine` with strength 0.4 |

Backends are listed in priority order; first-success-wins fallback chain
matches the existing pattern in `_generate_image` (canvas.py:174–200).

## Data flow (inpaint as canonical example)

```
inpaint(layer_id, mask_id, prompt)
  → load layer source bytes from blob store
  → load mask bytes
  → assemble multipart request: image, mask, prompt, [references]
  → LiteLLM /v1/images/edits  (or model-specific endpoint)
  → fallback chain on 429/5xx
  → result bytes → new blob → new Layer (preserves transform/effects/blend from source)
  → audit entry: (op, model, cost, prompt_hash, mask_hash, layer_id)
```

The new Layer replaces the old one in-place (same `id`, new `source.image_bytes`)
so undo can restore the prior blob ref.

## Cost discipline

Inpaint and ControlNet are proof-tier endpoints by default ($0.03–$0.10 per
call). Da Vinci's existing `MUST-NEVER` rule — "no proof render without user
approval" — extends to these ops. Tool spec adds explicit `tier` parameter.

## Edge cases

1. **Inpaint mask wholly outside layer bounds** — clipped to layer bounds; if
   intersection area is 0, raise `MaskOutOfBoundsError`.
2. **Outpaint into existing content** — when extending into a region that
   already has a layer, new layer's z_index is below existing; agent must
   composite explicitly if it wants the inverse.
3. **ControlNet with mismatched control image size** — auto-resized; warn
   above 2× scale.
4. **Upscale on already-large layer** — soft cap at 8192×8192; reject above.
5. **Style reference + LoRA both passed** — LoRA wins; reference_images
   demoted to img2img seeds.
6. **All endpoints fail** — raise `GenerativeBackendError(RoutingError)` with
   the chain of exceptions; agent falls back to draft tier per existing rule.
7. **Generated content fails Warden** — content rejected, layer unchanged,
   audit entry records the rejection reason.
8. **Outpaint produces a seam** — known artefact; the action does NOT
   auto-fix; agent uses `inpaint` with a feathered mask along the seam.

## Errors

- `MaskOutOfBoundsError(ToolError)`
- `GenerativeBackendError(RoutingError)`
- `UpscaleLimitError(ConfigError)`
- `ControlNetMismatchError(ConfigError)`

## Test surface

- Unit: param schema for every action; cost-tier defaults; fallback chain
  selection logic.
- Integration: each action invokes the right model in priority order; fallback
  triggers on simulated 429; Warden scan applied to every output.
- Performance (`@perf`): inpaint round-trip < 30s on a 1024² layer using the
  configured proof-tier endpoint.
- Security: prompt + mask hash logged to audit; no raw user input in trace
  metadata; bandit clean.

## Dependencies

- existing LiteLLM proxy
- New model entries in LiteLLM config: SDXL-inpaint, FLUX Kontext, SAM-2,
  Real-ESRGAN, IC-Light, ControlNet (pose/depth/canny/scribble)
- No new Python deps
