# Spec 17 — Chat surface

*HTTP chat interface. OpenAI-compatible so OpenWebUI (and anything else speaking the OpenAI API) treats Project Turing as a model. Streaming for plain replies, non-streaming when tools fire. One shared self with per-user session tagging from upstream auth headers.*

**Depends on:** [motivation.md](./motivation.md), [working-memory.md](./working-memory.md), [semantic-retrieval.md](./semantic-retrieval.md), [tool-layer.md](./tool-layer.md), [litellm-provider.md](./litellm-provider.md).
**Depended on by:** —

---

## Current state

`runtime/chat.py` exposes:
- `POST /v1/chat/completions` (OpenAI-compatible, non-streaming)
- `POST /chat` (legacy simple)
- `GET /v1/models`
- `GET /thoughts`, `GET /identity`
- `GET /` (HTML UI)

No streaming, no tool use from chat, no per-user tagging, no auth handling. 5 tests.

## Target

Full OpenAI-compatible surface that:
1. Reports `turing-conduit` in `/v1/models`.
2. Accepts streaming + non-streaming chat completions.
3. Routes user messages through the autonoetic loop (multi-step LLM calls if tools fire).
4. Tags every memory written during a session with the user identity from an upstream auth header.
5. Uses a composed prompt: operator base + self working memory + WISDOM + retrieved memory + conversation history + user message.

## Acceptance criteria

### OpenAI compatibility

- **AC-17.1.** `GET /v1/models` returns `{"object": "list", "data": [{"id": "turing-conduit", "object": "model", "created": <ts>, "owned_by": "project-turing"}]}`. Test.
- **AC-17.2.** `POST /v1/chat/completions` with `{model, messages: [...]}` returns the OpenAI chat-completion response shape: `{id, object: "chat.completion", created, model, choices: [{index, message: {role: "assistant", content}, finish_reason}], usage}`. Test.
- **AC-17.3.** Streaming: when the request includes `"stream": true`, the response is `text/event-stream` with `data: {...}\n\n` framed deltas matching the OpenAI streaming chat-completion shape, ending with `data: [DONE]\n\n`. Test asserts framing and content.
- **AC-17.4.** Streaming auto-disables when a tool call fires mid-reply: the stream ends gracefully with the partial assistant content, the tool runs, and a follow-up reply is composed and sent as a separate (non-streaming) chunk. Test asserts the non-streaming fallback path triggers.
- **AC-17.5.** `GET /` serves a minimal HTML chat UI for operators to verify the surface without OpenWebUI. Test asserts 200 + `<title>Project Turing` in body.

### Multi-turn handling

- **AC-17.6.** The `messages` array's full history is passed to the chat dispatcher (not flattened-and-discarded). The latest user message is the retrieval query; earlier turns are conversational context for the LLM. Test with a 3-turn conversation.
- **AC-17.7.** Empty messages array returns 400 `{"error": "missing 'messages'"}`. Test.

### Per-user session tagging

- **AC-17.8.** The chat handler reads `X-Forwarded-User` (configurable header name via `TURING_CHAT_USER_HEADER`) on every request. The value is the user tag for memories written during dispatch. Missing header defaults to `"anonymous"`. Test.
- **AC-17.9.** Memories written during a chat dispatch (OBSERVATION markers, OPINIONs, future REGRET/ACCOMPLISHMENT) carry `context["user_tag"] = <header value>`. Test asserts persistence of the tag.
- **AC-17.10.** Semantic retrieval during a chat call is *not* user-filtered by default — the shared self draws on its full memory regardless of who's asking. Test asserts cross-user retrieval works as expected.

### Prompt composition

- **AC-17.11.** Every chat reply uses the prompt structure:
  ```
  ## Base framing (operator-set)
  {base_prompt}

  ## Your working memory (self-maintained)
  {wm.render(self_id)}

  ## What you know about yourself (WISDOM)
  - ...

  ## Relevant memories
  - ...

  ## Conversation so far (last 6 turns)
  user: ...
  assistant: ...

  user: <latest>
  assistant:
  ```
  Test asserts each section heading is present in the prompt sent to the LLM.
- **AC-17.12.** When the `EmbeddingIndex` is empty or unavailable, the "Relevant memories" section is omitted (no empty heading). Test.
- **AC-17.13.** When WORKING_MEMORY is empty, the "Your working memory" heading still appears with the empty marker (per `working-memory.md`'s `render()` contract). Test.

### Tool use

- **AC-17.14.** The chat dispatcher's prompt includes a list of available tools and their schemas (per `tool-layer.md`). The LLM can return a function-call response; the dispatcher executes the tool, appends the result to the prompt, and re-calls the LLM for the final reply. Multi-step. Test with a registered fake tool.
- **AC-17.15.** A tool the LLM tries to call but isn't registered raises `ToolNotPermitted` and the dispatcher returns the error to the user as part of the assistant reply (e.g., "I don't have access to that"). Test.
- **AC-17.16.** Per-call tool-step cap: `MAX_TOOL_STEPS_PER_REPLY` (default 5). Exceeding the cap forces a final reply without further tool calls. Test.

### Health / routing endpoints

- **AC-17.17.** `GET /thoughts?limit=N` returns `{"thoughts": [...]}` reading the most recent `narrative.md` entries (per `journal.md`). Test.
- **AC-17.18.** `GET /identity` returns `{"self_id": "...", "wisdom": [{memory_id, content, intent, created_at}, ...]}`. Test.

### Failure modes

- **AC-17.19.** Provider errors during dispatch return a 200 OpenAI-shaped response with `content` describing the failure (e.g., "I encountered an error generating a reply") rather than HTTP error. OpenAI clients expect 200; raising would break OpenWebUI UX. Test.
- **AC-17.20.** Dispatcher timeout (`response_timeout_s`, default 30s) returns `504 {"error": "timeout"}`. Test.

### Auth / network

- **AC-17.21.** The chat server itself does NOT enforce auth. Auth is the cluster's responsibility (NetworkPolicy + ingress with oauth2-proxy or similar). The chat server reads `X-Forwarded-User` from the upstream proxy as truth. Documented in RUNNING.md. Test asserts the absence of any built-in auth check.
- **AC-17.22.** Default bind is `127.0.0.1`. Container env defaults to `0.0.0.0`; the user is responsible for not exposing port 9101 externally without a proxy. Test asserts default bind.

## Implementation

### 17.1 Streaming-vs-not decision

The dispatcher always begins in streaming mode if the request asked for it. The provider's `complete_streaming(prompt) -> Iterator[str]` yields tokens. After each yielded token, the dispatcher checks: is this token the start of a function-call protocol fragment? If yes:

1. Drop the streaming response (close the SSE stream cleanly).
2. Buffer the function call.
3. Execute the tool.
4. Resume with a new (non-streaming) LLM call that has the tool result.
5. Send the final assistant response as a single non-streaming chunk.

For LiteLLM, the function-call signal in streaming responses is `delta.tool_calls` per the OpenAI streaming protocol.

### 17.2 Tool-step loop

```python
def dispatch_chat(message, history, tools_available) -> str:
    prompt = build_chat_prompt(...)
    messages = [{"role": "user", "content": prompt}]
    for step in range(MAX_TOOL_STEPS_PER_REPLY):
        reply = provider.complete(messages, tools=tools_available)
        if reply.has_tool_call:
            tool_result = registry.invoke(reply.tool_name, **reply.tool_args)
            messages.append({"role": "assistant", "tool_calls": [reply.tool_call]})
            messages.append({"role": "tool", "content": str(tool_result)})
            continue
        return reply.content
    # Cap reached — force a plain reply.
    final = provider.complete(messages + [{"role": "system",
                                            "content": "No more tools; reply now."}])
    return final.content
```

### 17.3 Configuration constants

```python
CHAT_RESPONSE_TIMEOUT_S:        float = 30.0
MAX_TOOL_STEPS_PER_REPLY:       int   = 5
TURING_CHAT_USER_HEADER_NAME:   str   = "X-Forwarded-User"
```

## Open questions

- **Q17.1.** Streaming-to-non-streaming transition is rough: the SSE stream ends, the client sees a brief pause, then the final reply arrives. OpenWebUI handles this acceptably in practice (it shows "thinking..." during the pause), but it's not perfect. Better UX: keep the SSE channel open and emit assistant deltas with tool_call markers per the OpenAI protocol. Defer; current shape is a working approximation.
- **Q17.2.** Per-call concurrency: a long-running chat reply blocks one motivation backlog slot. Multiple simultaneous chats from different users could exhaust `MAX_CONCURRENT_DISPATCHES`. Specced as a future tuning concern; defer until observed.
- **Q17.3.** Audio surfaces (voice) overlay onto this same shape — `POST /v1/chat/completions` with audio prompt content, response is text or TTS depending on operator preference. Out of scope for chunk N; the spec leaves room for it.
- **Q17.4.** The HTML UI at `/` is minimal (single-textarea form). Real ops use OpenWebUI; the HTML UI is just a no-OpenWebUI fallback. Acceptable.
