"""Agent base class and handle() pipeline.

An agent is data, not a process. The runtime is shared.
handle() runs: Warden scan → build context → strategy.reason() → post-turn.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from stronghold.agents.messages import extract_user_text
from stronghold.tracing.pipeline import PipelineTrace
from stronghold.types.agent import AgentResponse

# Tool schemas — proper OpenAI function definitions for each tool
_TOOL_SCHEMAS: dict[str, dict[str, object]] = {
    "read_file": {
        "description": "Read the contents of a file. Returns the file content as a string.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File path relative to workspace root"},
            },
            "required": ["path"],
        },
    },
    "write_file": {
        "description": "Create or overwrite a file with the given content.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File path relative to workspace root"},
                "content": {"type": "string", "description": "The full file content to write"},
            },
            "required": ["path", "content"],
        },
    },
    "list_files": {
        "description": "List files and directories at the given path.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Directory path (default: '.')",
                    "default": ".",
                },
            },
        },
    },
    "run_pytest": {
        "description": "Run the pytest test suite. Returns pass/fail with details.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Test path (default: 'tests/')",
                    "default": "tests/",
                },
            },
        },
    },
    "run_ruff_check": {
        "description": "Run ruff linter. Returns violations with file:line:rule.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Path to check", "default": "src/"},
            },
        },
    },
    "run_mypy": {
        "description": "Run mypy type checker in strict mode. Returns type errors.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Path to check", "default": "src/"},
            },
        },
    },
    "run_bandit": {
        "description": "Run bandit security scanner. Returns security findings.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Path to scan", "default": "src/"},
            },
        },
    },
    "run_ruff_format": {
        "description": "Check code formatting with ruff. Returns formatting issues.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Path to check", "default": "src/"},
            },
        },
    },
    "git_commit": {
        "description": "Stage all changes and create a git commit.",
        "parameters": {
            "type": "object",
            "properties": {
                "message": {"type": "string", "description": "Commit message"},
            },
            "required": ["message"],
        },
    },
}


def _build_tool_schema(name: str, *, registry: Any = None) -> dict[str, object]:
    """Build an OpenAI-compatible tool definition for a named tool.

    Resolution order:
      1. Live tool registry (the source of truth for executor + parameters)
      2. Inline `_TOOL_SCHEMAS` table (legacy: quality-gate convenience tools)
      3. Stub with empty params (last-resort fallback so the LLM still sees the tool)
    """
    if registry is not None:
        defn = registry.get(name)
        if defn is not None:
            return {
                "type": "function",
                "function": {
                    "name": defn.name,
                    "description": defn.description,
                    "parameters": defn.parameters,
                },
            }

    schema = _TOOL_SCHEMAS.get(name)
    if schema:
        return {
            "type": "function",
            "function": {"name": name, **schema},
        }
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": f"Run {name}",
            "parameters": {"type": "object", "properties": {}},
        },
    }


def _detect_tool_failures(tool_history: list[dict[str, Any]]) -> bool:
    """Return True if any tool result looks like an error."""
    return bool(
        tool_history
        and any(
            str(h.get("result", "")).startswith("Error")
            or "error" in str(h.get("result", ""))[:50].lower()
            for h in tool_history
        )
    )


if TYPE_CHECKING:
    from stronghold.agents.context_builder import ContextBuilder
    from stronghold.memory.learnings.extractor import RCAExtractor, ToolCorrectionExtractor
    from stronghold.memory.learnings.promoter import LearningPromoter
    from stronghold.protocols.llm import LLMClient
    from stronghold.protocols.memory import LearningStore, OutcomeStore, SessionStore
    from stronghold.protocols.prompts import PromptManager
    from stronghold.protocols.quota import QuotaTracker
    from stronghold.protocols.tracing import TracingBackend
    from stronghold.security.warden.detector import Warden
    from stronghold.types.agent import AgentIdentity, ReasoningResult
    from stronghold.types.auth import AuthContext
    from stronghold.types.security import WardenVerdict


class Agent:
    """A running agent instance. All behavior determined by identity + strategy."""

    def __init__(
        self,
        identity: AgentIdentity,
        strategy: Any,  # ReasoningStrategy protocol
        *,
        llm: LLMClient,
        context_builder: ContextBuilder,
        prompt_manager: PromptManager,
        warden: Warden,
        learning_store: LearningStore | None = None,
        learning_extractor: ToolCorrectionExtractor | None = None,
        rca_extractor: RCAExtractor | None = None,
        learning_promoter: LearningPromoter | None = None,
        sentinel: Any = None,
        outcome_store: OutcomeStore | None = None,
        session_store: SessionStore | None = None,
        quota_tracker: QuotaTracker | None = None,
        coin_ledger: Any = None,
        tracer: TracingBackend | None = None,
        tool_executor: Any = None,
        tool_registry: Any = None,
    ) -> None:
        self.identity = identity
        self._strategy = strategy
        self._llm = llm
        self._context_builder = context_builder
        self._prompt_manager = prompt_manager
        self._warden = warden
        self._learning_store = learning_store
        self._learning_extractor = learning_extractor
        self._rca_extractor = rca_extractor
        self._learning_promoter = learning_promoter
        self._sentinel = sentinel
        self._outcome_store = outcome_store
        self._session_store = session_store
        self._quota_tracker = quota_tracker
        self._coin_ledger = coin_ledger
        self._tool_executor = tool_executor
        self._tool_registry = tool_registry
        self._tracer = tracer

    async def handle(
        self,
        messages: list[dict[str, Any]],
        auth: AuthContext,
        *,
        session_id: str | None = None,
        model_override: str | None = None,
        status_callback: Any = None,
    ) -> AgentResponse:
        """Route a request through the full agent pipeline."""
        trace = PipelineTrace(
            self._tracer.create_trace(
                user_id=auth.user_id,
                session_id=session_id or "",
                name=f"agent.{self.identity.name}",
                metadata={"agent": self.identity.name},
            )
            if self._tracer
            else None
        )
        user_text = extract_user_text(messages)

        if blocked := await self._warden_scan(trace, user_text):
            return blocked

        messages, history_count = await self._inject_session_history(messages, session_id)
        context_messages, injected_ids = await self._build_context(trace, messages, auth)
        model = model_override or self.identity.model

        result = await self._run_strategy(
            trace, context_messages, model, self._resolve_tool_defs(), auth, status_callback
        )
        if isinstance(result, AgentResponse):
            return result

        failures = _detect_tool_failures(result.tool_history)
        await self._run_rca(trace, user_text, result, auth, failures)
        await self._extract_learnings(trace, user_text, result, auth)
        await self._post_turn_memory(injected_ids, result, auth, failures)
        await self._save_session(session_id, user_text, result)
        await self._record_outcome(result, model, session_id, auth, failures)
        self._finalize_trace(trace, result, model, history_count, injected_ids)

        return AgentResponse(content=result.response or "", agent_name=self.identity.name)

    # ── Pipeline steps ────────────────────────────────────────────────────────

    async def _warden_scan(
        self, trace: PipelineTrace, user_text: str
    ) -> AgentResponse | None:
        """Scan user input; return a blocked AgentResponse if flagged, else None."""
        with trace.span("warden.user_input") as ws:
            ws.set_input({"text_length": len(user_text)})
            verdict = await self._warden.scan(user_text, "user_input")
            ws.set_output({"clean": verdict.clean, "flags": verdict.flags})
        if not verdict.clean:
            trace.score("blocked", 1.0, comment=f"flags: {verdict.flags}")
            trace.end()
            return AgentResponse.blocked_response(
                f"Blocked by Warden: {', '.join(verdict.flags)}"
            )
        return None

    async def _inject_session_history(
        self, messages: list[dict[str, Any]], session_id: str | None
    ) -> tuple[list[dict[str, Any]], int]:
        """Prepend session history before the current messages; return (messages, count)."""
        if not (session_id and self._session_store):
            return messages, 0
        history = await self._session_store.get_history(session_id)
        if not history:
            return messages, 0
        if messages and messages[0].get("role") == "system":
            return [messages[0], *history, *messages[1:]], len(history)
        return [*history, *messages], len(history)

    async def _build_context(
        self,
        trace: PipelineTrace,
        messages: list[dict[str, Any]],
        auth: AuthContext,
    ) -> tuple[list[dict[str, Any]], list[str]]:
        """Assemble the context window and return (context_messages, injected_ids)."""
        with trace.span("prompt.build") as ps:
            ps.set_input({"message_count": len(messages)})
            context, ids = await self._context_builder.build(
                messages,
                self.identity,
                prompt_manager=self._prompt_manager,
                learning_store=self._learning_store,
                agent_id=self.identity.name,
                org_id=auth.org_id,
                team_id=auth.team_id,
            )
            ps.set_output(
                {"context_message_count": len(context), "learnings_injected": len(ids)}
            )
        return context, ids

    def _resolve_tool_defs(self) -> list[dict[str, Any]] | None:
        """Build OpenAI-compatible tool definitions from the agent's identity."""
        if not self.identity.tools:
            return None
        return [
            _build_tool_schema(name, registry=self._tool_registry)
            for name in self.identity.tools
        ]

    async def _run_strategy(
        self,
        trace: PipelineTrace,
        context_messages: list[dict[str, Any]],
        model: str,
        tool_defs: list[dict[str, Any]] | None,
        auth: AuthContext,
        status_callback: Any,
    ) -> ReasoningResult | AgentResponse:
        """Run the reasoning strategy; return an AgentResponse on unrecoverable error."""
        kwargs: dict[str, Any] = {
            "trace": trace,
            "warden": self._warden,
            "auth": auth,
            "identity": self.identity,
        }
        if self._sentinel is not None:
            kwargs["sentinel"] = self._sentinel
        if status_callback:
            kwargs["status_callback"] = status_callback
        try:
            with trace.span("strategy.reason") as ss:
                ss.set_input({"model": model, "tools": len(tool_defs) if tool_defs else 0})
                result = await self._strategy.reason(
                    context_messages, model, self._llm,
                    tools=tool_defs, tool_executor=self._tool_executor, **kwargs,
                )
                ss.set_output({
                    "done": result.done,
                    "tool_rounds": len(result.tool_history) if result.tool_history else 0,
                    "response_length": len(result.response or ""),
                })
        except (ValueError, RuntimeError, TimeoutError, OSError) as exc:
            import logging as _log  # noqa: PLC0415
            _log.getLogger("stronghold.agent").warning(
                "Strategy failed: agent=%s model=%s error=%s",
                self.identity.name, model, type(exc).__name__,
            )
            trace.score("strategy_error", 0.0, "Strategy raised an exception")
            trace.end()
            return AgentResponse(
                content="I encountered an internal error. Please try again.",
                agent_name=self.identity.name,
            )
        return result

    async def _run_rca(
        self,
        trace: PipelineTrace,
        user_text: str,
        result: ReasoningResult,
        auth: AuthContext,
        tool_had_failures: bool,
    ) -> None:
        """Extract root-cause learnings when tool calls failed."""
        if not (tool_had_failures and self._rca_extractor and self._learning_store
                and result.tool_history):
            return
        with trace.span("rca.extraction") as rs:
            rca = await self._rca_extractor.extract_rca(user_text, result.tool_history)
            if rca:
                rca.agent_id = self.identity.name
                rca.org_id = auth.org_id
                rca.team_id = auth.team_id
                await self._learning_store.store(rca)
                rs.set_output({"rca": rca.learning[:200]})
            else:
                rs.set_output({"rca": "none"})

    async def _extract_learnings(
        self,
        trace: PipelineTrace,
        user_text: str,
        result: ReasoningResult,
        auth: AuthContext,
    ) -> None:
        """Extract correction and positive-pattern learnings from tool history."""
        if not (result.tool_history and self._learning_extractor and self._learning_store):
            return
        with trace.span("learning.extraction") as ls:
            corrections = self._learning_extractor.extract_corrections(
                user_text, result.tool_history
            )
            positives = self._learning_extractor.extract_positive_patterns(
                user_text, result.tool_history
            )
            for learning in corrections + positives:
                learning.agent_id = self.identity.name
                learning.org_id = auth.org_id
                learning.team_id = auth.team_id
                await self._learning_store.store(learning)
            ls.set_output({"corrections": len(corrections), "positives": len(positives)})

    async def _post_turn_memory(
        self,
        injected_ids: list[str],
        result: ReasoningResult,
        auth: AuthContext,
        tool_had_failures: bool,
    ) -> None:
        """Trigger learning promotion and record outcome feedback."""
        if self._learning_promoter and injected_ids:
            await self._learning_promoter.check_and_promote(org_id=auth.org_id)
        if injected_ids and self._learning_store:
            await self._learning_store.mark_outcome(
                injected_ids, success=not tool_had_failures, org_id=auth.org_id
            )

    async def _save_session(
        self, session_id: str | None, user_text: str, result: ReasoningResult
    ) -> None:
        """Persist the user and assistant turns to the session store."""
        if not (session_id and self._session_store and result.response):
            return
        save_msgs: list[dict[str, str]] = []
        if user_text:
            save_msgs.append({"role": "user", "content": user_text})
        save_msgs.append({"role": "assistant", "content": result.response})
        await self._session_store.append_messages(session_id, save_msgs)

    async def _record_outcome(
        self,
        result: ReasoningResult,
        model: str,
        session_id: str | None,
        auth: AuthContext,
        tool_had_failures: bool,
    ) -> None:
        """Charge coin ledger and record task outcome metrics."""
        if not self._outcome_store:
            return
        from stronghold.types.memory import Outcome

        charge_info: dict[str, object] = {"charged_microchips": 0, "pricing_version": ""}
        if self._coin_ledger:
            charge_info = await self._coin_ledger.charge_usage(
                request_id=session_id or "",
                org_id=auth.org_id,
                team_id=auth.team_id,
                user_id=auth.user_id,
                model_used=model,
                provider="",
                input_tokens=result.input_tokens,
                output_tokens=result.output_tokens,
            )
        outcome = Outcome(
            request_id=session_id or "",
            task_type="",
            model_used=model,
            provider="",
            tool_calls=[
                {
                    "name": str(h.get("tool_name", "")),
                    "success": not str(h.get("result", "")).startswith("Error"),
                }
                for h in (result.tool_history or [])
            ],
            success=not tool_had_failures,
            error_type="tool_error" if tool_had_failures else "",
            org_id=auth.org_id,
            team_id=auth.team_id,
            user_id=auth.user_id,
            agent_id=self.identity.name,
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
            charged_microchips=int(str(charge_info.get("charged_microchips", 0))),
            pricing_version=str(charge_info.get("pricing_version", "")),
        )
        await self._outcome_store.record(outcome)

    def _finalize_trace(
        self,
        trace: PipelineTrace,
        result: ReasoningResult,
        model: str,
        history_count: int,
        injected_ids: list[str],
    ) -> None:
        """Write final span metadata and close the trace."""
        success_count = 0
        fail_count = 0
        tools_used: list[str] = []
        for th in result.tool_history or []:
            r = str(th.get("result", ""))
            tools_used.append(str(th.get("tool_name", "")))
            if r.startswith("Error") or "error" in r[:50].lower():
                fail_count += 1
            else:
                success_count += 1
        trace.update({
            "agent": self.identity.name,
            "model": model,
            "response_length": str(len(result.response or "")),
            "tool_calls_total": str(len(result.tool_history) if result.tool_history else 0),
            "tool_calls_success": str(success_count),
            "tool_calls_failed": str(fail_count),
            "tools_used": ",".join(dict.fromkeys(tools_used)),
            "session_history_injected": str(history_count),
            "learnings_injected": str(len(injected_ids)),
        })
        trace.end()
