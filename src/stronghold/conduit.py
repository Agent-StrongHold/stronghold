"""Conduit — the request pipeline through which all requests flow.

Every request enters Stronghold through the Conduit. It orchestrates:
1. Intent classification (what does the user want?)
2. Ambiguity resolution (is the request clear enough?)
3. Execution tier determination (what priority tier?)
4. Model selection (which LLM should handle this?)
5. Quota pre-check (can we afford this request?)
6. Sufficiency analysis (does the request have enough detail?)
7. Agent dispatch (route to the right specialist)
8. Response formatting (OpenAI-compatible output)

The Conduit never executes tasks directly — it decides and delegates.
When it can't decide, it routes to the Arbiter agent for clarification.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import replace
from typing import TYPE_CHECKING, Any, Literal, Protocol, cast, runtime_checkable

from stronghold.agents.messages import extract_user_text
from stronghold.types.model import ModelConfig, ProviderConfig
from stronghold.types.reactor import Event

if TYPE_CHECKING:
    from stronghold.container import Container
    from stronghold.types.intent import Intent

logger = logging.getLogger("stronghold.conduit")

_PriorityTier = Literal["P0", "P1", "P2", "P3", "P4", "P5"]

# ── Execution tier constants ──
_TIER_LEVELS: dict[str, int] = {"P0": 0, "P1": 1, "P2": 2, "P3": 3, "P4": 4, "P5": 5}
_LEVEL_TO_TIER: dict[int, _PriorityTier] = {
    0: "P0",
    1: "P1",
    2: "P2",
    3: "P3",
    4: "P4",
    5: "P5",
}
# Critical tiers that must never be downgraded by cluster pressure.
_CRITICAL_TIERS: frozenset[str] = frozenset({"P0", "P1"})


@runtime_checkable
class _HasPriorityTier(Protocol):
    """Duck-type for anything carrying a priority_tier attribute."""

    priority_tier: str


def _get_cluster_pressure() -> bool:
    """Return True when the cluster is under pressure.

    Stub: always returns False. Will be wired to real metrics later.
    """
    return False


def _apply_tenant_policy(tier: str, _tenant_id: str | None = None) -> str:
    """Apply tenant-specific tier policy overrides.

    Stub: returns tier unchanged. Will consult tenant config later.
    """
    return tier


def determine_execution_tier(
    intent: Intent,
    agent: Any = None,
) -> Intent:
    """Apply the override stack to determine the final execution tier.

    Override stack (each step can override the previous):
      1. classifier.suggested_tier  -- from Intent.tier after classification
      2. agent.priority_tier        -- agent definition override
      3. tenant policy              -- (stub: no-op)
      4. cluster pressure           -- downgrades P2-P5 by one level

    Returns a *new* Intent with ``tier`` set to the final value.
    The caller should also record ``suggested_tier`` for tracing.
    """
    suggested_tier: str = intent.tier

    # ── Step 1: start with classifier suggestion ──
    current_tier = suggested_tier

    # ── Step 2: agent override ──
    if agent is not None and hasattr(agent, "priority_tier"):
        agent_tier: str = agent.priority_tier
        if agent_tier in _TIER_LEVELS and agent_tier != current_tier:
            logger.debug(
                "Agent priority_tier override: %s -> %s",
                current_tier,
                agent_tier,
            )
            current_tier = agent_tier

    # ── Step 3: tenant policy (stub) ──
    current_tier = _apply_tenant_policy(current_tier)

    # ── Step 4: cluster pressure ──
    if _get_cluster_pressure() and current_tier not in _CRITICAL_TIERS:
        level = _TIER_LEVELS.get(current_tier)
        if level is not None and level < 5:
            downgraded = _LEVEL_TO_TIER[level + 1]
            logger.debug(
                "Cluster pressure downgrade: %s -> %s",
                current_tier,
                downgraded,
            )
            current_tier = downgraded

    if current_tier == suggested_tier:
        return intent

    # current_tier comes from _LEVEL_TO_TIER (P0–P5 keys) or
    # agent.priority_tier (gated by `in _TIER_LEVELS`); both are Intent.tier
    # Literals at runtime. The cast tells mypy what the runtime guards prove.
    return replace(
        intent,
        tier=cast("Literal['P0', 'P1', 'P2', 'P3', 'P4', 'P5']", current_tier),
    )


# Words that signal consent in response to a data-sharing question.
_CONSENT_AFFIRMATIVE = frozenset(
    {
        "yes",
        "yeah",
        "sure",
        "ok",
        "okay",
        "fine",
        "allow",
        "yep",
        "yup",
        "y",
        "absolutely",
        "go",
    }
)


class Conduit:
    """The request pipeline — all requests flow through here.

    Holds no state except session→agent stickiness mapping.
    All dependencies are accessed through the Container.
    """

    _MAX_STICKY_SESSIONS = 10_000  # Evict oldest entries when exceeded
    _MAX_CONSENT_ENTRIES = 10_000  # SEC-013: bound consent maps too

    def __init__(self, container: Container) -> None:
        self._c = container
        self._session_agents: dict[str, str] = {}
        self._session_consents: dict[str, set[str]] = {}
        self._consent_pending: dict[str, str] = {}
        self._session_lock = asyncio.Lock()

    def _fallback_agent_name(self, preferred: str | None = None) -> str:
        """Resolve a usable agent name even if a configured agent is missing."""
        agents = self._c.agents
        if preferred and preferred in agents:
            return preferred
        if "arbiter" in agents:
            return "arbiter"
        if "default" in agents:
            return "default"
        for name in agents:
            return name
        raise RuntimeError("No agents are loaded in Stronghold")

    def _fallback_agent(self, preferred: str | None = None) -> Any:
        """Resolve an agent object with graceful fallback semantics."""
        name = self._fallback_agent_name(preferred)
        if preferred == "arbiter" and name != "arbiter":
            logger.warning("Arbiter agent missing; falling back to '%s'", name)
        return self._c.agents[name]

    @staticmethod
    def _estimate_tokens(messages: list[dict[str, Any]]) -> int:
        """Cheap token estimate for preflight coin-budget checks."""
        chars = 0
        for msg in messages:
            content = msg.get("content", "")
            if isinstance(content, str):
                chars += len(content)
            elif isinstance(content, list):
                chars += sum(
                    len(str(part.get("text", "")))
                    for part in content
                    if isinstance(part, dict) and part.get("type") == "text"
                )
        return max(chars // 4, 1)

    async def route_request(
        self,
        messages: list[dict[str, Any]],
        *,
        auth: Any = None,
        session_id: str | None = None,
        intent_hint: str = "",
        status_callback: Any = None,
    ) -> dict[str, Any]:
        """Route a request through the pipeline to the right agent.

        This is the ONLY way requests should reach an LLM. Nothing calls
        LiteLLM directly.

        Args:
            auth: AuthContext from the authenticated request. Required.

        Raises:
            TypeError: If auth is None or not an AuthContext instance.
            QuotaExhaustedError: If all providers are at 100%+ usage.
        """
        import time as _time

        self._validate_auth(auth)
        _start = _time.monotonic()
        c = self._c

        async def _status(msg: str) -> None:
            if status_callback:
                await status_callback(msg)

        trace = self._create_trace(auth, session_id)

        await _status("Classifying intent...")
        result = await self._classify_intent(messages, intent_hint, auth, session_id, trace)
        if isinstance(result, dict):
            return result
        intent: Intent = result

        target_agent_name = c.intent_registry.get_agent_for_intent(intent.task_type)
        intent = self._determine_tier(intent, target_agent_name, trace)
        trace.update({"task_type": intent.task_type, "classified_by": intent.classified_by})
        self._emit_reactor(
            "post_classify",
            {
                "task_type": intent.task_type,
                "complexity": intent.complexity,
                "tier": intent.tier,
                "classified_by": intent.classified_by,
                "user_id": auth.user_id,
                "session_id": session_id or "",
            },
        )

        target_agent_name = await self._apply_session_stickiness(
            session_id, intent_hint, target_agent_name
        )
        self._resolve_consent(session_id, messages)

        providers_cfg = self._build_providers_cfg()
        await self._check_quota(auth, intent, providers_cfg)

        _consented = self._session_consents.get(session_id or "", set())
        routable_providers = {
            k: v for k, v in providers_cfg.items() if not v.data_sharing or k in _consented
        }

        await _status(f"Routing to {(target_agent_name or 'default').title()}...")
        models = self._build_models_cfg()
        selection, model_to_use = self._select_model(intent, models, routable_providers, trace)

        consent_response = await self._check_data_sharing_consent(
            intent, models, providers_cfg, _consented, selection, session_id, auth, messages
        )
        if consent_response is not None:
            return consent_response

        await self._preflight_coin_check(auth, model_to_use, selection, messages)
        is_sticky_followup = await self._is_sticky_followup(session_id, target_agent_name)

        agent, messages, sufficiency_response = await self._run_sufficiency_check(
            intent,
            messages,
            auth,
            model_to_use,
            session_id,
            is_sticky_followup,
            intent_hint,
            target_agent_name,
        )
        if sufficiency_response is not None:
            return sufficiency_response

        await self._save_session_stickiness(session_id, agent)
        self._set_fallback_models(selection, model_to_use)
        self._emit_reactor(
            "pre_agent",
            {
                "agent": agent.identity.name,
                "model": model_to_use,
                "task_type": intent.task_type,
                "user_id": auth.user_id,
                "session_id": session_id or "",
            },
        )

        await _status(f"{agent.identity.name.title()} is working...")
        response = await self._dispatch_agent(
            agent, messages, auth, session_id, model_to_use, status_callback, trace
        )

        self._finalize_trace(trace, model_to_use, selection, agent, intent, session_id, _start)
        self._emit_reactor(
            "post_response",
            {
                "agent": agent.identity.name,
                "model": model_to_use,
                "task_type": intent.task_type,
                "user_id": auth.user_id,
                "session_id": session_id or "",
                "content_length": (len(response.content) if response.content else 0),
            },
        )

        return self._build_response(
            response_id=f"stronghold-{intent.task_type}",
            model=model_to_use,
            content=response.content,
            routing={
                "intent": {
                    "task_type": intent.task_type,
                    "complexity": intent.complexity,
                    "tier": intent.tier,
                    "classified_by": intent.classified_by,
                },
                "model": model_to_use,
                "agent": agent.identity.name,
                "reason": selection.reason if selection else "default",
            },
            include_usage=True,
        )

    @staticmethod
    def _build_response(
        *,
        response_id: str,
        model: str,
        content: str,
        routing: dict[str, Any],
        include_usage: bool = False,
    ) -> dict[str, Any]:
        """Build an OpenAI-compatible chat completion response."""
        result: dict[str, Any] = {
            "id": response_id,
            "object": "chat.completion",
            "model": model,
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": content},
                    "finish_reason": "stop",
                }
            ],
            "_routing": routing,
        }
        if include_usage:
            result["usage"] = {
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0,
            }
        else:
            result["usage"] = {}
        return result

    # ── Private pipeline steps ─────────────────────────────────────────────

    def _validate_auth(self, auth: Any) -> None:
        from stronghold.types.auth import AuthContext

        if auth is None or not isinstance(auth, AuthContext):
            logger.error(
                "route_request called without valid AuthContext (got %s). "
                "All callers must provide an explicit AuthContext.",
                type(auth).__name__,
            )
            raise TypeError(
                "route_request requires an AuthContext instance — "
                f"got {type(auth).__name__}. "
                "Pass an explicit AuthContext; SYSTEM_AUTH fallback has been removed."
            )

    def _create_trace(self, auth: Any, session_id: str | None) -> Any:
        return self._c.tracer.create_trace(
            user_id=auth.user_id,
            session_id=session_id or "",
            name="route_request",
        )

    async def _classify_intent(
        self,
        messages: list[dict[str, Any]],
        intent_hint: str,
        auth: Any,
        session_id: str | None,
        trace: Any,
    ) -> Any:
        """Classify intent; returns Intent or an early-exit response dict if ambiguous."""
        c = self._c
        with trace.span("conduit.classify") as cs:
            if intent_hint and intent_hint in c.config.task_types:
                from stronghold.types.intent import Intent

                intent: Intent = Intent(
                    task_type=intent_hint,
                    classified_by="hint",
                    user_text=extract_user_text(messages),
                )
                cs.set_output({"task_type": intent_hint, "classified_by": "hint"})
            else:
                intent = await c.classifier.classify(messages, c.config.task_types)
                cs.set_output(
                    {
                        "task_type": intent.task_type,
                        "classified_by": intent.classified_by,
                        "complexity": intent.complexity,
                        "tier": intent.tier,
                    }
                )

            from stronghold.classifier.engine import is_ambiguous
            from stronghold.classifier.keyword import score_keywords

            raw_scores = score_keywords(intent.user_text, c.config.task_types)
            if is_ambiguous(raw_scores) and not intent_hint:
                arbiter = self._fallback_agent("arbiter")
                response = await arbiter.handle(messages, auth, session_id=session_id)
                return self._build_response(
                    response_id="stronghold-clarify",
                    model=arbiter.identity.name,
                    content=response.content,
                    routing={
                        "intent": {
                            "task_type": "clarify",
                            "scores": raw_scores,
                            "classified_by": "ambiguous",
                        },
                        "agent": arbiter.identity.name,
                        "reason": f"ambiguous: {raw_scores}",
                    },
                )

        return intent

    def _determine_tier(
        self, intent: Intent, target_agent_name: str | None, trace: Any
    ) -> Intent:
        c = self._c
        _agent_for_tier = c.agents.get(target_agent_name) if target_agent_name else None
        suggested_tier = intent.tier
        with trace.span("conduit.determine_tier") as ts:
            intent = determine_execution_tier(intent, agent=_agent_for_tier)
            ts.set_output({"suggested_tier": suggested_tier, "final_tier": intent.tier})
        return intent

    def _emit_reactor(self, event_name: str, data: dict[str, Any]) -> None:
        self._c.reactor.emit(Event(event_name, data))

    async def _apply_session_stickiness(
        self,
        session_id: str | None,
        intent_hint: str,
        target_agent_name: str | None,
    ) -> str | None:
        if session_id and not target_agent_name and not intent_hint:
            async with self._session_lock:
                sticky = self._session_agents.get(session_id)
                if sticky and sticky in self._c.agents:
                    return sticky
        return target_agent_name

    def _resolve_consent(
        self, session_id: str | None, messages: list[dict[str, Any]]
    ) -> None:
        if not session_id or session_id not in self._consent_pending:
            return
        pending_provider = self._consent_pending.pop(session_id)
        user_text = extract_user_text(messages).strip().lower()
        first_word = user_text.split()[0] if user_text else ""
        if first_word not in _CONSENT_AFFIRMATIVE and user_text not in _CONSENT_AFFIRMATIVE:
            return
        if session_id not in self._session_consents:
            self._session_consents[session_id] = set()
        self._session_consents[session_id].add(pending_provider)
        if len(self._session_consents) > self._MAX_CONSENT_ENTRIES:
            excess = len(self._session_consents) - self._MAX_CONSENT_ENTRIES
            for old_key in list(self._session_consents)[:excess]:
                del self._session_consents[old_key]
        logger.info(
            "Data sharing consent granted: session=%s provider=%s",
            session_id,
            pending_provider,
        )

    def _build_providers_cfg(self) -> dict[str, ProviderConfig]:
        _prov_fields = {f.name for f in ProviderConfig.__dataclass_fields__.values()}
        return {
            k: ProviderConfig(**{fk: fv for fk, fv in v.items() if fk in _prov_fields})  # type: ignore[arg-type]
            if isinstance(v, dict)
            else v
            for k, v in self._c.config.providers.items()
        }

    def _build_models_cfg(self) -> dict[str, ModelConfig]:
        _model_fields = {f.name for f in ModelConfig.__dataclass_fields__.values()}
        return {
            k: ModelConfig(**{fk: fv for fk, fv in v.items() if fk in _model_fields})  # type: ignore[arg-type]
            if isinstance(v, dict)
            else v
            for k, v in self._c.config.models.items()
        }

    async def _check_quota(
        self,
        auth: Any,
        intent: Intent,
        providers_cfg: dict[str, ProviderConfig],
    ) -> None:
        c = self._c
        _any_available = False
        for prov_name, prov_cfg in providers_cfg.items():
            if prov_cfg.status != "active":
                continue
            has_paygo = (
                prov_cfg.overage_cost_per_1k_input > 0
                or prov_cfg.overage_cost_per_1k_output > 0
            )
            if has_paygo:
                _any_available = True
                break
            usage_pct = await c.quota_tracker.get_usage_pct(
                prov_name,
                prov_cfg.billing_cycle,
                prov_cfg.free_tokens,
            )
            if usage_pct < 1.0:
                _any_available = True
                break

        if not _any_available:
            from stronghold.types.errors import QuotaExhaustedError

            logger.warning(
                "Quota pre-check: all providers at 100%%+ usage, rejecting (user=%s, task=%s)",
                auth.user_id,
                intent.task_type,
            )
            raise QuotaExhaustedError(
                "All providers are at or above 100% quota usage. "
                "Request rejected to prevent cost overrun. "
                "Try again next billing cycle or contact an admin."
            )

    def _select_model(
        self,
        intent: Intent,
        models: dict[str, ModelConfig],
        providers: dict[str, ProviderConfig],
        trace: Any,
    ) -> tuple[Any, str]:
        c = self._c
        with trace.span("conduit.route") as rs:
            rs.set_input({"task_type": intent.task_type, "agent": "routing"})
            try:
                from stronghold.types.errors import RoutingError

                selection = c.router.select(intent, models, providers, c.config.routing)
                model_to_use = selection.litellm_id
                best = selection.candidates[0] if selection.candidates else None
                rs.set_output(
                    {
                        "model": model_to_use,
                        "provider": selection.provider,
                        "score": selection.score,
                        "quality": best.quality if best else 0.0,
                        "effective_cost": best.effective_cost if best else 0.0,
                        "usage_pct": best.usage_pct if best else 0.0,
                        "tier": best.tier if best else "unknown",
                        "reason": selection.reason,
                        "candidates_count": len(selection.candidates),
                    }
                )
            except RoutingError:
                logger.warning("Router selection failed, using fallback", exc_info=True)
                selection = None
                model_to_use = next(
                    (
                        str(v.get("litellm_id", k)) if isinstance(v, dict) else v.litellm_id
                        for k, v in c.config.models.items()
                    ),
                    "auto",
                )
                rs.set_output({"model": model_to_use, "reason": "fallback"})
        return selection, model_to_use

    async def _check_data_sharing_consent(
        self,
        intent: Intent,
        models: dict[str, ModelConfig],
        providers_cfg: dict[str, ProviderConfig],
        consented: set[str],
        selection: Any,
        session_id: str | None,
        auth: Any,
        messages: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        _ds_unconsented = {
            k
            for k, v in providers_cfg.items()
            if v.data_sharing and v.status == "active" and k not in consented
        }
        if not _ds_unconsented or not session_id:
            return None

        try:
            full_selection = self._c.router.select(
                intent, models, providers_cfg, self._c.config.routing
            )
        except Exception:
            full_selection = None

        if not (
            full_selection
            and full_selection.provider in _ds_unconsented
            and (selection is None or full_selection.score > selection.score)
        ):
            return None

        ds_cfg = providers_cfg[full_selection.provider]
        notice = ds_cfg.data_sharing_notice or (
            f"The {full_selection.provider} provider shares your API data for model training."
        )
        self._consent_pending[session_id] = full_selection.provider
        if len(self._consent_pending) > self._MAX_CONSENT_ENTRIES:
            excess = len(self._consent_pending) - self._MAX_CONSENT_ENTRIES
            for old_key in list(self._consent_pending)[:excess]:
                del self._consent_pending[old_key]

        arbiter = self._fallback_agent("arbiter")
        consent_messages: list[dict[str, Any]] = [
            {
                "role": "system",
                "content": (
                    "Before answering the user's question, ask a brief "
                    "data sharing consent question. Keep it natural and "
                    "conversational.\n\n"
                    f"Provider: {full_selection.provider}\n"
                    f"Notice: {notice}\n\n"
                    "Ask whether they are OK with this provider seeing "
                    "their request data (for better quality/speed), or "
                    "if they prefer a privacy-respecting alternative.\n\n"
                    "Do NOT fulfill the original request yet."
                ),
            },
            *messages,
        ]
        response = await arbiter.handle(consent_messages, auth, session_id=session_id)
        return self._build_response(
            response_id="stronghold-consent-required",
            model=arbiter.identity.name,
            content=response.content,
            routing={
                "intent": {
                    "task_type": intent.task_type,
                    "classified_by": "consent_required",
                },
                "agent": arbiter.identity.name,
                "provider": full_selection.provider,
                "reason": f"data_sharing_consent_required: {full_selection.provider}",
            },
        )

    async def _preflight_coin_check(
        self,
        auth: Any,
        model_to_use: str,
        selection: Any,
        messages: list[dict[str, Any]],
    ) -> None:
        if not getattr(self._c, "coin_ledger", None):
            return
        estimated_input_tokens = self._estimate_tokens(messages)
        estimated_output_tokens = max(estimated_input_tokens, 256)
        await self._c.coin_ledger.ensure_can_afford(
            org_id=auth.org_id,
            team_id=auth.team_id,
            user_id=auth.user_id,
            model_used=model_to_use,
            provider=selection.provider if selection else "",
            input_tokens=estimated_input_tokens,
            output_tokens=estimated_output_tokens,
        )

    async def _is_sticky_followup(
        self, session_id: str | None, target_agent_name: str | None
    ) -> bool:
        if not session_id:
            return False
        async with self._session_lock:
            return (
                session_id in self._session_agents
                and self._session_agents[session_id] == target_agent_name
            )

    def _compute_sufficiency(
        self, intent: Intent, is_sticky_followup: bool, intent_hint: str
    ) -> Any:
        """Return SufficiencyResult or None when sufficiency check should be skipped."""
        if is_sticky_followup or intent_hint:
            return None

        from stronghold.agents.request_analyzer import (
            MissingDetail,
            SufficiencyResult,
            analyze_request_sufficiency,
        )

        _always_clarify = {"creative"}
        if intent.task_type in _always_clarify:
            return SufficiencyResult(
                sufficient=False,
                confidence=0.0,
                missing=[
                    MissingDetail(
                        "what",
                        "What kind of content? (e.g., email, story, blog post, poem)",
                    ),
                    MissingDetail(
                        "where",
                        "Who is the audience? (e.g., a client, your team, social media)",
                    ),
                    MissingDetail(
                        "how",
                        "What tone or style? (e.g., formal, casual, persuasive, heartfelt)",
                    ),
                    MissingDetail(
                        "context",
                        "What topic or theme? Any specific points to include?",
                    ),
                ],
            )
        return analyze_request_sufficiency(intent.user_text, task_type=intent.task_type)

    async def _run_sufficiency_check(
        self,
        intent: Intent,
        messages: list[dict[str, Any]],
        auth: Any,
        model_to_use: str,
        session_id: str | None,
        is_sticky_followup: bool,
        intent_hint: str,
        target_agent_name: str | None,
    ) -> tuple[Any, list[dict[str, Any]], dict[str, Any] | None]:
        """Return (agent, messages, early_response).

        early_response is non-None when the request lacks sufficient detail.
        """
        c = self._c
        if not target_agent_name or target_agent_name not in c.agents:
            return self._fallback_agent("arbiter"), messages, None

        agent = c.agents[target_agent_name]
        sufficiency = self._compute_sufficiency(intent, is_sticky_followup, intent_hint)

        if not sufficiency or sufficiency.sufficient:
            from stronghold.agents.context_filter import extract_task_context

            return agent, extract_task_context(messages, task_type=intent.task_type), None

        missing_qs = "\n".join(f"- {m.question}" for m in sufficiency.missing)
        guided_messages: list[dict[str, Any]] = [
            {
                "role": "system",
                "content": (
                    "The user's request needs more detail before you can proceed. "
                    "Do NOT attempt to fulfill the request yet. Instead, ask the "
                    "following clarifying questions in a friendly, conversational "
                    "way. Frame them as choices where possible.\n\n"
                    f"Missing details:\n{missing_qs}\n\n"
                    "Keep it brief — just ask the questions, don't write the content."
                ),
            },
            *messages,
        ]
        arbiter = self._fallback_agent("arbiter")
        response = await arbiter.handle(
            guided_messages,
            auth,
            session_id=session_id,
            model_override=model_to_use,
        )

        if session_id and target_agent_name:
            async with self._session_lock:
                self._session_agents[session_id] = target_agent_name

        return (
            agent,
            messages,
            self._build_response(
                response_id="stronghold-needs-detail",
                model=arbiter.identity.name,
                content=response.content,
                routing={
                    "intent": {
                        "task_type": intent.task_type,
                        "classified_by": "needs_detail",
                    },
                    "agent": arbiter.identity.name,
                    "reason": (
                        f"insufficient detail: {[m.category for m in sufficiency.missing]}"
                    ),
                    "missing": missing_qs,
                },
            ),
        )

    async def _save_session_stickiness(
        self, session_id: str | None, agent: Any
    ) -> None:
        if not session_id or agent.identity.name == "arbiter":
            return
        async with self._session_lock:
            self._session_agents[session_id] = agent.identity.name
            if len(self._session_agents) > self._MAX_STICKY_SESSIONS:
                excess = len(self._session_agents) - self._MAX_STICKY_SESSIONS
                for old_key in list(self._session_agents)[:excess]:
                    del self._session_agents[old_key]

    def _set_fallback_models(self, selection: Any, model_to_use: str) -> None:
        fallback_models: list[str] = []
        if selection and selection.candidates:
            fallback_models = [
                cand.litellm_id
                for cand in selection.candidates[1:4]
                if cand.litellm_id != model_to_use
            ]
        if fallback_models:
            logger.info("Fallback models: %s", fallback_models)
        self._c.llm._fallback_models = fallback_models  # type: ignore[attr-defined]

    async def _dispatch_agent(
        self,
        agent: Any,
        messages: list[dict[str, Any]],
        auth: Any,
        session_id: str | None,
        model_to_use: str,
        status_callback: Any,
        trace: Any,
    ) -> Any:
        try:
            return await agent.handle(
                messages,
                auth,
                session_id=session_id,
                model_override=model_to_use,
                status_callback=status_callback,
            )
        except Exception:
            logger.exception(
                "Agent dispatch failed: agent=%s model=%s",
                agent.identity.name,
                model_to_use,
            )
            trace.score("dispatch_error", 0.0, "Agent raised an exception")
            trace.end()
            raise

    def _finalize_trace(
        self,
        trace: Any,
        model_to_use: str,
        selection: Any,
        agent: Any,
        intent: Intent,
        session_id: str | None,
        start: float,
    ) -> None:
        import time as _time

        _elapsed_ms = round((_time.monotonic() - start) * 1000)
        _provider = selection.provider if selection else "unknown"
        trace.update(
            {
                "model": model_to_use,
                "provider": _provider,
                "agent": agent.identity.name,
                "intent": intent.task_type,
                "complexity": intent.complexity,
                "tier": intent.tier,
                "total_latency_ms": str(_elapsed_ms),
                "session_id": session_id or "",
                "is_sticky_followup": str(
                    session_id is not None and agent.identity.name != "default"
                ),
            }
        )
        trace.end()
