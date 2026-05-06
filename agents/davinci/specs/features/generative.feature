Feature: Generative actions
  Inpaint, outpaint, controlnet, upscale, relight, variation. Backed by
  external model endpoints via LiteLLM with priority-ordered fallback.

  See ../04-generative.md.

  Background:
    Given an authenticated user in tenant "acme"
    And a Page with raster Layer "L1" of size 1024x1024
    And LiteLLM is reachable

  @p0 @critical
  Scenario: Inpaint with a mask replaces the masked region only
    Given mask "M1" covers (200, 200, 600, 600) on "L1"
    When I inpaint "L1" with mask "M1" and prompt "a red dragon"
    Then a new generation request is sent to the inpaint endpoint
    And the request includes the layer source bytes, mask bytes, and prompt
    And the response replaces "L1"'s source bytes
    And "L1" keeps its previous transform, effects, blend, and id

  @p0 @critical
  Scenario: Inpaint mask wholly outside layer raises
    Given mask "M_out" covers (1100, 1100, 1300, 1300) on a 1024x1024 layer
    When I inpaint "L1" with "M_out"
    Then MaskOutOfBoundsError is raised
    And "L1" is unchanged

  @p0
  Scenario: Inpaint failure preserves the original layer
    Given the inpaint endpoint returns 500
    When I inpaint "L1" with "M1"
    Then GenerativeBackendError is raised
    And "L1"'s source bytes are unchanged

  @p0
  Scenario: Inpaint output is Warden-scanned
    Given the inpaint endpoint returns content flagged by Warden
    When I inpaint "L1"
    Then the layer is not updated
    And the audit log records a Warden rejection

  @p0
  Scenario: Outpaint extends the page in a direction
    Given a Page of size 1024x1024
    When I outpaint direction=right pixels=512 prompt="more sky"
    Then the page width becomes 1536
    And original layers are unchanged in position
    And a new layer is added covering the new region (x=1024, w=512)

  @p0
  Scenario: Outpaint into existing content places below by default
    Given two layers exist on the right edge of the page
    When I outpaint right with pixels=200
    Then the new layer's z_index is below the existing layers'

  @p0 @critical
  Scenario Outline: Tier defaults follow Da Vinci's draft-then-proof rule
    When I call <action> without explicit tier
    Then the request goes to the <expected_tier> models
    And the action requires user approval if tier=proof

    Examples:
      | action                | expected_tier |
      | inpaint               | proof         |
      | outpaint              | proof         |
      | controlnet_generate   | proof         |
      | upscale               | proof         |
      | variation             | draft         |
      | relight               | proof         |

  @p0
  Scenario: ControlNet uses control_layer's geometry
    Given a pose-control layer "C1" on the page
    When I controlnet_generate with control_type=pose, control_layer_id=C1, prompt="warrior"
    Then the request includes C1's bytes as the control image
    And the result respects C1's pose

  @p0
  Scenario: Upscale soft-cap rejects above 8192
    Given "L1" is 4096x4096
    When I upscale with factor=4 (would yield 16384x16384)
    Then UpscaleLimitError is raised

  @p0
  Scenario: Style reference and LoRA together: LoRA wins
    When I generate with reference_images=[X] AND lora_id=Y
    Then the request includes the LoRA
    And the reference images are demoted to img2img seeds (or omitted per model)

  @p0
  Scenario: Fallback chain triggers on 429 from primary
    Given the primary inpaint model returns 429
    And the secondary model returns 200
    When I inpaint "L1"
    Then the secondary model's result is used
    And the audit log records the model used

  @p0
  Scenario: All endpoints fail raises GenerativeBackendError
    Given every inpaint endpoint returns 500
    When I inpaint "L1"
    Then GenerativeBackendError is raised
    And the error wraps the chain of underlying exceptions

  @p0 @security
  Scenario: Audit entry records prompt hash and mask hash, not raw text
    When I inpaint "L1" with prompt P and mask M
    Then the audit entry contains sha256(P) and sha256(M)
    And does not contain the raw prompt or raw mask bytes

  @p0
  Scenario: Variation produces N children of an existing layer
    When I variation "L1" with count=3
    Then 3 new candidate layers are produced
    And each is a refine of "L1" with strength=0.4 default

  @p1 @perf
  Scenario: Inpaint round-trip on 1024² completes within budget
    When I inpaint a 1024x1024 layer with proof tier
    Then the round-trip completes in under 30 seconds

  @p1
  Scenario: Outpaint seam smoothing is the agent's responsibility
    When I outpaint right by 256 pixels
    Then the result may have a visible seam
    And the action does NOT auto-fix it
    And the agent rule recommends an inpaint pass with a feathered seam mask

  @p1
  Scenario: Relight changes lighting with subject preserved
    When I relight "L1" with light_direction="upper-left", color="warm", intensity=0.6
    Then the new layer has different illumination
    And the underlying subject silhouette is preserved within tolerance
