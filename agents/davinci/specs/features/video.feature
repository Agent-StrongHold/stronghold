Feature: Video (reach goal — sketch only)
  Timeline + keyframes + AI video gen + caption / overlay rendering;
  ffmpeg-based; async render queue. Detailed scenarios deferred to phase 7.

  See ../15-video.md.

  Background:
    Given an authenticated user in tenant "acme"

  @reach @p0
  Scenario: Import a video as a layer
    When alice video_layer_import a small mp4
    Then a VideoLayer exists with fps, dims, duration_ms set
    And the layer is added to the page

  @reach @p0
  Scenario: Generate a video from text prompt
    Given an AI video provider (e.g. Veo 3) configured + cost-gated
    When alice video_layer_generate prompt="dragon flying over castle", dims=1920x1080, duration_ms=4000
    Then a VideoLayer is created
    And the source.kind is "generated" with model + prompt + seed recorded

  @reach @p0
  Scenario: Animate a still canvas layer
    Given an existing canvas Layer
    When alice video_layer_animate_still duration_ms=5000 transform_anim="ken_burns"
    Then a VideoLayer of source.kind="still" exists with the animation params

  @reach @p0
  Scenario: Add a keyframe and interpolate on render
    Given a VideoLayer with property "x" keyframes at t=0 (x=0) and t=2000 (x=200) easing=LINEAR
    When the renderer runs at t=1000
    Then the layer is rendered at x=100 (linear interp)

  @reach @p0
  Scenario: Generate captions from a NarrationTrack
    Given a NarrationTrack with word timings
    When caption_from_narration is invoked
    Then a caption Track exists with per-segment text + timing

  @reach @p0
  Scenario: Generate captions from raw audio via Whisper
    Given an audio_blob_id without narration metadata
    When caption_from_audio is invoked
    Then Whisper transcription produces caption segments + timings

  @reach @p0
  Scenario: Render job lifecycle QUEUED → RUNNING → COMPLETED
    Given a Document with one video layer + audio + caption tracks
    When alice video_render to MP4
    Then a RenderJob exists in QUEUED
    And status transitions through RUNNING → COMPLETED with progress events
    And result_blob_id is set on COMPLETED

  @reach @p0
  Scenario: Render job cancellation stops mid-flight work
    Given a RUNNING RenderJob
    When alice render_cancel
    Then the job moves to CANCELLED
    And resources are released

  @reach @p1
  Scenario: Voice ducking under narration
    Given music + narration tracks overlapping
    When the final mix renders
    Then the music is ducked -6dB during voice
