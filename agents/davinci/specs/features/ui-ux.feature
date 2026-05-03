Feature: UI / UX
  Chat-led editor where the agent does ~90% and the user tweaks ~10%, with
  every tweak feeding the corrections pipeline. Cost gates inline; live
  draft thumbnails; dyslexia mode; keyboard-first.

  See ../16-ui-ux.md.

  Background:
    Given an authenticated user "alice" in tenant "acme"
    And alice has an open Document in the editor

  @p0 @critical
  Scenario: Three-pane shell (chat, document, inspector)
    When the editor opens
    Then the chat panel is on the left, document in the centre, inspector on the right
    And all three are resizable + collapsible

  @p0
  Scenario Outline: Direct manipulation primitives map to canvas actions
    When alice performs <gesture>
    Then the corresponding action <action> is invoked

    Examples:
      | gesture                          | action            |
      | click on a layer                  | layer.select      |
      | drag selected layer               | transform_move    |
      | corner-handle drag (with shift)   | scale-aspect-lock |
      | top-handle drag (with shift)      | rotate-snap-15    |
      | drag layer in panel               | reorder           |
      | drag asset onto canvas            | asset_insert      |
      | T key                             | new text layer    |
      | Del on selected                   | delete            |
      | Ctrl+D                            | duplicate         |
      | Ctrl+Z                            | undo              |
      | Ctrl+Shift+Z                      | redo              |

  @p0 @critical
  Scenario: Cost gate at < $0.10 fires inline button (no modal)
    Given a forecast cost of $0.04
    When alice clicks "Regenerate background"
    Then no modal is shown
    And the action runs immediately
    And the cost is logged

  @p0
  Scenario: Cost gate $0.10–$1 shows inline button with model dropdown
    Given a forecast cost of $0.40
    Then the regenerate button shows the cost
    And hovering reveals candidate models with costs and free-tier remaining

  @p0
  Scenario: Cost gate $1–$10 shows modal
    Given a forecast cost of $5.00
    When alice triggers the action
    Then a modal asks for approval
    And cancellation reverts no state

  @p0
  Scenario: Cost gate ≥ $10 requires typed confirmation
    Given a forecast cost of $25
    When alice triggers the action
    Then a modal asks for typed "yes"

  @p0 @critical
  Scenario: Plan-before-action for big requests
    Given alice asks "regenerate every page in this style"
    When the agent plans (≥ 3 layer mutations)
    Then the plan is presented as a checklist in chat
    And alice may accept, edit, or reject before any tool call fires

  @p0
  Scenario: Style-lock badge in doc header
    Given a Document with style_lock "warrior-knight v3"
    Then the doc header shows the lock badge with name + version
    And clicking it shows the lock card + drift score per page

  @p0
  Scenario: Page draft/proof dot indicators in layers panel
    Given a layer at draft tier
    Then the layer thumbnail in the panel shows a blue dot
    Given a layer at proof tier
    Then the layer thumbnail shows a green dot

  @p0
  Scenario: Pre-flight summary in doc header
    Given a Document with 3 WARN and 0 FAIL
    Then the doc header shows "OK • 3 warnings"
    And clicking opens the report

  @p0
  Scenario: Budget bar bottom-right shows spend + reset countdown
    Given alice has DAILY budget cap $5 and spent $2
    Then the budget bar shows 40% with a reset countdown

  @p0
  Scenario: Agent status live in chat header
    When the agent transitions states
    Then the chat header shows: idle → planning → generating → waiting on user

  @p0 @critical
  Scenario: WebSocket disconnect surfaces banner; reconnect reconciles
    Given a live WebSocket session
    When the connection drops
    Then the editor shows a banner
    And queued user actions buffer
    On reconnect:
    Then state reconciles via version_get

  @p0
  Scenario: Race: agent generates a layer while user edits it
    Given alice is editing layer L1 transform
    And the agent is regenerating L1's content
    When both apply
    Then alice's transform wins
    And the agent's content is adopted with the new transform

  @p0
  Scenario: User opens same Document in two tabs
    Given two open tabs editing the same Document
    Then the second tab is read-only by default
    And alice can promote the second tab to active editing (read-only badge clears)

  @p0
  Scenario Outline: Backend errors surface user-friendly messages
    When backend raises <error>
    Then the editor surfaces <user_message>

    Examples:
      | error                       | user_message                                                     |
      | BudgetExceededError         | You've reached your daily limit. Adjust budget?                 |
      | WardenBlockedError          | That image was flagged. Try a different one?                    |
      | GenerativeBackendError      | All generation models are busy. Retry?                          |
      | PreflightFailedError        | 3 issues to fix before exporting. View them?                    |
      | ConcurrentEditError         | Someone (or another tab) just edited this page. Reload?         |
      | DPILowError                 | Image is below print resolution. Upscale or accept lower quality? |

  @p0
  Scenario: Surfacing a critic-promoted Learning to chat
    Given Type Critic just promoted PREFER_FONT_FAMILY to Atkinson Hyperlegible
    Then chat shows "I noticed... apply across this book? [Yes][Just here][Don't ask again]"
    And clicking "Don't ask again" silences the rule, not the learning

  @p1
  Scenario: Reduced-motion mode disables draft thumbnail animations
    Given OS-level reduced-motion preference enabled
    Then thumbnails fade in without animation
