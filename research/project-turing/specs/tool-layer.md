# Spec 18 — Tool layer

*Outward-facing actions. Allowlist enforced structurally — only operator-registered tools can fire. Failures mint stance OPINIONs that the existing pipeline promotes to LESSON or REGRET. OpenAI-style function-call schemas so the chat dispatcher can invoke tools mid-reply.*

**Depends on:** [schema.md](./schema.md), [write-paths.md](./write-paths.md), [chat-surface.md](./chat-surface.md).
**Depended on by:** [rss-thinking.md](./rss-thinking.md).

---

## Current state

`runtime/tools/base.py` (Tool Protocol + ToolRegistry + ToolNotPermitted), `runtime/tools/obsidian.py` (real), `runtime/tools/rss.py` (real), `runtime/tools/wiki.py` / `wordpress.py` / `search.py` / `newsletter.py` (scaffolds). 4 ToolRegistry tests, 4 Obsidian tests, 5 RSS tests. Scaffolds untested. No spec.

## Target

A `Tool` Protocol with structured `invoke()` arguments, a `ToolRegistry` that holds the operator's allowlist, OpenAI-style function-call schemas for chat-dispatcher integration, failure-handling that mints stance OPINIONs through the existing memory pipeline.

## Acceptance criteria

### Protocol

- **AC-18.1.** Every Tool implements:
  ```python
  class Tool(Protocol):
      name: str          # unique within a registry
      mode: ToolMode     # READ | WRITE | SUBSCRIBE
      def invoke(self, **kwargs) -> Any: ...
      def schema(self) -> dict: ...   # NEW per this spec
  ```
  Test asserts every concrete tool implements all four.
- **AC-18.2.** `schema()` returns an OpenAI-compatible function-calling JSON schema:
  ```json
  {
    "name": "<tool.name>",
    "description": "<one-line description>",
    "parameters": {
      "type": "object",
      "properties": {<arg_name>: {"type": "...", "description": "..."}},
      "required": ["<required arg>", ...]
    }
  }
  ```
  Test asserts the shape for ObsidianWriter, RSSReader, and the four scaffold tools.

### ToolRegistry

- **AC-18.3.** `register(tool)` adds a tool; double-registration of the same name raises `ValueError`. Test.
- **AC-18.4.** `get(name)` returns the tool; unknown name raises `ToolNotPermitted`. Test.
- **AC-18.5.** `invoke(name, **kwargs)` delegates to `get(name).invoke(**kwargs)`. Test.
- **AC-18.6.** `names()` returns sorted list of registered tool names. `names_by_mode(mode)` filters. Test.
- **AC-18.7.** `schemas()` (NEW) returns a list of all registered tools' OpenAI function-call schemas. The chat dispatcher uses this to populate the `tools` argument on its LLM call. Test.
- **AC-18.8.** A registry created with no tools returns empty `names()` and empty `schemas()`; `invoke()` always raises `ToolNotPermitted`. Test.

### Failure handling

- **AC-18.9.** When a tool's `invoke()` raises, the caller (Actor, chat dispatcher, RSS action handler) must mint a stance OPINION via the standard write-path:
  ```python
  EpisodicMemory(
    tier=OPINION, source=I_DID,
    content=f"tried tool '{tool_name}' for '{intent}'; failed: {exc}",
    weight=0.4,
    intent_at_time=f"tool-{tool_name}",
    context={"failure_count": <n>},
  )
  ```
  Test asserts the OPINION lands on a fake-failing tool.
- **AC-18.10.** When a stance OPINION's `failure_count` accumulates past `TOOL_FAILURE_LESSON_THRESHOLD` (default 3, configurable) for the same `(tool_name, intent)` combination, the contradiction-detection / promotion pipeline should mint a LESSON. This pipeline already exists; the only new behavior is the failure-count tracking. Test asserts a 4th failure with same intent produces a LESSON.
- **AC-18.11.** A successful tool invocation that follows accumulated failures supersedes the latest stance OPINION (resolves the contradiction; mints an ACCOMPLISHMENT through the existing path). Test.

### Concrete tools

#### ObsidianWriter (real)

- **AC-18.12.** Writes markdown notes with YAML front-matter to `<vault>/<subdir>/<YYYY-MM-DD>/<HHMMSS>-<slug>.md`. Test asserts file presence + format.
- **AC-18.13.** Schema declares: `title` (required string), `content` (required string), `tags` (optional list[string]), `kind` (optional string), `front_matter` (optional dict).

#### RSSReader (real)

- **AC-18.14.** Parses RSS 2.0 and Atom feeds; deduplicates by guid/id/hashed-link. Test.
- **AC-18.15.** Schema declares: `url` (optional string; omit to poll all registered feeds).

#### MediaWikiWriter (scaffold)

- **AC-18.16.** Constructor requires `api_url`, `bot_username`, `bot_password`; raises `ValueError` on any missing. Test.
- **AC-18.17.** Schema declares: `title` (required), `content` (required), `summary` (optional), `section` (optional). Test.

#### WordPressWriter (scaffold)

- **AC-18.18.** Constructor requires `site_url`, `username`, `application_password`; raises on missing. Test.
- **AC-18.19.** Schema declares: `title` (required), `content` (required), `status` (optional), `categories` / `tags` (optional list[int]), `excerpt` (optional). Defaults to draft status. Test.

#### SearxSearch (scaffold)

- **AC-18.20.** Constructor requires `base_url`. Test.
- **AC-18.21.** Schema declares: `query` (required), `max_results` (optional int, default 10). Returns list of `SearchResult(title, url, snippet)`. Test.

#### NewsletterSubscriber (scaffold)

- **AC-18.22.** Constructor requires `endpoint` and `email`; raises on missing. Test.
- **AC-18.23.** Schema declares: `list_name` (optional), `extra_fields` (optional dict).

## Implementation

### 18.1 Schema accessor pattern

Each tool gains a `schema()` method. The simplest implementation hand-codes the schema in the tool class:

```python
class ObsidianWriter:
    name = "obsidian_writer"
    mode = ToolMode.WRITE

    def schema(self) -> dict:
        return {
            "name": self.name,
            "description": "Write a markdown note to the Obsidian vault.",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Note title"},
                    "content": {"type": "string", "description": "Note body"},
                    "tags": {"type": "array", "items": {"type": "string"}},
                    "kind": {"type": "string"},
                },
                "required": ["title", "content"],
            },
        }
```

### 18.2 Failure tracking

Stance OPINIONs from failed tool calls carry `intent_at_time = f"tool-{tool_name}"`. A `failure_count` field in `context` accumulates across attempts; the tool-failure handler reads the latest stance for the same intent and either:
- Increments the existing count by writing a new stance with `failure_count = old + 1` and superseding the previous stance.
- Or starts at 1 if no prior stance exists.

When `failure_count >= TOOL_FAILURE_LESSON_THRESHOLD`, the next failure mints a LESSON: "Repeated failures with `tool_name` on `intent` — alternative: ..."

### 18.3 Configuration constants

```python
TOOL_FAILURE_LESSON_THRESHOLD: int = 3
```

## Open questions

- **Q18.1.** Schema authorship: hand-coded per tool is simple but error-prone. An alternative is a decorator that derives schema from the `invoke` signature and type hints. Defer; hand-coded for the chunk that ships first.
- **Q18.2.** Tool argument validation: the schema describes the contract but the tool itself may need to re-validate (the LLM can hallucinate args). Each `invoke()` should validate its kwargs and raise `ValueError` on bad inputs; the bad-call mints a stance OPINION per AC-18.9.
- **Q18.3.** Streaming tool results: a search that returns 50 hits would currently send the whole list in one chat reply. A future enhancement could stream tool results into the chat. Out of scope.
- **Q18.4.** Tool composition: the LLM might want to chain tools (`search` → `wiki_writer`). The current `MAX_TOOL_STEPS_PER_REPLY` cap from `chat-surface.md` bounds this. Within the cap, chaining works.
