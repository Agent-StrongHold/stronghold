"""Tests for memory scope filtering (build_scope_filter).

Validates the hierarchical scope filter builder:
  GLOBAL > ORGANIZATION > TEAM > USER > AGENT > SESSION

Each test uses real types — no mocks per project rules.
"""

from __future__ import annotations

from stronghold.memory.scopes import build_scope_filter
from stronghold.types.memory import MemoryScope


class TestGlobalScope:
    """Global scope is always present regardless of arguments."""

    def test_global_always_included_with_no_args(self) -> None:
        result = build_scope_filter()
        assert (MemoryScope.GLOBAL, None) in result

    def test_global_always_included_with_all_args(self) -> None:
        result = build_scope_filter(
            agent_id="agent-1",
            user_id="user-1",
            team_id="team-1",
            org_id="org-1",
        )
        assert (MemoryScope.GLOBAL, None) in result

    def test_global_is_first_filter(self) -> None:
        result = build_scope_filter(org_id="org-1", team_id="team-1")
        assert result[0] == (MemoryScope.GLOBAL, None)


class TestOrganizationScope:
    """Organization scope only appears when org_id is provided."""

    def test_org_scope_included_when_org_id_provided(self) -> None:
        result = build_scope_filter(org_id="acme-corp")
        assert (MemoryScope.ORGANIZATION, "acme-corp") in result

    def test_org_scope_excluded_when_no_org_id(self) -> None:
        result = build_scope_filter(user_id="user-1")
        scopes = [s for s, _ in result]
        assert MemoryScope.ORGANIZATION not in scopes

    def test_org_scope_excluded_for_empty_org_id(self) -> None:
        result = build_scope_filter(org_id="")
        scopes = [s for s, _ in result]
        assert MemoryScope.ORGANIZATION not in scopes


class TestTeamScope:
    """Team scope only appears when team_id is provided."""

    def test_team_scope_included_when_team_id_provided(self) -> None:
        result = build_scope_filter(team_id="backend-team")
        assert (MemoryScope.TEAM, "backend-team") in result

    def test_team_scope_excluded_when_no_team_id(self) -> None:
        result = build_scope_filter(org_id="org-1")
        scopes = [s for s, _ in result]
        assert MemoryScope.TEAM not in scopes


class TestUserScope:
    """User scope only appears when user_id is provided."""

    def test_user_scope_included_when_user_id_provided(self) -> None:
        result = build_scope_filter(user_id="alice")
        assert (MemoryScope.USER, "alice") in result

    def test_user_scope_excluded_when_no_user_id(self) -> None:
        result = build_scope_filter(team_id="team-1")
        scopes = [s for s, _ in result]
        assert MemoryScope.USER not in scopes


class TestAgentScope:
    """Agent scope only appears when agent_id is provided."""

    def test_agent_scope_included_when_agent_id_provided(self) -> None:
        result = build_scope_filter(agent_id="artificer")
        assert (MemoryScope.AGENT, "artificer") in result

    def test_agent_scope_excluded_when_no_agent_id(self) -> None:
        result = build_scope_filter(user_id="alice")
        scopes = [s for s, _ in result]
        assert MemoryScope.AGENT not in scopes


class TestSessionScope:
    """Session scope is never included by build_scope_filter.

    Session filtering is handled at a different layer (session store),
    so build_scope_filter never emits SESSION tuples.
    """

    def test_session_scope_never_in_output(self) -> None:
        result = build_scope_filter(agent_id="a", user_id="u", team_id="t", org_id="o")
        scopes = [s for s, _ in result]
        assert MemoryScope.SESSION not in scopes


class TestScopeHierarchy:
    """Scope ordering follows the hierarchy: GLOBAL > ORG > TEAM > USER > AGENT."""

    def test_full_hierarchy_order(self) -> None:
        result = build_scope_filter(
            org_id="org-1",
            team_id="team-1",
            user_id="user-1",
            agent_id="agent-1",
        )
        scopes = [s for s, _ in result]
        expected_order = [
            MemoryScope.GLOBAL,
            MemoryScope.ORGANIZATION,
            MemoryScope.TEAM,
            MemoryScope.USER,
            MemoryScope.AGENT,
        ]
        assert scopes == expected_order

    def test_hierarchy_length_with_all_params(self) -> None:
        result = build_scope_filter(org_id="o", team_id="t", user_id="u", agent_id="a")
        assert len(result) == 5


class TestEmptyScope:
    """Calling with no arguments returns only the global filter."""

    def test_no_args_returns_only_global(self) -> None:
        result = build_scope_filter()
        assert result == [(MemoryScope.GLOBAL, None)]

    def test_no_args_length_is_one(self) -> None:
        result = build_scope_filter()
        assert len(result) == 1


class TestMultipleScopesCombine:
    """Partial argument combinations produce correct filter sets."""

    def test_org_and_user_without_team(self) -> None:
        result = build_scope_filter(org_id="org-1", user_id="user-1")
        scopes = [s for s, _ in result]
        assert MemoryScope.GLOBAL in scopes
        assert MemoryScope.ORGANIZATION in scopes
        assert MemoryScope.USER in scopes
        assert MemoryScope.TEAM not in scopes
        assert MemoryScope.AGENT not in scopes

    def test_team_and_agent_without_org_or_user(self) -> None:
        result = build_scope_filter(team_id="team-1", agent_id="ranger")
        expected = [
            (MemoryScope.GLOBAL, None),
            (MemoryScope.TEAM, "team-1"),
            (MemoryScope.AGENT, "ranger"),
        ]
        assert result == expected

    def test_only_agent_id(self) -> None:
        result = build_scope_filter(agent_id="scribe")
        assert result == [
            (MemoryScope.GLOBAL, None),
            (MemoryScope.AGENT, "scribe"),
        ]


class TestScopeValues:
    """Values in the filter tuples match exactly what was passed in."""

    def test_values_are_preserved(self) -> None:
        result = build_scope_filter(
            org_id="acme-corp",
            team_id="platform",
            user_id="blake@acme.com",
            agent_id="artificer",
        )
        values = {s: v for s, v in result}
        assert values[MemoryScope.GLOBAL] is None
        assert values[MemoryScope.ORGANIZATION] == "acme-corp"
        assert values[MemoryScope.TEAM] == "platform"
        assert values[MemoryScope.USER] == "blake@acme.com"
        assert values[MemoryScope.AGENT] == "artificer"

    def test_none_values_excluded(self) -> None:
        """Passing None explicitly still excludes the scope."""
        result = build_scope_filter(org_id=None, team_id=None, user_id=None, agent_id=None)
        assert result == [(MemoryScope.GLOBAL, None)]
