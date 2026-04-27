# 32 — Onboarding & First Document Wizard

**Status**: P0 / Trust phase. First-time-user-experience for non-technical users.
**One-liner**: a chat-driven wizard that turns "I want to make a book about
my daughter and her dragon" into a partly-drafted Document with picked
template, brand kit, and first cover draft.

## Problem it solves

A blank canvas is paralysing. Non-technical users need a *conversational*
on-ramp: "tell me what you want", agent asks 3-5 clarifying questions,
proposes a template, generates a first draft, then hands off to the editor.
This is the moment the user decides whether to keep using Da Vinci.

## Goals

- < 5 minutes from sign-in to first generated cover draft
- Zero technical decisions from the user (DPI, page count, fonts)
- Establish: brand kit, style direction, first character, first prop
- Set the user's first budget cap (so cost gates are calibrated)
- Surface every ongoing concept (style lock, character refs, brand kit) so
  the user sees them before they encounter them in the editor

## Wizard flow

```
1. WELCOME             "Hi! What would you like to make?"
   → opt: picture book / poster / infographic / video overlay / open canvas

2. INTENT              "Tell me about your project — a sentence or two."
   → free text → vision-LLM extracts: subject, audience, mood, length

3. CLARIFY             agent asks 1-3 follow-ups based on extraction
   → e.g. "Is this for ages 3-5 or 5-7?" / "Read-along or just printed?"
                   / "Cover only, or full 32 pages?"

4. STYLE BRIEF         agent proposes 3 style mood-board thumbnails
   → user picks one (or uploads inspiration); style lock seed established

5. CHARACTER (book)    "Who's the main character?"
   → Da Vinci generates 4 character ref candidates → user picks one
   → saved to character library with name

6. BRAND KIT           agent extracts palette + suggested fonts from style brief
   → user accepts or tweaks color swatches

7. BUDGET              "How much would you like to spend on this book?
                        Suggested: $5 daily cap / $20 lifetime cap."
   → user sets thresholds; defaults are conservative

8. FIRST DRAFT         agent generates cover (proof tier) using locked style + char
   → user sees first draft + handoff to editor
```

## Data model

```
WizardSession (frozen):
  id: str
  user_id: str
  tenant_id: str
  started_at: datetime
  current_step: WizardStep
  collected: WizardCollected
  outcome: WizardOutcome | None        # set when finished
  abandoned_at: datetime | None        # if user bails

WizardStep (StrEnum):
  WELCOME | INTENT | CLARIFY | STYLE_BRIEF | CHARACTER | BRAND_KIT
  | BUDGET | FIRST_DRAFT | DONE

WizardCollected (frozen):
  doc_kind: DocumentKind | None
  intent_text: str = ""
  audience_age_band: AgeBand | None
  language: str = "en"
  page_count: int | None
  style_brief_choice: int | None       # 0-2 of presented thumbnails
  style_seed_image_blob_id: str | None # uploaded inspiration
  character_choice: int | None
  character_ref_id: str | None
  brand_kit_id: str | None
  budget_daily_usd: Decimal | None
  budget_total_usd: Decimal | None

WizardOutcome (frozen):
  document_id: str
  brand_kit_id: str
  style_lock_id: str
  character_ref_ids: tuple[str, ...]
  estimated_cost_usd: Decimal          # spent so far
  duration_seconds: int
```

## API surface

| Action | Args | Returns |
|---|---|---|
| `wizard_start` | `user_id` | WizardSession id |
| `wizard_advance` | `session_id, step_input` | next step + payload |
| `wizard_back` | `session_id` | previous step + collected |
| `wizard_skip` | `session_id` | skip current step (some steps optional) |
| `wizard_abandon` | `session_id` | mark session abandoned |
| `wizard_resume` | `user_id` | latest unfinished session, if any |

## UI surface

- Modal-overlay wizard on first sign-in; dismissable to "skip — open blank
  canvas" (advanced users)
- Progress bar with step names
- Each step is one chat-style exchange (Da Vinci asks, user answers)
- "Why are you asking this?" expandable per step

## Edge cases

1. **User bails mid-wizard** — session marked abandoned, partial Collected
   discarded after 24 hrs unless user resumes. Generated assets (character ref,
   draft) retained per normal blob retention.
2. **User uploads inappropriate inspiration** — Warden scans uploads;
   inappropriate content rejected with kid-safe explanation.
3. **Free tier exhausted during wizard** — gate before each gen; user sees
   "this generation needs $0.04, would you like to add a budget?"
4. **Vision-LLM fails to extract intent** — fall back to direct
   multi-choice questions (template gallery).
5. **Style brief thumbnails all rejected** — let user upload up to 3
   inspiration images; agent re-proposes.
6. **Character brief returns no usable refs** — re-prompt with simplified
   description; offer to skip to "I'll define the character later."
7. **Wizard completes but first draft fails** — log error, hand off to
   editor with the empty Document; chat panel apologises and offers retry.
8. **User has previous Documents** — wizard offers "Start from a previous
   book" path that clones a finished Document as a template.
9. **Returning user with same project type** — wizard auto-fills brand kit
   and budget defaults from previous run.
10. **Multi-language UX** — wizard language follows user locale; intent
    extraction language follows user input language; output language is
    user-chosen.

## Privacy / safety

- All wizard inputs land in tenant-scoped DB; no aggregation across tenants
- Free-text intent stored only as long as the WizardSession or Document
  exists; not used for cross-user training
- Children's content gets stricter Warden settings
- Content involving real names/photos of minors triggers an extra consent gate

## Errors

- `WizardSessionNotFoundError`
- `WizardStepUnknownError(ConfigError)`
- `WizardInputInvalidError(ConfigError)`

## Test surface

- Unit: state machine — every step transitions correctly with valid input;
  invalid input loops back; back/skip behaviour.
- Integration: full happy-path wizard produces a Document, BrandKit,
  StyleLock, CharacterRef in DB; abandoned session expires.
- Security: tenant scope enforced; Warden scans on uploads.
- UX (`@manual`): time-to-first-draft < 5 minutes for new user (recorded as
  metric, not assert).

## Dependencies

- vision-LLM endpoint (existing) for intent extraction + style brief
  generation
- §11 templates, §17 template authoring, §18 asset library, §09 style lock,
  §31 cost & budget all called by the wizard
