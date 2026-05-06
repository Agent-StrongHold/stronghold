# 15 — Video (Reach Goal)

**Status**: REACH / Phase 7. Separate program with own quality gates.
**One-liner**: timeline + keyframes + AI video generation + caption / overlay
rendering, ffmpeg-based pipeline, async render queue.

## Audience

After static product (books / posters / infographics) is solid. Video is
~6 calendar weeks of focused work; do not start until preflight, versioning,
exports, and corrections all stable.

## Architecture

A sibling tool to canvas: `motion.py`. Layers shared with canvas via the
`Layer` model (§01) — video layers are an additional `LayerType` =
`VIDEO`. Render goes through a dedicated `VideoRenderer` not `Pillow`.

Optionally a sibling agent `Cinematographer` extending Da Vinci with
video-only actions, gated by trust tier.

## Data model

```
VideoLayer (frozen):
  id: str
  layer_type: VIDEO
  source: VideoSource              # imported file, generated, image-as-still
  in_ms: int                       # in-point in source
  out_ms: int                      # out-point
  audio_track: AudioTrackRef | None # link to NarrationTrack §27
  blend_mode: BlendMode             # composite blend
  opacity: float
  effects: tuple[Effect, ...]      # per-frame effects
  keyframes: tuple[Keyframe, ...]  # animated properties

VideoSource (tagged union):
  Imported:    {kind: "imported", blob_id, fps, dims, duration_ms}
  Generated:   {kind: "generated", blob_id, model, prompt, seed, fps, dims}
  StillImage:  {kind: "still", layer_id, duration_ms, transform_anim}

Keyframe (frozen):
  time_ms: int
  property: str                    # "x", "y", "scale", "opacity", "rotation", etc.
  value: float
  easing: EasingKind               # LINEAR | EASE_IN | EASE_OUT | EASE_IN_OUT | BEZIER

Track (frozen):
  id: str
  document_id: str
  kind: TrackKind                  # VIDEO | AUDIO | OVERLAY | CAPTION
  clips: tuple[Clip, ...]
  muted: bool = False
  locked: bool = False

Clip (frozen):
  id: str
  track_id: str
  layer_id: str                    # which layer renders during this clip
  start_ms: int                    # within track timeline
  duration_ms: int
```

## Rendering pipeline

```
def render_video(timeline, options) -> bytes:
    # 1. Compute final dims, fps, duration
    # 2. For each frame:
    #    For each track (video/overlay/caption):
    #      - Find active clip at this time
    #      - Render layer at this time (apply keyframes via interpolation)
    #      - Apply effects per-frame
    #    Composite tracks via blend_mode + opacity
    # 3. Mux audio tracks
    # 4. Encode to target format (ffmpeg)
```

Backed by ffmpeg via `ffmpeg-python`; per-frame layer composition by Pillow
(reuses existing pipeline).

## AI video generation

| Provider | Use | Cost |
|---|---|---|
| Veo 3 (Google) | text→video, image→video | varies |
| Runway Gen-4 | text→video, motion brush | $$$ |
| Kling 2.5 | text→video, style transfer | $$ |
| Sora 2 (when accessible) | text→video, longer durations | $$$$ |
| Stable Video Diffusion | image→video, self-hosted | compute only |

Cost-gated per §31. Routed through LiteLLM if/when generative video lands
in their proxy; otherwise direct provider.

## Subtitles / captions

Two paths:
1. **From narration** (§27) — segments + word timings → caption track
2. **From audio** (no narration) — Whisper transcription → caption track

Caption rendering: per-segment text layer with start/end keyframes for
fade-in/out. Supports VTT/SRT export as sidecar.

## Voiceover

Cross-ref §27. Audio tracks added with auto-ducking (-6 dB) when overlapping.

## Background removal on video

RMBG-V2 / SAM-2 video → alpha-channel video. Per-frame application; cached
per source.

## Color grading

Per-clip LUT (3D LUT or per-frame CMYK-style transform). Reuses §07 effects
on a per-frame basis (slow but consistent).

## Stabilization

`ffmpeg vidstabdetect` + `vidstabtransform` two-pass. Caches detection per
source.

## Animations on existing static layers

`StillImage` source kind: take an existing canvas Layer, give it a
duration, optionally a `transform_anim` (Ken Burns pan/zoom, etc.).

This is the path for "animate my book" and "make a moving poster" use
cases without leaving the canvas.

## Render queue

Videos render in seconds-to-minutes; cannot block. Queue via existing
worker pattern (`worker_main.py` etc.):

```
RenderJob (frozen):
  id: str
  document_id: str
  target_format: VideoFormat
  options: RenderOptions
  status: RenderStatus              # QUEUED | RUNNING | COMPLETED | FAILED | CANCELLED
  progress_pct: int
  result_blob_id: str | None
  error: str | None
  created_at, started_at, completed_at
```

WebSocket events stream progress to UI.

## Export formats

| Format | Codec | Container |
|---|---|---|
| MP4 | H.264 | mp4 (default) |
| MP4 (HEVC) | H.265 | mp4 |
| WebM | VP9 | webm |
| WebM (AV1) | AV1 | webm |
| GIF | gif | gif (lossy palette) |
| MOV (alpha) | ProRes 4444 | mov |

## API surface

| Action | Args | Returns |
|---|---|---|
| `video_layer_import` | `file_bytes, [trim]` | VideoLayer |
| `video_layer_generate` | `prompt, [model, image_layer_id], dims, duration_ms` | VideoLayer |
| `video_layer_animate_still` | `layer_id, duration_ms, transform_anim` | VideoLayer |
| `keyframe_add` | `layer_id, property, time_ms, value, easing` | Keyframe |
| `keyframe_update` | `keyframe_id, value/time/easing` | Keyframe |
| `track_add` | `document_id, kind` | Track |
| `clip_add` | `track_id, layer_id, start_ms, duration_ms` | Clip |
| `caption_from_narration` | `narration_id` | caption Track |
| `caption_from_audio` | `audio_blob_id` | caption Track (Whisper) |
| `video_render` | `document_id, format, options` | RenderJob |
| `render_status` | `job_id` | RenderJob |
| `render_cancel` | `job_id` | RenderJob |

## Edge cases

(deferred — comprehensive list once the static product stabilizes; key
classes: aspect mismatch between clips, audio drift, frame drops on long
renders, GPU memory limits on AI gen, re-rendering when source updates,
color space drift across formats)

## Errors (deferred to implementation)

## Test surface (sketch)

- Per-frame composition deterministic
- Keyframe interpolation correct per easing
- Caption alignment within tolerance
- Render job lifecycle correct
- Cost gating works per provider

## Dependencies

- ffmpeg + `ffmpeg-python`
- `pyav` (alternative low-level)
- Whisper / `whisperx` (existing in §27)
- Provider API integrations
- Existing worker pattern + WebSocket
