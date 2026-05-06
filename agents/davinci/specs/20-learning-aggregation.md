# 20 — Learning Aggregation

**Status**: P0 / Hyperagent phase. Turns corrections into learned behaviour.
**One-liner**: aggregate Corrections (§19) into promoted Learnings, scoped by
asset / document / user, with decay, contradiction resolution, and weight
floors.

## Problem it solves

A single correction is anecdote; patterns are wisdom. Aggregation extracts
patterns, promotes them to durable learnings consumed by future generation,
and decays them when not reinforced.

## Data model

```
Learning (frozen):                  # extends Stronghold's existing Learning
  id: str
  tenant_id: str
  user_id: str | None              # null for tenant-scope or document-scope
  document_id: str | None          # null for user/tenant scope
  asset_id: str | None             # for asset-scoped (character/prop) learnings
  scope: LearningScope             # cross-ref: USER | DOCUMENT | ASSET | TENANT
  rule_kind: LearningRuleKind
  rule_data: Mapping[str, Any]     # kind-specific
  confidence: float                # 0..1
  weight: float                    # 0..1; multiplied by confidence at apply time
  hit_count: int                   # supporting corrections
  last_reinforced_at: datetime
  created_at: datetime
  pinned: bool = False             # immune to decay
  contradicts: tuple[str, ...] = () # ids of conflicting learnings
  evidence: tuple[str, ...] = ()    # correction ids supporting this

LearningRuleKind (StrEnum):
  PREFER_FONT_FAMILY                # rule_data: {family, scope_constraint}
  PREFER_PALETTE_COLOR              # rule_data: {color, role}
  PREFER_FONT_WEIGHT                # rule_data: {weight, role}
  PREFER_TEXT_TRANSFORM             # rule_data: {transform, role}
  PREFER_LAYOUT                     # rule_data: {layout_kind, doc_kind}
  PREFER_ASSET_VARIANT              # rule_data: {asset_id, variant_field, value}
  PREFER_PROMPT_SUFFIX              # rule_data: {suffix_terms}
  PREFER_BLEND_MODE                 # rule_data: {mode, layer_kind}
  AVOID_FONT_FAMILY                 # rule_data: {family}
  AVOID_PALETTE_COLOR               # rule_data: {color}
  AVOID_PROMPT_TERMS                # rule_data: {terms}
  CHARACTER_REFINEMENT              # rule_data: {trait_field, value}
  STYLE_LOCK_DRIFT                  # rule_data: {axis, direction}
  REQUIRES_BRAND_KIT_USE            # rule_data: {kit_id}
  REQUIRES_ACCESSIBILITY_FONT       # rule_data: {context}

LearningScope (StrEnum):
  TENANT
  USER
  DOCUMENT
  ASSET
```

## Promotion rules

Aggregation is a periodic + event-driven job:

```
def aggregate(window: timedelta = 1day):
    for user in active_users:
        recent = correction_store.list(user_id=user.id, since=window)
        recent = [c for c in recent if not c.reverted]
        clusters = cluster_corrections(recent)
        for cluster in clusters:
            decision = decide_promotion(cluster)
            if decision.promote:
                upsert_learning(...)
            if decision.demote_existing:
                decay_learning(...)
```

Promotion thresholds:

| Pattern | Threshold | Promoted scope |
|---|---|---|
| Same kind/value ≥ 3 times across documents in 30d | confidence 0.7 | USER |
| Same kind/value ≥ 2 times in same document | confidence 0.7 | DOCUMENT |
| Same change on same character_asset_id | confidence 0.8 | ASSET |
| Brand-kit colour applied where agent used non-brand | confidence 0.9 | DOCUMENT (hard rule) |
| Reverted within 60s ≥ 2 times | confidence 0.6 | NEGATIVE (avoid) |
| Same change but inverse on different docs | (no learning; contextual) | — |

Confidence updates on each new supporting correction:

```
new_confidence = 1 - (1 - prior_confidence) * (1 - per_evidence_strength)
```

Bounded to [0, 1].

## Application

When Da Vinci builds a generation prompt or system prompt, the learning
store is queried for applicable learnings:

```
def apply_learnings(action_context):
    # Query relevance: scope match + rule kind applicability
    candidates = learning_store.find(
        scope=USER, user_id=ctx.user.id,
        rule_kinds=[FONT, PALETTE, PROMPT_SUFFIX, ...],
    )
    for c in candidates:
        # rule_data → prompt suffix or system message addition
        injected = render_for_action(c.rule_data, action_context)
        prompt_builder.add_directive(injected, weight=c.confidence * c.weight)
    return prompt_builder.build()
```

Injected directives carry weight; conflicting directives use weighted vote.

## Decay

Learnings without reinforcement decay weight over time:

```
weight = max(min_floor, weight * decay_factor**(days_since_reinforcement))
```

| Factor | Default | Reason |
|---|---|---|
| `decay_factor` per day | 0.99 | ~half-life 70 days |
| `min_floor` (regular) | 0.0 | full decay possible |
| `min_floor` (REQUIRES_ACCESSIBILITY_FONT) | 0.5 | safety floor |
| `min_floor` (REQUIRES_BRAND_KIT_USE) | 0.3 | brand floor |
| `pinned` | weight constant 1.0 | hand-pinned by user |

Reinforcement (a new supporting correction) resets `last_reinforced_at` and
multiplies weight by 1.1 (capped at 1.0).

## Contradiction resolution

When a new learning contradicts an existing one (rule_data inverts):
- If new evidence stronger → demote old (weight halved); link via
  `contradicts`
- If old has more accumulated evidence → reject new
- If neither dominates → ASK USER via chat surface ("you've used both serif
  and sans on different books — which should I default to?")

## Critic-aware aggregation (cross-ref §30)

Each Critic sub-agent (TYPE, COLOR, COMPOSITION, PROMPT, PROP) consumes
relevant subsets of corrections:

| Critic | Watches kinds | Promotes rule kinds |
|---|---|---|
| Type | TEXT_EDIT, FONT_CHANGE, EFFECT_ADD on text | PREFER_FONT_FAMILY, PREFER_FONT_WEIGHT, PREFER_TEXT_TRANSFORM |
| Color | COLOR_CHANGE | PREFER_PALETTE_COLOR, AVOID_PALETTE_COLOR, REQUIRES_BRAND_KIT_USE |
| Composition | TRANSFORM_*, REORDER, LAYOUT_APPLY | PREFER_LAYOUT |
| Prompt | REGEN_WITH_NEW_PROMPT | PREFER_PROMPT_SUFFIX, AVOID_PROMPT_TERMS |
| Prop | REPLACE_PROP, ASSET-scoped corrections | CHARACTER_REFINEMENT, PREFER_ASSET_VARIANT |

Critics aggregate independently; learnings from each are tagged with
`critic_id` for traceability.

## API surface

| Action | Args | Returns |
|---|---|---|
| `learning_list` | `[scope, user_id, document_id, asset_id, rule_kind]` | tuple[Learning, ...] |
| `learning_get` | `learning_id` | Learning |
| `learning_pin` | `learning_id, pinned: bool` | Learning |
| `learning_decay_run` | (cron, internal) | summary |
| `learning_aggregate_run` | (cron, internal) | summary |
| `learning_apply_preview` | `action_context` | injected directives that WOULD apply |
| `learning_user_summary` | `user_id` | human-readable summary for UI surface |
| `learning_silence` | `learning_id` | Learning with weight 0 + pinned (won't return) |

## Edge cases

1. **Aggregator runs while user is editing** — append-only; user actions
   continue uninterrupted.
2. **User deletes account / data** — all corrections + learnings purged;
   tenant-scoped corrections from other users in same tenant unaffected.
3. **Promoted learning surfaced to user immediately** — chat one-line
   notification; user can `learning_silence` from that surface.
4. **Conflicting learnings of same scope from different critics** — Critic
   precedence: COLOR + TYPE > COMPOSITION > PROMPT (composition is most
   contextual).
5. **Cross-document learning applied where user wants per-doc behaviour** —
   user can override per-doc; that override becomes a DOCUMENT-scope
   learning that supersedes USER scope at apply time.
6. **Bulk corrections during smart-resize** (§14) — counted as single
   batch correction event for aggregation.
7. **Aggregator processing very long history** — paginated; checkpoint;
   resumable.
8. **User has very few corrections** — aggregator no-op until threshold;
   no spurious learnings.
9. **Negative learnings stack with positive** — both apply; net direction
   wins; surface-able.
10. **Learning data integrity** — every learning links to its supporting
    Correction ids; deletion of corrections requires recomputation.

## Errors

- `LearningStorageError(StrongholdError)`
- `LearningContradictionUnresolvedError(StrongholdError)` — surfaces UI ask

## Test surface

- Unit: every promotion rule given matching corrections produces expected
  Learning; decay math; weight floors honoured; contradiction detection.
- Integration: feed 100 fixture corrections → expected learnings; apply at
  prompt-build time injects predicted suffix; cross-tenant isolation.
- Property: aggregating subset twice = aggregating once (idempotent on
  same input window).
- Performance: aggregator processes 10k corrections in < 10 s.

## Dependencies

- existing `LearningStore` protocol (consumer; this spec extends rule kinds)
- §19 corrections (input)
- §30 critics orchestration (independent aggregators per critic)
- §09 style lock (consumer of style-related learnings)
