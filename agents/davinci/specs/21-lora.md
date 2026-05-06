# 21 — LoRA / Fine-tuning

**Status**: P1 / Optimization phase (after operational maturity).
**One-liner**: train a per-book or per-user LoRA on accepted proof renders +
character refs + style lock; switch generation to base-model + LoRA for
5-10× cheaper, more consistent output.

## Why this is at phase 6, not phase 1

Per the revised order (see SPEC.md): LoRA is an *optimization* of an
already-working system. It depends on:
- §22 preflight — clean training data
- §23 versioning — rollback path if LoRA degrades quality
- §31 cost & budget — visible training charge
- §30 critics — clean signal extraction
- §25 accessibility — bake constraints in, don't retrofit
- §26 i18n — train per-language, not English-only
- §27 audio — voice consistency separate problem

## Data model

```
LoraTrainingJob (frozen):
  id: str
  tenant_id: str
  user_id: str
  scope: LoraScope                  # DOCUMENT | CHARACTER | STYLE_LOCK | USER
  scope_id: str                     # the doc / character / lock id
  base_model: str                   # "flux.1-dev", "sdxl-1.0", etc.
  trainer: LoraTrainer              # provider
  training_data: tuple[str, ...]    # blob ids of training images
  metadata_jsonl_blob_id: str       # captions per image
  status: LoraJobStatus             # PENDING | RUNNING | COMPLETED | FAILED | CANCELLED
  forecast_cost_usd: Decimal
  actual_cost_usd: Decimal | None
  forecast_duration_minutes: int
  actual_duration_minutes: int | None
  result_lora_id: str | None        # populated on COMPLETED
  failure_reason: str | None
  triggered_by: TriggeredBy         # USER | AUTO_AFTER_N_REFS | SCHEDULED
  created_at, updated_at, completed_at

LoraScope (StrEnum):
  DOCUMENT          # one book → one LoRA capturing its style + characters
  CHARACTER         # single character ref → consistent per-prompt
  STYLE_LOCK        # style lock → cross-document style anchor
  USER              # user's overall taste (advanced)

LoraTrainer (StrEnum):
  REPLICATE_FLUX_TRAINER
  FAL_FLUX_LORA
  TOGETHER_LORA
  LOCAL                              # self-hosted, P2

LoraJobStatus (StrEnum):
  PENDING | RUNNING | COMPLETED | FAILED | CANCELLED

TriggeredBy (StrEnum):
  USER
  AUTO_AFTER_N_REFS                  # auto-trigger when scope has N qualifying training images
  SCHEDULED                           # nightly retrain when N new corrections

Lora (frozen):
  id: str
  tenant_id: str
  owner_id: str
  scope: LoraScope
  scope_id: str
  base_model: str
  trigger_words: tuple[str, ...]    # for prompt activation
  rank: int = 16                    # LoRA rank
  alpha: int = 32                   # LoRA alpha
  blob_id: str                      # the actual safetensors weights
  thumbnail_blob_id: str | None     # generated sample
  metadata: Mapping[str, Any]
  trained_at: datetime
  parent_lora_id: str | None        # for re-training that builds on prior
  active: bool                      # current active LoRA for the scope
  retired_at: datetime | None
```

## Training data selection

Per scope, the training set is auto-curated:

| Scope | Training data |
|---|---|
| `DOCUMENT` | All proof-tier layers from completed pages; min 20, max 60. Captions: layer prompts |
| `CHARACTER` | Multi-view reference sheet + all proof layers depicting that character; min 10 |
| `STYLE_LOCK` | All layers tagged with this lock id, across all docs in same tenant; min 30 |
| `USER` | Cross-document distillation; only from public/owned docs; min 100; opt-in |

Each image is captioned automatically (vision-LLM) with the character/style
descriptors, brand kit terms, and trigger word.

## Trigger words

Per-LoRA trigger word avoids prompt collision:
- `DOCUMENT` LoRA: `<book-{id-suffix}>`
- `CHARACTER` LoRA: name normalized (e.g. `<lily-dragon>`)
- `STYLE_LOCK` LoRA: `<style-{lock-name}>`

When LoRA active, prompts auto-include trigger word.

## Training pipeline

```
def train_lora(scope, scope_id, [trainer]) -> LoraTrainingJob:
    # 1. Curate training data (auto)
    images = curate(scope, scope_id)
    if len(images) < min_for_scope(scope):
        raise InsufficientTrainingDataError
    # 2. Caption each image
    captions = [caption(img, scope_metadata) for img in images]
    # 3. Build metadata.jsonl
    jsonl = build_jsonl(images, captions, trigger_word)
    # 4. Cost forecast (cross-ref §31)
    forecast = forecast_lora_cost(trainer, num_images=len(images))
    # 5. Cost gate (per §31)
    if not approval_check(forecast): raise ApprovalRequiredError
    # 6. Submit job
    job = trainer.submit(images, jsonl, base_model, ...)
    # 7. Poll asynchronously; emit events
    return job
```

## Application

When a Document or context has an active LoRA:

```
def build_generation_request(prompt, ctx):
    loras_to_apply = []
    if ctx.document.active_lora_id:
        loras_to_apply.append(load_lora(ctx.document.active_lora_id))
    for char_id in ctx.referenced_characters:
        if char_lora := character_lora(char_id):
            loras_to_apply.append(char_lora)
    if ctx.style_lock and ctx.style_lock.lora_id:
        loras_to_apply.append(load_lora(ctx.style_lock.lora_id))
    final_prompt = inject_trigger_words(prompt, loras_to_apply)
    selected_model = base_model_for(loras_to_apply)
    return GenerationRequest(prompt=final_prompt, loras=loras_to_apply, model=selected_model)
```

LoRA cost: included in per-call provider price (Replicate / fal). Often
free if hosted.

## Quality gates

Before promoting a trained LoRA to "active":
- Generate 5 sample images with prompts from the training set
- Vision-LLM compares samples to training data → quality score
- If score below threshold, flag job FAILED with reason; retain for review
- Pre-flight (§22) integration: any LoRA marked non-passing is excluded from
  generation

## Versioning + rollback

Every LoRA is versioned; previous LoRA stays available:
- Set new LoRA active; old LoRA marked inactive (not deleted)
- "Rollback LoRA" sets previous as active
- N most recent retained; older auto-deleted per retention policy (180 days
  default; pinned LoRAs retained indefinitely)

## Auto-training trigger

After N qualifying corrections accumulate for a scope:

| Scope | Threshold | Cadence |
|---|---|---|
| DOCUMENT | 30 proof renders + style lock | one-shot at 80% completion |
| CHARACTER | 15 high-confidence character corrections | weekly check |
| STYLE_LOCK | 50 layers under lock | weekly check |
| USER | 200 cross-doc proofs | monthly |

Auto-trigger creates a job in PENDING state; user must approve via cost gate.

## Cost forecasts

| Trainer | Cost per LoRA | Time |
|---|---|---|
| Replicate (FLUX) | $1.20-3.00 | 15-30 min |
| Fal (FLUX) | $1.50-4.00 | 10-20 min |
| Together (SDXL) | $0.50-1.50 | 20-40 min |
| Local (self-hosted) | compute only | depends |

Cost-gated per §31; user sees forecast and approves.

## API surface

| Action | Args | Returns |
|---|---|---|
| `lora_train` | `scope, scope_id, [trainer, base_model]` | LoraTrainingJob |
| `lora_status` | `job_id` | LoraTrainingJob |
| `lora_cancel` | `job_id` | LoraTrainingJob |
| `lora_list` | `[scope, scope_id]` | tuple[Lora, ...] |
| `lora_activate` | `lora_id` | Lora set as active for its scope |
| `lora_deactivate` | `lora_id` | unmark active |
| `lora_pin` | `lora_id` | retained indefinitely |
| `lora_delete` | `lora_id` | (only inactive) |
| `lora_compare` | `lora_id_a, lora_id_b, prompt` | side-by-side renders |

## Edge cases

1. **Insufficient training data** — `InsufficientTrainingDataError`; clear
   message of how many more images needed.
2. **Training failure** (provider, OOM, etc.) — job FAILED with reason;
   user can retry; cost partially refunded if partial fail.
3. **Quality gate fails** — LoRA produced but quality score low; job
   COMPLETED but not auto-active; user can review and decide.
4. **Multiple LoRAs active for same prompt** (doc + character + style) —
   provider may cap at 3-5 LoRAs; warn if more requested; combine via
   weighted blending where supported.
5. **Trigger word collision** with another active LoRA — auto-suffix the
   newer one; warn.
6. **LoRA outlasts model deprecation** (base model retired) — LoRA marked
   incompatible; user prompted to retrain on current base.
7. **Cross-tenant LoRA sharing** — DISALLOWED. LoRAs encode tenant data
   indirectly; never shareable across tenants.
8. **Privacy: photos of real people in training data** — Warden + face-
   embedding denylist on training set submission; strict rules for child
   photos.
9. **LoRA degrades quality after retraining** — auto-rollback if vision-LLM
   score dropped > 15% vs prior; user notified.
10. **Concurrent train requests for same scope** — second request returns
    existing PENDING/RUNNING job rather than starting new.

## Errors

- `InsufficientTrainingDataError(ConfigError)`
- `LoraTrainingFailedError(ToolError)`
- `LoraQualityGateFailedError(ConfigError)` — non-fatal; job COMPLETED
  but not active
- `LoraIncompatibleBaseModelError(ConfigError)`
- `LoraTrainerUnavailableError(RoutingError)`

## Test surface

- Unit: training data curation per scope; caption generation invariants;
  trigger word generation; cost forecast formula.
- Integration (mock trainer): full job lifecycle PENDING→RUNNING→COMPLETED
  with quality gate; auto-rollback on degradation; LoRA application
  modifies generation request.
- Security: cross-tenant prevention; face denylist enforcement; bandit
  clean.
- Property: same training set + base model + trainer = same LoRA bytes
  (when trainer supports deterministic mode).

## Dependencies

- §04 generative (LoRA-aware models via LiteLLM)
- §22 preflight (training data quality gate)
- §31 cost & budget (forecast + gate)
- §23 versioning (rollback)
- §19 corrections + §20 learnings + §30 critics (auto-trigger signals)
- Provider APIs: Replicate, fal, Together
