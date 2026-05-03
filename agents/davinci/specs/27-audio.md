# 27 — Audio (TTS, Voices, Narration)

**Status**: P1 / Content phase. Foundation for read-along videos (§15).
**One-liner**: text-to-speech narration per Document or per text layer; voice
references per character; sound effects library; aligned timestamps for
captioning.

## Problem it solves

A children's book becomes a *read-along* book when narrated. A video overlay
needs captions and voiceover. An infographic explainer needs synced
narration. Without an audio subsystem, every video gets manually-recorded
audio. With it, every Document can be narrated in seconds.

## Data model

```
NarrationTrack (frozen):
  id: str
  document_id: str
  language: str                     # BCP-47
  voice_id: str                     # provider-specific voice
  narrator: NarratorKind            # SINGLE | CHARACTER_BASED
  segments: tuple[NarrationSegment, ...]
  audio_blob_id: str | None         # full mixed audio
  created_at, updated_at

NarrationSegment (frozen):
  id: str
  page_id: str
  layer_id: str | None              # source text layer (or None for narrator)
  text: str
  voice_id: str                     # may differ from track default per-character
  start_ms: int                     # within track
  duration_ms: int
  word_timings: tuple[WordTiming, ...]   # for karaoke-style highlighting
  audio_blob_id: str                 # per-segment audio

WordTiming (frozen):
  word: str
  start_ms: int
  duration_ms: int

NarratorKind (StrEnum):
  SINGLE          # one voice for whole doc
  CHARACTER_BASED # different voice per character

VoiceRef (frozen):
  id: str                           # provider-prefixed e.g. "elevenlabs/serenity"
  provider: AudioProvider
  display_name: str
  language_support: tuple[str, ...]
  description: str                  # "warm female narrator, ages 4-8"
  preview_audio_blob_id: str | None

CharacterVoice (frozen):
  character_asset_id: str           # cross-ref §18
  voice_id: str
```

## Providers

| Provider | Use | Cost | Latency |
|---|---|---|---|
| **ElevenLabs** | natural narrator voices, character voices | $0.18/1k chars | 2-5s/segment |
| **OpenAI TTS** | basic, fast, cheap | $0.015/1k chars | 1-3s |
| **Cartesia** | low-latency streaming | $0.10/1k chars | sub-second |
| **Google Cloud TTS** | broad language coverage | $0.016/1k chars | 1-3s |
| **Local Coqui XTTS** | self-hosted; voice cloning | free (compute cost) | depends |

Provider chosen by document/user setting; default `openai_tts` for cost.
Cost-gated per §31.

## Voice cloning (P1)

User uploads a 30s sample → ElevenLabs / Coqui clones the voice. Tenant-scoped
voice asset; user attests rights (legal: voice rights are sensitive).

```
voice_clone(audio_blob_id, name, [language_hint]) -> VoiceRef
```

Warden + Sentinel scan the audio for: no public-figure impersonation, no
known voice matches in a denylist (P2: voice fingerprinting).

## Character voices

For NarratorKind=CHARACTER_BASED:
- A `CharacterAsset` (§18) gains an optional `voice_id`
- During narration, dialogue attributed to a character uses that voice
- Narrator (default voice) reads action/description text
- Dialogue attribution detection: heuristic ("...said Lily") + LLM
  classification fallback

## Synchronization

Per-segment audio is generated; full track is concatenated with
segment-aware silence (per Page boundary 800ms; per paragraph 400ms; per
sentence 250ms; configurable).

Word-level timings come from provider response (ElevenLabs, Cartesia
support; OpenAI does not — falls back to forced alignment via Whisper).

## Caption generation (cross-ref §15 video)

Segments + word timings produce VTT/SRT caption files for video export. Per
caption is one segment or one sentence (whichever shorter).

## Sound effects library

```
SoundEffect (frozen):
  id: str
  name: str
  tags: tuple[str, ...]
  duration_ms: int
  audio_blob_id: str
  license: str                      # CC0, royalty-free, etc.
```

Bundled set: ~100 kid-friendly SFX (page turn, footsteps, magic, dragon
roar, etc.). Search by tag.

User-uploaded SFX permitted (rights acknowledged, Warden scan).

## Music (P1)

Background music via:
- Bundled royalty-free tracks (pixabay / freepd, attribution where required)
- Provider integration (Suno / Udio API once available, cost-gated)

Music plays under narration with auto-ducking (-6dB during voice).

## API surface

| Action | Args | Returns |
|---|---|---|
| `narration_create` | `document_id, voice_id, [narrator_kind]` | NarrationTrack |
| `narration_segment_generate` | `track_id, segment_text, voice_id` | NarrationSegment |
| `narration_regenerate_page` | `track_id, page_id` | re-rendered segments |
| `narration_export` | `track_id, format: mp3\|wav\|ogg` | bytes |
| `voice_list` | `[provider, language]` | tuple[VoiceRef, ...] |
| `voice_preview` | `voice_id, sample_text` | bytes |
| `voice_clone` | `audio_blob_id, name` | VoiceRef |
| `character_voice_set` | `character_asset_id, voice_id` | CharacterAsset |
| `sfx_list` | `[tags]` | tuple[SoundEffect, ...] |
| `sfx_insert` | `track_id, sfx_id, page_id, offset_ms` | NarrationTrack |

## Edge cases

1. **Text layer changes after narration generated** — segment marked stale;
   re-generation cost-gated.
2. **TTS provider down** — fall through chain; if all down,
   `NarrationBackendError`.
3. **Voice doesn't support target language** — fall back to default voice
   for that language; warn.
4. **Voice cloning of public figure** — Warden / denylist; reject with
   clear reason.
5. **Dialogue attribution wrong** — user can override per segment.
6. **Word timings missing** (provider doesn't supply) — forced alignment via
   Whisper; flag if confidence < threshold.
7. **Long text per segment** — chunk to provider's max; preserve semantic
   breaks (sentence boundaries).
8. **Generated audio contains injected voice prompt** (TTS jailbreak) —
   listened-to-by-Warden via STT round-trip on a sample (P2).
9. **Unsupported language** — fall back to closest supported; warn.
10. **Pronunciation issues** with names — user-overridable phonetic spelling
    or IPA dictionary per book.

## Errors

- `NarrationBackendError(RoutingError)`
- `VoiceNotFoundError(ConfigError)`
- `VoiceCloneRightsViolationError(SecurityError)`
- `SFXLicenseUnknownError(ConfigError)`

## Test surface

- Unit: NarrationTrack/Segment invariants; word timing arithmetic; provider
  fallback selection.
- Integration: generate narration for a fixture book → audio_blob_id set;
  exported caption VTT validates; per-character voice routing works.
- Security: voice cloning denylist enforced; rights acknowledgement required;
  bandit clean.
- Performance: full 32-page picture book narration < 60s on default provider.

## Dependencies

- LiteLLM (translation cost gating)
- ElevenLabs / OpenAI TTS / Cartesia API endpoints
- Whisper or `whisperx` for word alignment (when provider doesn't supply)
- `pydub` or `ffmpeg-python` for audio mixing
- bundled SFX set (royalty-free)
