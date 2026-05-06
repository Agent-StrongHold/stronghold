Feature: LoRA / fine-tuning
  Train per-document/character/style/user LoRAs on accepted proof renders;
  switch generation to base + LoRA for cheaper, more consistent output.

  See ../21-lora.md.

  Background:
    Given an authenticated user "alice" in tenant "acme"
    And a tenant-allowed LoRA trainer (replicate/flux)

  @p0 @critical
  Scenario: Submit a DOCUMENT-scope LoRA training job
    Given a Document with at least 20 proof-tier layers and a style lock
    When alice lora_train scope=DOCUMENT, scope_id=D1
    Then a LoraTrainingJob exists with status=PENDING
    And training_data lists the curated blob ids
    And forecast_cost_usd > 0

  @p0
  Scenario: Insufficient training data raises
    Given a Document with only 5 proof layers
    When alice lora_train scope=DOCUMENT
    Then InsufficientTrainingDataError is raised

  @p0
  Scenario: Cost gate required before submission
    Given a forecast above auto-approve threshold
    When lora_train is invoked
    Then ApprovalRequiredError is raised
    And the user must approve via §31 cost gate

  @p0
  Scenario: Job lifecycle PENDING → RUNNING → COMPLETED
    Given a submitted LoraTrainingJob
    When the trainer transitions states
    Then status updates per webhook
    And actual_cost_usd, actual_duration_minutes, result_lora_id are set on COMPLETED

  @p0 @critical
  Scenario: Quality gate fails LoRA stays inactive
    Given a COMPLETED job whose vision-LLM quality score < threshold
    Then status is COMPLETED
    But the LoRA is NOT auto-active
    And LoraQualityGateFailedError is recorded

  @p0
  Scenario: Active LoRA injects trigger word at generation
    Given an active CHARACTER LoRA "<lily-dragon>"
    When alice generates a layer mentioning Lily
    Then the prompt includes "<lily-dragon>"
    And the request is routed to a base model that supports the LoRA

  @p0
  Scenario: Multiple active LoRAs (doc + character + style) combined per provider cap
    Given doc, character, and style LoRAs all active
    When generation runs
    Then up to the provider's cap LoRAs are sent
    And a warning surfaces if more LoRAs requested than supported

  @p0
  Scenario: Trigger-word collision auto-suffixes the newer LoRA
    Given an existing LoRA with trigger "<warrior>"
    When a new LoRA is trained that would also use "<warrior>"
    Then the newer LoRA gets a suffixed trigger (e.g. "<warrior-2>")

  @p0
  Scenario: Auto-rollback if new LoRA degrades quality > 15%
    Given an active LoRA with sample quality 0.82
    And a newly trained LoRA with quality 0.65
    When the new LoRA is activated
    Then auto-rollback restores the prior LoRA
    And the user is notified

  @p0 @security
  Scenario: Cross-tenant LoRA access denied
    Given a LoRA owned by tenant "globex"
    When alice (acme) tries lora_get
    Then PermissionDeniedError is raised

  @p0 @security
  Scenario: Photo of real child in training data triggers extra-strict review
    Given training data containing real child photos
    When the trainer is submitted
    Then Warden + face-embedding denylist enforce strict checks
    And submission is blocked unless extra consent confirmed

  @p0
  Scenario: Concurrent train requests for same scope return existing job
    Given a PENDING LoraTrainingJob for scope=DOCUMENT, D1
    When alice lora_train again for D1
    Then the existing job is returned (no duplicate)

  @p0
  Scenario: LoRA pinned is not auto-deleted by retention
    Given a Lora pinned=true
    When retention sweep runs after 365 days
    Then the LoRA is still present

  @p0
  Scenario: lora_compare renders side-by-side previews
    Given two LoRAs and a sample prompt
    When alice lora_compare A B prompt
    Then a side-by-side preview render is produced

  @p1
  Scenario: Auto-train trigger fires when corrections threshold crossed
    Given alice has accumulated 30 high-confidence character corrections
    When the auto-train cron runs
    Then a CHARACTER scope LoraTrainingJob is created in PENDING
    And alice receives a notification with cost preview
