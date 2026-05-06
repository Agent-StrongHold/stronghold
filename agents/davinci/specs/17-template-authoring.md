# 17 — Template Authoring

**Status**: P0 / Document phase. The "save as template" loop.
**One-liner**: any finished Document or Page can become a reusable Template
via a wizard that marks slots, lockable layers, and parametric prompts.

## Problem it solves

Bundled templates can't cover every project. Once your wife has made one
great picture book cover, she should be able to "save as template" and reuse
that structure for all future books — with her name, character, and brand
kit slotting in.

## Authoring flow

```
1. SOURCE          Pick a Page or whole Document as the source.
2. SCOPE           Whole-document template (multi-page) or single-page?
3. SLOT MARKING    For each layer: mark as LITERAL (copy) | PLACEHOLDER (slot)
                                             | PARAMETRIC (regen with template prompt)
                                             | LOCKED (immutable in instances)
4. VARIABLE        For each PLACEHOLDER/PARAMETRIC: define a variable
                   - id, display_name, required, type, default
5. PROMPT TEMPLATE For PARAMETRIC: write the prompt with {{variable}} insertion
                   - Da Vinci proposes the template based on the source layer's
                     original prompt
6. BRAND KIT       Decide: lock to source's brand kit, or swappable
7. STYLE LOCK SEED Decide: lock to source's style, or swappable
8. METADATA        Name, category, thumbnail (auto-pick from source), tags
9. PUBLISH         Save to tenant library; optional share with team
```

The wizard is conversational + side-panel checkbox-driven, mirroring §32.

## Data model

Template authoring produces a Template (data structure in §11). This spec
covers the *authoring state*:

```
TemplateAuthoringSession (frozen):
  id: str
  user_id: str
  tenant_id: str
  source_document_id: str
  source_page_id: str | None        # null = whole doc
  current_step: AuthoringStep
  marked_layers: Mapping[str, LayerMarking]
  variables: tuple[TemplateVariable, ...]
  brand_kit_locked: bool
  style_lock_locked: bool
  draft_template: Template | None    # current snapshot of the in-progress template

LayerMarking (frozen):
  layer_id: str
  intent: LayerIntent       # LITERAL | PLACEHOLDER | PARAMETRIC | LOCKED
  variable_id: str | None    # for PLACEHOLDER, PARAMETRIC
  prompt_template: str = "" # for PARAMETRIC
  placeholder_type: PlaceholderType | None

AuthoringStep (StrEnum):
  SOURCE | SCOPE | SLOT_MARKING | VARIABLE | PROMPT_TEMPLATE
  | BRAND_KIT | STYLE_LOCK_SEED | METADATA | PUBLISH | DONE

LayerIntent (StrEnum):
  LITERAL          # copy as-is
  PLACEHOLDER      # empty slot, instance fills
  PARAMETRIC       # regenerate from prompt_template
  LOCKED           # copy as-is, locked from edits in instances
```

## Auto-suggestion for slot marking

To save your wife from labelling 30 layers by hand, Da Vinci proposes
markings based on layer kind + content:

| Source layer | Proposed intent | Reason |
|---|---|---|
| Text layer with the doc title | PLACEHOLDER (TEXT_TITLE) | matches Document.metadata.title |
| Text layer with author byline | PLACEHOLDER (TEXT_BYLINE) | matches Document.metadata.author |
| Text layer with body content | PLACEHOLDER (TEXT_BODY) | varies per book |
| Background generated layer | PARAMETRIC | with prompt_template = original prompt with subject swapped to {{subject}} |
| Character generated layer | PARAMETRIC | prompt with character description as {{character}} |
| Logo layer | LITERAL or LOCKED if linked to brand kit | depends on intent |
| Frame / decoration shape | LOCKED | structural |
| Page number text | LITERAL | structural; page furniture handles re-numbering |

The user accepts or overrides per layer.

## Prompt template construction

For PARAMETRIC layers, Da Vinci proposes a prompt template:

```
Original prompt: "a smiling 5-year-old girl with curly red hair holding a teddy bear, watercolour, soft light"
            ↓
Proposed template: "a smiling {{age}}-year-old {{character_kind}} with {{hair_description}}
                    holding a {{prop}}, {{style.rendering}}, {{style.lighting}}"
            ↓
Variables inferred:
  age (INT, required, default=5)
  character_kind (ENUM[girl, boy, child], required, default=girl)
  hair_description (STR, required, default="curly red hair")
  prop (STR, required, default="teddy bear")
```

The user can edit the proposed template before publishing.

## Variable validation

Each variable's type drives its UI in template_apply (§11):
- STR → text field with optional default
- INT → spinbox with optional min/max
- COLOR → swatch picker (defaults from brand kit)
- IMAGE → upload + character library + asset library picker
- ENUM → dropdown

Templates with unbound `{{var}}` references in prompt_template are rejected
at publish.

## Publishing flow

```
def publish_template(session) -> Template:
    validate_session(session)        # all required slots have variables
                                     # all prompt_templates parse cleanly
                                     # thumbnail set
    template = build_template_from_session(session)
    # default trust tier:
    #   - admin user → T2
    #   - regular user → T3 (user-created, AI-reviewed)
    template.trust_tier = T3
    template.provenance = USER
    save(template, scope=tenant)
    audit_entry("template_published", template.id, user_id)
    return template
```

Sharing across team / publishing to a marketplace (§29) is a separate flow.

## Versioning

Templates are versioned (separate from §23 document versioning):
- Each `publish` creates a new version
- Documents instantiated from a template record `template_id` + `template_version`
- Updating a template never retroactively changes existing instances

## API surface

| Action | Args | Returns |
|---|---|---|
| `template_authoring_start` | `source_document_id, [source_page_id]` | session id |
| `template_authoring_advance` | `session_id, step_input` | session |
| `template_authoring_mark_layer` | `session_id, layer_id, intent, [variable_id]` | session |
| `template_authoring_set_variable` | `session_id, variable` | session |
| `template_authoring_preview` | `session_id, sample_variables` | rendered Document |
| `template_authoring_publish` | `session_id, name, category, tags` | Template |
| `template_authoring_abandon` | `session_id` | (session deleted) |

## Edge cases

1. **Source has dynamic content** (regenerated multiple times during editing)
   — only the latest version of each layer enters the template; history is
   not.
2. **Variable referenced in prompt but not declared** — publish blocked with
   list of missing declarations.
3. **PARAMETRIC layer with prompt that doesn't parameterize** — author can
   leave it; instance gets identical generation each time (warn at publish).
4. **PLACEHOLDER but no variable definition** — validation error.
5. **Two layers reference the same variable id** — fine; instance fills both
   from the same value.
6. **Source document has style lock not seeded into template** — warn user;
   instances will lack consistency.
7. **Source uses tenant-only fonts/assets** — template publish records
   asset references; instance must resolve them in the same tenant.
8. **Publishing to T2 requires admin** — enforced by Stronghold trust system.
9. **Template author later deletes a referenced asset** — instances retain
   their copy; template apply fails for new instances with clear error.
10. **Renaming a variable** — bumps template version; old instances keep
    their bindings; new instances see the new name.

## Errors

- `TemplateAuthoringSessionNotFoundError`
- `TemplateAuthoringValidationError(ConfigError)` — publish blocked
- `TemplatePromptTemplateError(ConfigError)` — bad placeholder syntax

## Test surface

- Unit: each AuthoringStep transitions correctly; LayerMarking validation;
  prompt_template parses with all required variables.
- Integration: full author flow on a 3-layer Page → publishable Template;
  published Template applies cleanly via §11.
- Security: tenant scope enforced on publish; trust tier defaults correct;
  audit entry recorded.

## Dependencies

- §02, §11, §22 preflight (validate before publish), §23 versioning
