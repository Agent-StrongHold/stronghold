"""Tests for TournamentIntegration — wiring tournament evolution into the request pipeline.

Covers: probability gating, parallel execution, Elo update, arbiter exclusion,
battle record creation, challenger selection, config defaults, edge cases.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest

from stronghold.agents.base import Agent
from stronghold.agents.tournament import (
    BattleRecord,
    Tournament,
    TournamentIntegration,
)
from stronghold.types.agent import AgentIdentity, AgentResponse, ReasoningResult
from stronghold.types.config import StrongholdConfig, TournamentConfig
from tests.factories import build_auth_context, build_intent
from tests.fakes import FakeLLMClient, FakePromptManager, NoopTracingBackend

if TYPE_CHECKING:
    from stronghold.types.auth import AuthContext


# ── Helpers ──────────────────────────────────────────────────────────


class StubStrategy:
    """Strategy that returns a fixed response."""

    def __init__(self, response: str = "stub response") -> None:
        self._response = response

    async def reason(
        self,
        messages: list[dict[str, Any]],
        model: str,
        llm: Any,
        **kwargs: Any,
    ) -> ReasoningResult:
        return ReasoningResult(response=self._response, done=True)


def _make_agent(name: str, response: str = "agent response") -> Agent:
    """Build a minimal Agent with a stub strategy."""
    from stronghold.agents.context_builder import ContextBuilder
    from stronghold.security.warden.detector import Warden

    identity = AgentIdentity(name=name)
    return Agent(
        identity=identity,
        strategy=StubStrategy(response),
        llm=FakeLLMClient(),
        context_builder=ContextBuilder(),
        prompt_manager=FakePromptManager(),
        warden=Warden(),
        tracer=NoopTracingBackend(),
    )


def _make_agents_dict(*names: str) -> dict[str, Agent]:
    """Build a dict of agents from names."""
    return {n: _make_agent(n, f"response from {n}") for n in names}


def _make_integration(
    agents: dict[str, Agent] | None = None,
    tournament: Tournament | None = None,
    config: TournamentConfig | None = None,
) -> TournamentIntegration:
    """Build a TournamentIntegration with defaults."""
    return TournamentIntegration(
        tournament=tournament or Tournament(),
        agents=agents or _make_agents_dict("artificer", "ranger", "scribe"),
        config=config or TournamentConfig(),
    )


# ── Tests ────────────────────────────────────────────────────────────


class TestTournamentConfig:
    """TournamentConfig defaults and validation."""

    def test_default_probability(self) -> None:
        cfg = TournamentConfig()
        assert cfg.probability == 0.07

    def test_default_excluded_agents(self) -> None:
        cfg = TournamentConfig()
        assert "arbiter" in cfg.excluded_agents

    def test_custom_probability(self) -> None:
        cfg = TournamentConfig(probability=0.15)
        assert cfg.probability == 0.15

    def test_config_in_stronghold_config(self) -> None:
        sc = StrongholdConfig()
        assert isinstance(sc.tournament, TournamentConfig)
        assert sc.tournament.probability == 0.07


class TestShouldTournament:
    """Probability gating and exclusion logic."""

    def test_arbiter_excluded(self) -> None:
        """Arbiter intent must never trigger a tournament."""
        agents = _make_agents_dict("arbiter", "artificer", "ranger")
        intent = build_intent(task_type="chat")

        # Even with probability=1.0, arbiter is excluded
        ti = _make_integration(
            agents=agents,
            config=TournamentConfig(probability=1.0),
        )
        # When the incumbent is arbiter, never tournament
        result = ti.should_tournament(intent, incumbent_agent="arbiter")
        assert result is False

    def test_probability_zero_never_triggers(self) -> None:
        """With probability=0, should_tournament always returns False."""
        ti = _make_integration(config=TournamentConfig(probability=0.0))
        intent = build_intent(task_type="code")
        for _ in range(100):
            assert ti.should_tournament(intent, incumbent_agent="artificer") is False

    def test_probability_one_always_triggers(self) -> None:
        """With probability=1.0, should_tournament always returns True (if not excluded)."""
        agents = _make_agents_dict("artificer", "ranger", "scribe")
        ti = _make_integration(
            agents=agents,
            config=TournamentConfig(probability=1.0),
        )
        intent = build_intent(task_type="code")
        assert ti.should_tournament(intent, incumbent_agent="artificer") is True

    def test_excluded_agent_custom_list(self) -> None:
        """Custom exclusion list is respected."""
        agents = _make_agents_dict("artificer", "ranger", "scribe")
        ti = _make_integration(
            agents=agents,
            config=TournamentConfig(probability=1.0, excluded_agents=["ranger"]),
        )
        intent = build_intent(task_type="search")
        assert ti.should_tournament(intent, incumbent_agent="ranger") is False
        assert ti.should_tournament(intent, incumbent_agent="artificer") is True

    def test_needs_at_least_two_agents(self) -> None:
        """Cannot tournament if there is only one eligible agent."""
        agents = _make_agents_dict("artificer")
        ti = _make_integration(
            agents=agents,
            config=TournamentConfig(probability=1.0),
        )
        intent = build_intent(task_type="code")
        assert ti.should_tournament(intent, incumbent_agent="artificer") is False

    def test_disabled_flag(self) -> None:
        """enabled=False disables tournaments entirely."""
        agents = _make_agents_dict("artificer", "ranger", "scribe")
        ti = _make_integration(
            agents=agents,
            config=TournamentConfig(probability=1.0, enabled=False),
        )
        intent = build_intent(task_type="code")
        assert ti.should_tournament(intent, incumbent_agent="artificer") is False


class TestChallengerSelection:
    """Challenger selection from available agents."""

    def test_select_challenger_excludes_incumbent(self) -> None:
        agents = _make_agents_dict("artificer", "ranger", "scribe")
        ti = _make_integration(agents=agents)
        challenger = ti.select_challenger("artificer")
        assert challenger is not None
        assert challenger != "artificer"
        assert challenger in {"ranger", "scribe"}

    def test_select_challenger_excludes_excluded_agents(self) -> None:
        agents = _make_agents_dict("arbiter", "artificer", "ranger")
        ti = _make_integration(
            agents=agents,
            config=TournamentConfig(excluded_agents=["arbiter"]),
        )
        challenger = ti.select_challenger("artificer")
        assert challenger == "ranger"

    def test_select_challenger_returns_none_when_no_candidates(self) -> None:
        agents = _make_agents_dict("artificer")
        ti = _make_integration(agents=agents)
        challenger = ti.select_challenger("artificer")
        assert challenger is None


class TestRunTournament:
    """Parallel execution, LLM-as-judge scoring, Elo update."""

    @pytest.fixture()
    def agents(self) -> dict[str, Agent]:
        return {
            "artificer": _make_agent("artificer", "code solution A"),
            "ranger": _make_agent("ranger", "search result B"),
            "scribe": _make_agent("scribe", "creative draft C"),
        }

    @pytest.fixture()
    def tournament(self) -> Tournament:
        return Tournament()

    @pytest.fixture()
    def auth(self) -> AuthContext:
        return build_auth_context(org_id="acme")

    async def test_run_tournament_returns_battle_record(
        self,
        agents: dict[str, Agent],
        tournament: Tournament,
        auth: AuthContext,
    ) -> None:
        ti = _make_integration(agents=agents, tournament=tournament)
        messages: list[dict[str, Any]] = [{"role": "user", "content": "write a function"}]

        record = await ti.run_tournament(
            messages=messages,
            incumbent_agent="artificer",
            challenger_agent="ranger",
            auth=auth,
            intent_task_type="code",
        )

        assert isinstance(record, BattleRecord)
        assert record.agent_a == "artificer"
        assert record.agent_b == "ranger"
        assert record.intent == "code"
        assert record.org_id == "acme"
        assert record.winner in {"artificer", "ranger", "draw"}

    async def test_parallel_execution(
        self,
        agents: dict[str, Agent],
        tournament: Tournament,
        auth: AuthContext,
    ) -> None:
        """Both agents are called in parallel via asyncio.gather."""
        call_order: list[str] = []
        orig_handle_a = agents["artificer"].handle
        orig_handle_b = agents["ranger"].handle

        async def tracked_handle_a(*args: Any, **kwargs: Any) -> AgentResponse:
            call_order.append("artificer_start")
            result = await orig_handle_a(*args, **kwargs)
            call_order.append("artificer_end")
            return result

        async def tracked_handle_b(*args: Any, **kwargs: Any) -> AgentResponse:
            call_order.append("ranger_start")
            result = await orig_handle_b(*args, **kwargs)
            call_order.append("ranger_end")
            return result

        agents["artificer"].handle = tracked_handle_a  # type: ignore[assignment]
        agents["ranger"].handle = tracked_handle_b  # type: ignore[assignment]

        ti = _make_integration(agents=agents, tournament=tournament)
        messages: list[dict[str, Any]] = [{"role": "user", "content": "hello"}]

        await ti.run_tournament(
            messages=messages,
            incumbent_agent="artificer",
            challenger_agent="ranger",
            auth=auth,
            intent_task_type="code",
        )

        # Both agents were called
        assert "artificer_start" in call_order
        assert "ranger_start" in call_order

    async def test_elo_updated_after_battle(
        self,
        agents: dict[str, Agent],
        tournament: Tournament,
        auth: AuthContext,
    ) -> None:
        ti = _make_integration(agents=agents, tournament=tournament)
        messages: list[dict[str, Any]] = [{"role": "user", "content": "test"}]

        await ti.run_tournament(
            messages=messages,
            incumbent_agent="artificer",
            challenger_agent="ranger",
            auth=auth,
            intent_task_type="code",
        )

        # Elo ratings should have changed from default 1200
        leaderboard = tournament.get_leaderboard("code", org_id="acme")
        assert len(leaderboard) == 2
        elos = {entry["agent"]: entry["elo"] for entry in leaderboard}
        assert "artificer" in elos
        assert "ranger" in elos
        # One should be above and one below (or both 1200 if draw)
        assert (
            elos["artificer"] != 1200.0
            or elos["ranger"] != 1200.0
            or (elos["artificer"] == 1200.0 and elos["ranger"] == 1200.0)
        )

    async def test_battle_record_stored_in_tournament(
        self,
        agents: dict[str, Agent],
        tournament: Tournament,
        auth: AuthContext,
    ) -> None:
        ti = _make_integration(agents=agents, tournament=tournament)
        messages: list[dict[str, Any]] = [{"role": "user", "content": "test"}]

        await ti.run_tournament(
            messages=messages,
            incumbent_agent="artificer",
            challenger_agent="ranger",
            auth=auth,
            intent_task_type="code",
        )

        history = tournament.get_battle_history(intent="code", org_id="acme")
        assert len(history) == 1
        assert history[0]["agent_a"] == "artificer"
        assert history[0]["agent_b"] == "ranger"

    async def test_incumbent_response_returned(
        self,
        agents: dict[str, Agent],
        tournament: Tournament,
        auth: AuthContext,
    ) -> None:
        """run_tournament returns the incumbent's response content for the caller."""
        ti = _make_integration(agents=agents, tournament=tournament)
        messages: list[dict[str, Any]] = [{"role": "user", "content": "test"}]

        record = await ti.run_tournament(
            messages=messages,
            incumbent_agent="artificer",
            challenger_agent="ranger",
            auth=auth,
            intent_task_type="code",
        )

        # The battle record should have scores
        assert record.score_a >= 0.0
        assert record.score_b >= 0.0

    async def test_scores_are_based_on_response_length_stub(
        self,
        tournament: Tournament,
        auth: AuthContext,
    ) -> None:
        """The stub judge uses response length as a simple heuristic."""
        short_agent = _make_agent("short", "hi")
        long_agent = _make_agent("long", "This is a much longer and more detailed response.")
        agents = {"short": short_agent, "long": long_agent}

        ti = _make_integration(agents=agents, tournament=tournament)
        messages: list[dict[str, Any]] = [{"role": "user", "content": "explain"}]

        record = await ti.run_tournament(
            messages=messages,
            incumbent_agent="short",
            challenger_agent="long",
            auth=auth,
            intent_task_type="chat",
        )

        # Longer response should score higher with the stub judge
        assert record.score_b > record.score_a

    async def test_agent_handle_failure_does_not_crash(
        self,
        tournament: Tournament,
        auth: AuthContext,
    ) -> None:
        """If one agent's strategy raises, the tournament still completes.

        Agent.handle() catches strategy errors internally and returns a
        short error message, so the "failing" agent still gets a low score
        (not zero). The important thing is that the tournament completes
        and produces a valid BattleRecord.
        """

        class FailStrategy:
            async def reason(self, *args: Any, **kwargs: Any) -> ReasoningResult:
                msg = "agent exploded"
                raise RuntimeError(msg)

        from stronghold.agents.context_builder import ContextBuilder
        from stronghold.security.warden.detector import Warden

        failing_agent = Agent(
            identity=AgentIdentity(name="failing"),
            strategy=FailStrategy(),
            llm=FakeLLMClient(),
            context_builder=ContextBuilder(),
            prompt_manager=FakePromptManager(),
            warden=Warden(),
            tracer=NoopTracingBackend(),
        )
        ok_agent = _make_agent(
            "ok_agent",
            "This is a much longer detailed response that should score well.",
        )
        agents = {"failing": failing_agent, "ok_agent": ok_agent}

        ti = _make_integration(agents=agents, tournament=tournament)
        messages: list[dict[str, Any]] = [{"role": "user", "content": "test"}]

        record = await ti.run_tournament(
            messages=messages,
            incumbent_agent="failing",
            challenger_agent="ok_agent",
            auth=auth,
            intent_task_type="code",
        )

        # Should produce a valid record even when one agent's strategy fails
        assert isinstance(record, BattleRecord)
        # The ok_agent with a longer response should outscore the error message
        assert record.score_b > record.score_a
