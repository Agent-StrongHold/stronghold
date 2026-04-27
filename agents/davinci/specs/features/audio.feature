Feature: Audio (TTS, voices, narration)
  Generate narration tracks per Document; per-character voices; word-level
  timings for captions; sound effects; ducking under voice.

  See ../27-audio.md.

  Background:
    Given an authenticated user in tenant "acme"
    And a Document "D1" with text layers per page
    And a TTS provider (default: openai_tts) configured

  @p0 @critical
  Scenario: Create a narration track over a Document
    When I narration_create document_id=D1 voice_id="openai/alloy" narrator_kind=SINGLE
    Then a NarrationTrack exists
    And segments cover every text layer in page order

  @p0
  Scenario: Per-segment audio is generated and concatenated with silence
    Given a NarrationTrack with default silences
    When the track is built
    Then each segment has audio_blob_id
    And the full track audio_blob_id is the concatenation with 800ms between pages

  @p0
  Scenario: Word timings used when provider supplies them
    Given a TTS provider that returns word timings
    When generating a segment
    Then segment.word_timings is non-empty

  @p0
  Scenario: Whisper alignment fallback when provider lacks timings
    Given a TTS provider that does NOT supply word timings
    When generating a segment
    Then word_timings are computed by Whisper alignment
    And confidence flag is recorded

  @p0
  Scenario: Character-based narration uses character voices
    Given NarratorKind=CHARACTER_BASED
    And character "Lily" has voice "elevenlabs/serenity"
    When dialogue attributed to Lily is processed
    Then that segment uses serenity voice
    And action/description text uses the default narrator voice

  @p0
  Scenario: Caption track derived from narration segments
    Given a NarrationTrack with timings
    When caption_from_narration is invoked
    Then a caption Track is created
    And each caption matches segment text + timing

  @p0
  Scenario: Caption from raw audio uses Whisper transcription
    Given an audio_blob with no narration
    When caption_from_audio is invoked
    Then Whisper produces a transcript
    And captions are created with timings

  @p0 @critical
  Scenario: SFX library lookup by tag
    Given the bundled SFX library
    When I sfx_list with tags=["page_turn"]
    Then matching SFX entries are returned
    And licenses are listed

  @p0
  Scenario: Sound effect inserted into narration track at offset
    Given an SFX and a track
    When sfx_insert at page_id and offset_ms
    Then the SFX is mixed in at the offset
    And voice ducks by -6dB during overlap

  @p0 @security
  Scenario: Voice cloning of public figure rejected
    Given a voice sample matching a denylisted public figure
    When voice_clone is invoked
    Then VoiceCloneRightsViolationError is raised

  @p0 @security
  Scenario: Voice cloning requires rights acknowledgement
    Given alice uploads a voice sample
    When alice does not acknowledge rights
    Then voice_clone is rejected

  @p0
  Scenario: Long text segment chunked to provider's max
    Given a text layer with 10k characters
    When generating its segment
    Then the audio is chunked at sentence boundaries
    And word timings are stitched correctly

  @p0
  Scenario: Provider unavailability falls through chain
    Given primary TTS provider returns 500
    When generating a segment
    Then the next configured provider is used
    And the audit entry records the actual provider

  @p0 @perf
  Scenario: Full 32-page picture book narration within budget
    Given a 32-page picture book Document
    When narration_create + segments generated end-to-end
    Then the full track completes in under 60 seconds with default provider

  @p1
  Scenario: Pronunciation override via book dictionary
    Given a book-level dictionary mapping name "Lily" → IPA
    When narration generates a segment containing "Lily"
    Then the IPA hint is included in the TTS request
