# 16 — UI / UX

**Status**: P0 / Phase 5. Depends on most engine specs.
**One-liner**: a chat-led editor where Da Vinci does ~90% and the user
tweaks ~10%, with every tweak feeding the corrections pipeline.

## Audience

A non-technical creator (designer-adjacent at most). Mental model is
"Canva-with-AI" not "Photoshop". Cares about: outcomes, speed, cost
visibility, undo, kid-friendly defaults.

## Shell

```
┌─ Chat (resizable) ──┬─ Document ──────────────────┬─ Inspector ─┐
│ Da Vinci:           │  ┌─────┬─────┬─────┬─────┐  │ Page 4      │
│ "Drafted 4 spreads" │  │ p1  │ p2  │ p3  │ p4  │  │ Layers:     │
│ [thumbnail strip]   │  └─────┴─────┴─────┴─────┘  │ ├ dragon    │
│                     │  ┌──────────────────────┐    │ ├ bg        │
│ User: "make dragon  │  │                      │    │ └ caption   │
│  bigger"            │  │     selected page    │    │             │
│                     │  │      live preview     │    │ Style lock  │
│ [accept]/[tweak]    │  │                      │    │ Brand kit   │
│                     │  └──────────────────────┘    │ Refs        │
│                     │  Toolbar: + text + shape ... │             │
│                     │  Cost gate: $0.04 [approve]  │             │
└─────────────────────┴──────────────────────────────┴─────────────┘
```

Three resizable columns. Inspector and chat collapsible. Document panel is
always primary.

## Modes

| Mode | When | Interaction |
|---|---|---|
| Wizard (§32) | First doc / new project | Conversational; modal overlay |
| Edit | Default after wizard / open document | Direct manipulation + chat |
| Preview | Toggle button | Print-view with bleed/safe-area guides; no chrome |
| Read-along | Children's book + audio (§27) | Page flip + narration playback |
| Compare | Two versions (§23) | Side-by-side renders; slider |

## Direct-manipulation primitives (canvas surface)

What she can do without typing in chat:

| Action | Affordance |
|---|---|
| Select layer | Click on canvas; ctrl-click for multi |
| Move | Drag selected; arrow keys for nudge |
| Scale | Corner handles; shift = aspect-lock |
| Rotate | Top handle; shift = snap 15° |
| Reorder | Drag in layers panel; right-click → forward/back |
| Show/hide | Eye icon in layers panel |
| Lock | Lock icon in layers panel |
| Delete | Del key on selected |
| Duplicate | Ctrl-D on selected |
| Copy/paste between pages | Ctrl-C / Ctrl-V |
| Reorder pages | Drag in page strip |
| Add text | Toolbar / T key; click on canvas to place |
| Add shape | Toolbar / shape submenu |
| Add asset | Drag from inspector's Assets pane |
| Undo / redo | Ctrl-Z / Ctrl-Shift-Z (cross-session via §23) |
| Pick colour | Eyedropper from inspector swatches |
| Fit to view | F key; double-click to focus on selected |

## Inspector tabs

| Tab | Contents |
|---|---|
| Page | print spec, page number, master, layout kind, background |
| Layers | tree with z-index, blend, opacity, mask presence, locked indicator |
| Selected layer | type-specific: text style + content / shape geometry / raster prompt + regen |
| Style lock | name, version, palette, drift indicator per page |
| Brand kit | palette swatches, fonts, logos; "apply to selection" |
| Assets | search/filter; characters / props / uploads tabs; drag onto canvas |
| Templates | tenant + bundled; "save current as template" button |
| History | timeline of versions; checkpoint button; revert / branch UI |
| Cost | live spend + budget bar; per-action forecast on hover |

## Chat panel

Chat is the agent's primary interaction surface. Patterns:

| Pattern | Example |
|---|---|
| Free request | "Make all dragons rounder" |
| Reference | "[layer thumbnail] this is too dark" |
| Plan response | Da Vinci proposes a multi-step plan as a checklist; user edits/accepts |
| Draft preview | Inline thumbnail + "approve" / "tweak" / "regenerate" buttons |
| Cost gate | Modal blocking action: "needs $0.12, approve?" |
| Learning surfaces | "Da Vinci learned: prefers Atkinson Hyperlegible — apply across book?" |

Chat is durable per Document (not session). Conversation auto-summarises old
turns when context budget tight (existing Stronghold pattern).

## Cost gate UX

Three states, depending on cost (§31 thresholds):

1. `< $0.10` → invisible; happens, surfaced post-action
2. `$0.10–$1` → inline button: `[Regenerate background] $0.04 ▾`
   - Hover shows model candidates + free-tier remaining
   - Click runs immediately, no modal
3. `$1–$10` → modal with summary + approve/cancel
4. `≥ $10` → modal requiring typed confirmation
5. `≥ $100` → blocked unless tenant admin grants

## Status indicators

| Indicator | Where | Meaning |
|---|---|---|
| Style-lock badge | Doc header | "Locked: warrior-knight v3" + drift score |
| Brand-kit badge | Doc header | "Acme Brand v2" |
| Page draft/proof | Layers panel | blue dot = draft, green = proof |
| Pre-flight summary | Doc header | OK / warnings / failures count |
| Budget bar | Bottom-right | spent/total with reset countdown |
| Agent status | Chat header | idle / planning / generating / waiting on user |
| Connection | Chat header | online / reconnecting (WebSocket) |

## Keyboard shortcuts

Standard set; chosen for muscle memory from Figma / Canva:

```
V          select tool
T          text
R          rectangle
O          ellipse
L          line
H          hand (pan)
Z / Z+Z    zoom in / out
F          fit
Cmd-A      select all on page
Cmd-D      duplicate
Cmd-G      group / ungroup
Cmd-Z      undo
Cmd-Shift-Z redo
Cmd-S      checkpoint
Cmd-E      export
Cmd-K      command palette / chat focus
[ / ]      send back / forward
Shift-[ / ] send to back / front
Arrow      nudge 1px
Shift-Arrow nudge 8px
```

## Accessibility (cross-ref §25)

- All UI text passes WCAG AA contrast at default theme
- All interactive elements reachable by keyboard
- Live regions announce agent status changes to screen readers
- Reduced-motion mode disables draft thumbnail animations
- High-contrast / dark mode toggle
- Zoom up to 400% without losing layout

## Surfacing learning

Whenever §20 promotes a learning, chat shows a one-line surface:

> "I noticed you've changed Comic Sans → Atkinson Hyperlegible 4 times.
> Apply across this book?  [Yes] [Just here] [Don't ask again]"

Action is undoable; "Don't ask again" silences the rule, not the learning.

## Component architecture (frontend)

Recommendation, not enforcement:
- **Stack**: Next.js (React) or SolidStart (Solid). Either is fine; React is
  the default for hire-ability.
- **Canvas**: `Konva.js` or `Pixi.js` for layer manipulation; Pillow renders
  on the server, frontend overlays a thin transform layer.
- **State**: Zustand or XState; XState if the wizard + cost-gate state
  machines get complex (likely they will).
- **Realtime**: WebSocket session protocol (existing Stronghold conduit)
  for: agent status, draft thumbnails, cost gates, version updates.
- **Telemetry**: existing Phoenix backend; UI emits client-side spans for
  interaction latency.

## Edge cases

1. **WebSocket disconnect mid-action** — UI shows banner; queued actions
   buffered; on reconnect, reconcile via version_get.
2. **Race: agent generates a layer while user edits it** — agent's update
   adopts user's transform; conflict on content surfaces an inline diff.
3. **User opens same Document in two tabs** — second tab read-only with
   "open here" button; concurrent edits are allowed but surfaced.
4. **Long generation (LoRA training, multi-page regen)** — progress bar in
   chat; user can navigate away; notification on completion.
5. **Chat history exceeds context** — conduit auto-summarises; UI shows a
   collapse marker.
6. **Browser refresh during wizard** — wizard resumes from latest step.
7. **Drag from external app** (file explorer image) — auto-asset_upload
   if Warden passes; otherwise rejected with clear reason.
8. **Touch / tablet input** — pinch-zoom, two-finger pan; supported but not
   the primary form factor in P0.

## Errors (UI surfacing)

The UI does not introduce new errors; it surfaces existing ones with
human-friendly explanations and a "what to do" suggestion.

| Backend error | UI surface |
|---|---|
| BudgetExceededError | "You've reached your daily limit. Adjust budget?" |
| WardenBlockedError | "That image was flagged. Try a different one?" |
| GenerativeBackendError | "All generation models are busy. Retry?" |
| PreflightFailedError | "3 issues to fix before exporting. View them?" |
| ConcurrentEditError | "Someone (or another tab) just edited this page. Reload?" |
| DPILowError | "Image is below print resolution. Upscale or accept lower quality?" |

## Test surface

- Component-level tests via React Testing Library (or equivalent)
- Visual regression via Chromatic / Percy on key screens
- E2E (Playwright) for: wizard happy path, cost gate flow, undo/redo,
  template apply, export
- A11y: axe-core lint on every screen; keyboard-only test for primary flows

## Dependencies

- Frontend project (separate repo / package): `stronghold-studio`
- Existing Stronghold API + WebSocket conduit
- All engine specs (referenced extensively)
