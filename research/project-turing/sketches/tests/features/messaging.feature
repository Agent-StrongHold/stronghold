Feature: Gated SMS Messaging via SignalWire

  Tess sends text messages to whitelisted contacts when she has something
  worth saying. Messages are gated by contact allowlist, daily limits, and
  allowed-hours windows. All sends are logged to the DB.

  Background:
    Given a messaging provider with contacts:
      | id     | name  | phone         | allowed | max_daily | hours  |
      | blake  | Blake | +15551234567  | true    | 3         | 8-22   |
      | alice  | Alice | +15559876543  | false   | 1         | 9-20   |
      | bob    | Bob   | +15555551234  | true    | 0         | 0-24   |

  # --- Contact gating ---

  Scenario: MSG-1: Send to allowed contact succeeds
    Given current hour is 14
    When I send "Hey, I figured out something cool about X" to "blake"
    Then the message is sent via SignalWire
    And daily_count for "blake" is 1
    And outbound_messages has 1 row

  Scenario: MSG-2: Send to unknown contact is rejected
    When I send "Hello" to "unknown-person"
    Then ContactNotAllowed is raised
    And no SignalWire API call is made

  Scenario: MSG-3: Send to disallowed contact is rejected
    When I send "Hello" to "alice"
    Then ContactNotAllowed is raised
    And no SignalWire API call is made

  # --- Daily limit ---

  Scenario: MSG-4: Daily limit blocks excess messages
    Given current hour is 14
    And 3 messages already sent to "blake" today
    When I send "One more thing" to "blake"
    Then DailyLimitExceeded is raised

  Scenario: MSG-5: Zero daily limit blocks all messages
    Given current hour is 12
    When I send "Hey" to "bob"
    Then DailyLimitExceeded is raised

  # --- Allowed hours ---

  Scenario: MSG-6: Message blocked outside allowed hours
    Given current hour is 23
    When I send "Can't sleep?" to "blake"
    Then OutsideAllowedHours is raised

  Scenario: MSG-7: Message allowed during allowed hours
    Given current hour is 8
    When I send "Good morning" to "blake"
    Then the message is sent via SignalWire

  # --- Message body ---

  Scenario: MSG-8: Message body is truncated to 320 chars
    Given current hour is 14
    When I send a message with 400 characters to "blake"
    Then the SignalWire API receives a body of at most 320 characters

  Scenario: MSG-9: Empty message body is rejected
    Given current hour is 14
    When I send "" to "blake"
    Then a ValueError is raised

  # --- SignalWire API interaction ---

  Scenario: MSG-10: SignalWire 201 response returns message_id
    Given current hour is 14
    And SignalWire API will return 201 with sid "SM-123"
    When I send "Test" to "blake"
    Then the returned message_id starts with "msg-"
    And outbound_messages has provider_sid "SM-123"

  Scenario: MSG-11: SignalWire 401 raises with clear error
    Given current hour is 14
    And SignalWire API will return 401
    When I send "Test" to "blake"
    Then SendFailed is raised
    And no row is inserted into outbound_messages

  # --- Idempotency ---

  Scenario: MSG-12: Each send includes Idempotency-Key header
    Given current hour is 14
    When I send "Test" to "blake"
    Then the SignalWire API request includes header "Idempotency-Key"
    And the value matches pattern "msg-.*"
