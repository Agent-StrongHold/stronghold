# 30 — Critics Orchestration

**Status**: P1 / Hyperagent phase. Decomposes Da Vinci's "self-improvement"
into specialist sub-agents.
**One-liner**: per-concern Critics (Type, Color, Composition, Prompt, Prop)
each consume corrections, refine their domain-specific micro-models, and
expose `style_hint() → str` to the prompt builder.

## Problem it solves

A monolithic "Da Vinci learns" agent scales poorly: corrections about font
choice get tangled with corrections about composition, signals dilute,
debugging is hopeless. Decomposing into focused critics gives each one a
clean input stream, a clean output, and a clear domain.

This is the same Artificer pattern Stronghold already uses (planner / coder
/ reviewer / debugger sub-agents).

## Critics

```
Critic (frozen):
  id: str
  name: CriticName
  watches: tuple[CorrectionKind, ...]    # subscriptions
  promotes: tuple[LearningRuleKind, ...] # produces
  precedence: int                         # tie-breaker; lower = higher precedence
  description: str

CriticName (StrEnum):
  TYPE                  # typography
  COLOR                 # palette + brand kit adherence
  COMPOSITION           # layout + balance + alignment
  PROMPT                # generative prompt patterns
  PROP                  # asset/character refinement
  ACCESSIBILITY         # WCAG / age-band / dyslexia
  COST                  # learns user's cost preferences (opt-in)
```

## Critic responsibilities

### Type Critic

| Watches | Promotes |
|---|---|
| TEXT_EDIT, FONT_CHANGE, EFFECT_ADD/REMOVE on text layers | PREFER_FONT_FAMILY, PREFER_FONT_WEIGHT, PREFER_TEXT_TRANSFORM, PREFER_BLEND_MODE on text |

Examples:
- "User swaps Comic Sans → Atkinson Hyperlegible 4 times → REQUIRES_ACCESSIBILITY_FONT"
- "User adds drop_cap on every chapter start → PREFER_LAYOUT chapter-start with drop cap"
- "User raises body size_px in early-reader books → PREFER_FONT_WEIGHT/SIZE for age band"

### Color Critic

| Watches | Promotes |
|---|---|
| COLOR_CHANGE | PREFER_PALETTE_COLOR, AVOID_PALETTE_COLOR, REQUIRES_BRAND_KIT_USE |

Examples:
- "User swaps generated colour to brand kit value 3+ times → REQUIRES_BRAND_KIT_USE for that document kind"
- "User repeatedly adds a warm accent colour to cool-toned generations → palette refinement"

### Composition Critic

| Watches | Promotes |
|---|---|
| TRANSFORM_MOVE, TRANSFORM_SCALE, TRANSFORM_ROTATE, REORDER, LAYOUT_APPLY | PREFER_LAYOUT |

Examples:
- "User shifts character to right-of-centre repeatedly → composition heuristic for this character"
- "User changes ART_WITH_BODY → ART_WITH_CAPTION on intro pages → layout preference per page kind"

### Prompt Critic

| Watches | Promotes |
|---|---|
| REGEN_WITH_NEW_PROMPT | PREFER_PROMPT_SUFFIX, AVOID_PROMPT_TERMS |

Examples:
- "User adds 'soft watercolour' to many regen prompts → suffix candidate"
- "User removes 'photorealistic' frequently → AVOID_PROMPT_TERMS"

### Prop Critic

| Watches | Promotes |
|---|---|
| REPLACE_PROP, REPLACE_CHARACTER, asset-scoped TRANSFORM_*  | CHARACTER_REFINEMENT, PREFER_ASSET_VARIANT |

Examples:
- "User repeatedly increases dragon's eye size → CharacterRefinement(eye_size=larger)"
- "User picks the same alternate prop in similar contexts → variant preference"

### Accessibility Critic

| Watches | Promotes |
|---|---|
| FONT_CHANGE → accessibility-flagged, COLOR_CHANGE → contrast issues, ALT_TEXT_EDIT | REQUIRES_ACCESSIBILITY_FONT, brand-kit palette flagged colour-blind safe |

These learnings get min_floor 0.5 by default (don't decay easily).

### Cost Critic (opt-in)

| Watches | Promotes |
|---|---|
| Cost-gate approvals/rejections, model selection overrides | PREFER_DRAFT_TIER, AVOID_MODEL pattern |

Disabled by default — learning from cost decisions feels invasive. Opt-in
per user.

## Orchestration

Critics run independently:

```
def critics_aggregate_run(window):
    for critic in active_critics:
        relevant = correction_store.list(
            since=window,
            kinds=critic.watches,
        )
        clusters = cluster(critic, relevant)
        for cluster in clusters:
            decision = critic.decide(cluster)
            if decision.promote:
                learning_store.upsert(
                    Learning(critic_id=critic.id, ...)
                )
```

No critic depends on another's output (decoupled). They share the
correction stream and the learning store.

## Application priority

When Da Vinci builds a prompt and multiple learnings apply, conflicts
resolved by `precedence`:

| Critic | Precedence (lower = higher) |
|---|---|
| ACCESSIBILITY | 0 |
| COLOR (REQUIRES_BRAND_KIT_USE) | 1 |
| TYPE | 2 |
| PROP | 3 |
| COMPOSITION | 4 |
| PROMPT | 5 |
| COST | 6 |

Within a critic, learnings are weighted by `confidence × weight`.

## Critic configuration

Per-tenant or per-user:

```
CriticConfig (frozen):
  critic_name: CriticName
  enabled: bool
  min_evidence_threshold: int = 3
  decay_factor: float = 0.99
  custom_weights: Mapping[str, float] = {}
```

Default: all enabled except COST.

## Surfacing critic learnings to UI

When a critic promotes a learning, UI shows a one-line surface (cross-ref
§16):

> "Type Critic learned: prefers Atkinson Hyperlegible body. Apply across this
>  book? [Yes] [Just here] [Don't ask again]"

The surface includes the critic name so the user understands the source.

## API surface

| Action | Args | Returns |
|---|---|---|
| `critic_list` | `[user_id]` | tuple[Critic + CriticConfig, ...] |
| `critic_enable` | `critic_name, enabled` | CriticConfig |
| `critic_explain` | `critic_name, learning_id` | "Promoted because ..." |
| `critic_run` | (cron, internal) | per-critic summary |

## Edge cases

1. **Critic promotes a learning that conflicts with another critic** —
   precedence wins; the lower-precedence critic's learning gets `weight ×
   0.5` and contradicts entry.
2. **Critic disabled mid-flight** — already-promoted learnings remain;
   future aggregation skipped.
3. **Critic with bug produces noise** — learnings can be silenced
   wholesale per critic ("clear all TYPE learnings").
4. **New critic added** — backfills against history within window; flagged
   as "new" in UI.
5. **User opts out of critic learning** — `enabled=false`; capture
   continues for §21 LoRA training (which doesn't depend on learnings).
6. **Cross-tenant critic sharing** — DISALLOWED. Each tenant's critics
   train on their own corrections only.
7. **Critic that observes nothing** — over time, weight floor 0; if
   floor != 0, surfaces "no signal" warning to admin.

## Errors

- `CriticNotFoundError`
- `CriticConfigInvalidError(ConfigError)`

## Test surface

- Unit: each Critic class subscribes only to its kinds; clustering function;
  promotion rules.
- Integration: a fixture stream of 50 corrections produces expected
  learnings per critic; precedence tie-breaks correctly.
- Property: critic outputs are deterministic given same inputs.
- Security: tenant isolation; per-user opt-out honoured.

## Dependencies

- §19 corrections (input)
- §20 learning aggregation (output via shared store)
- §16 UI/UX (surfacing)
- existing `LearningStore` protocol
