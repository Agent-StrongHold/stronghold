"""User-facing memory management: view, correct, forget.

Provides list/get/correct/forget/purge operations for episodic memories,
enforcing org-scoped tenant isolation on every operation.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from stronghold.memory.episodic.tiers import clamp_weight
from stronghold.types.memory import WEIGHT_BOUNDS, EpisodicMemory

if TYPE_CHECKING:
    from stronghold.memory.episodic.store import InMemoryEpisodicStore


def _memory_to_dict(mem: EpisodicMemory) -> dict[str, Any]:
    """Serialize an EpisodicMemory to a JSON-safe dict."""
    return {
        "memory_id": mem.memory_id,
        "tier": str(mem.tier),
        "content": mem.content,
        "weight": mem.weight,
        "scope": str(mem.scope),
        "source": mem.source,
        "user_id": mem.user_id or "",
        "org_id": mem.org_id,
        "team_id": mem.team_id,
        "agent_id": mem.agent_id or "",
        "reinforcement_count": mem.reinforcement_count,
        "created_at": mem.created_at.isoformat(),
        "last_accessed_at": mem.last_accessed_at.isoformat(),
    }


class MemoryManager:
    """User-facing memory management operations.

    All methods enforce org_id isolation — callers can only see/modify
    memories belonging to their organization.
    """

    def __init__(self, episodic_store: InMemoryEpisodicStore) -> None:
        self._store = episodic_store

    async def list_memories(
        self,
        user_id: str,
        org_id: str,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """List a user's episodic memories within their org."""
        results: list[dict[str, Any]] = []
        for mem in self._store._memories:
            if mem.deleted:
                continue
            if mem.user_id != user_id:
                continue
            if mem.org_id != org_id:
                continue
            results.append(_memory_to_dict(mem))
            if len(results) >= limit:
                break
        return results

    async def get_memory(
        self,
        memory_id: str,
        org_id: str,
    ) -> dict[str, Any] | None:
        """Retrieve a single memory by ID, org-scoped."""
        for mem in self._store._memories:
            if mem.memory_id == memory_id and mem.org_id == org_id and not mem.deleted:
                return _memory_to_dict(mem)
        return None

    async def correct_memory(
        self,
        memory_id: str,
        org_id: str,
        new_content: str,
    ) -> bool:
        """Update a memory's content and set weight to tier ceiling.

        User corrections are high-confidence — clamp weight to tier max.
        Returns True if found and updated, False if not found or wrong org.
        """
        for i, mem in enumerate(self._store._memories):
            if mem.memory_id != memory_id or mem.org_id != org_id or mem.deleted:
                continue
            bounds = WEIGHT_BOUNDS.get(mem.tier, (0.1, 1.0))
            ceiling = bounds[1]
            self._store._memories[i] = EpisodicMemory(
                memory_id=mem.memory_id,
                tier=mem.tier,
                content=new_content,
                weight=clamp_weight(mem.tier, ceiling),
                org_id=mem.org_id,
                team_id=mem.team_id,
                agent_id=mem.agent_id,
                user_id=mem.user_id,
                scope=mem.scope,
                source=mem.source,
                context=mem.context,
                reinforcement_count=mem.reinforcement_count,
                contradiction_count=mem.contradiction_count,
                created_at=mem.created_at,
                last_accessed_at=mem.last_accessed_at,
                deleted=mem.deleted,
            )
            return True
        return False

    async def forget_memory(
        self,
        memory_id: str,
        org_id: str,
    ) -> bool:
        """Soft-delete a single memory. Returns True if found and deleted."""
        for i, mem in enumerate(self._store._memories):
            if mem.memory_id != memory_id or mem.org_id != org_id or mem.deleted:
                continue
            self._store._memories[i] = EpisodicMemory(
                memory_id=mem.memory_id,
                tier=mem.tier,
                content=mem.content,
                weight=mem.weight,
                org_id=mem.org_id,
                team_id=mem.team_id,
                agent_id=mem.agent_id,
                user_id=mem.user_id,
                scope=mem.scope,
                source=mem.source,
                context=mem.context,
                reinforcement_count=mem.reinforcement_count,
                contradiction_count=mem.contradiction_count,
                created_at=mem.created_at,
                last_accessed_at=mem.last_accessed_at,
                deleted=True,
            )
            return True
        return False

    async def forget_by_keyword(
        self,
        user_id: str,
        org_id: str,
        keyword: str,
    ) -> int:
        """Bulk soft-delete memories matching a keyword. Returns count deleted."""
        keyword_lower = keyword.lower()
        count = 0
        for i, mem in enumerate(self._store._memories):
            if mem.deleted:
                continue
            if mem.user_id != user_id or mem.org_id != org_id:
                continue
            if keyword_lower not in mem.content.lower():
                continue
            self._store._memories[i] = EpisodicMemory(
                memory_id=mem.memory_id,
                tier=mem.tier,
                content=mem.content,
                weight=mem.weight,
                org_id=mem.org_id,
                team_id=mem.team_id,
                agent_id=mem.agent_id,
                user_id=mem.user_id,
                scope=mem.scope,
                source=mem.source,
                context=mem.context,
                reinforcement_count=mem.reinforcement_count,
                contradiction_count=mem.contradiction_count,
                created_at=mem.created_at,
                last_accessed_at=mem.last_accessed_at,
                deleted=True,
            )
            count += 1
        return count

    async def purge_user(
        self,
        user_id: str,
        org_id: str,
    ) -> int:
        """GDPR: soft-delete ALL memories for a user within an org. Returns count."""
        count = 0
        for i, mem in enumerate(self._store._memories):
            if mem.deleted:
                continue
            if mem.user_id != user_id or mem.org_id != org_id:
                continue
            self._store._memories[i] = EpisodicMemory(
                memory_id=mem.memory_id,
                tier=mem.tier,
                content=mem.content,
                weight=mem.weight,
                org_id=mem.org_id,
                team_id=mem.team_id,
                agent_id=mem.agent_id,
                user_id=mem.user_id,
                scope=mem.scope,
                source=mem.source,
                context=mem.context,
                reinforcement_count=mem.reinforcement_count,
                contradiction_count=mem.contradiction_count,
                created_at=mem.created_at,
                last_accessed_at=mem.last_accessed_at,
                deleted=True,
            )
            count += 1
        return count
