from __future__ import annotations

import json
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path

import asyncpg

from .protocols import ImmutableViolation, RepoError, WisdomInvariantViolation
from .tiers import WEIGHT_BOUNDS, clamp_weight
from .types import DURABLE_TIERS, EpisodicMemory, MemoryTier, SourceKind

_NON_DURABLE_TIERS: frozenset[MemoryTier] = frozenset(MemoryTier) - DURABLE_TIERS

_INSERT_EPISODIC_SQL = """
INSERT INTO episodic_memory (
    memory_id, self_id, tier, source, content, weight,
    affect, confidence_at_creation, surprise_delta, intent_at_time,
    supersedes, superseded_by, origin_episode_id, immutable,
    reinforcement_count, contradiction_count, deleted,
    created_at, last_accessed_at, context
) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18,$19,$20)
"""

_INSERT_DURABLE_SQL = """
INSERT INTO durable_memory (
    memory_id, self_id, tier, source, content, weight,
    affect, confidence_at_creation, surprise_delta, intent_at_time,
    supersedes, superseded_by, origin_episode_id, immutable,
    reinforcement_count, contradiction_count,
    created_at, last_accessed_at, context
) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18,$19)
"""


class PostgresRepo:
    def __init__(self, dsn: str) -> None:
        self._dsn = dsn
        self._pool: asyncpg.Pool | None = None

    async def _get_pool(self) -> asyncpg.Pool:
        if self._pool is None:
            self._pool = await asyncpg.create_pool(self._dsn)
        return self._pool

    async def create_tables(self) -> None:
        pool = await self._get_pool()
        schema_path = Path(__file__).with_name("postgres_schema.sql")
        schema_sql = schema_path.read_text()
        statements = self._split_schema(schema_sql)
        async with pool.acquire() as conn:
            async with conn.transaction():
                for stmt in statements:
                    await conn.execute(stmt)

    async def close(self) -> None:
        if self._pool is not None:
            await self._pool.close()
            self._pool = None

    async def insert(self, memory: EpisodicMemory) -> str:
        if not self._weight_in_bounds(memory):
            lo, hi = WEIGHT_BOUNDS[memory.tier]
            raise RepoError(
                f"weight {memory.weight} outside tier bounds [{lo}, {hi}] for {memory.tier.value}"
            )
        if memory.tier == MemoryTier.WISDOM:
            await self._validate_wisdom_invariants(memory)
        is_episodic = memory.tier not in DURABLE_TIERS
        table = "episodic_memory" if is_episodic else "durable_memory"
        sql = _INSERT_EPISODIC_SQL if is_episodic else _INSERT_DURABLE_SQL
        row = self._row_for_insert(memory, is_episodic)
        pool = await self._get_pool()
        try:
            async with pool.acquire() as conn:
                await conn.execute(sql, *row)
        except Exception as e:
            raise RepoError(str(e)) from e
        return memory.memory_id

    async def get(self, memory_id: str) -> EpisodicMemory | None:
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            row = await self._fetch_by_id(conn, memory_id, "durable_memory")
            if row is not None:
                return self._row_to_memory(row, include_deleted=False)
            row = await self._fetch_by_id(conn, memory_id, "episodic_memory")
            if row is not None:
                return self._row_to_memory(row, include_deleted=True)
        return None

    async def get_head(self, memory_id: str) -> EpisodicMemory | None:
        current = await self.get(memory_id)
        while current is not None and current.superseded_by is not None:
            nxt = await self.get(current.superseded_by)
            if nxt is None:
                break
            current = nxt
        return current

    async def walk_lineage(self, memory_id: str) -> list[EpisodicMemory]:
        chain: list[EpisodicMemory] = []
        current = await self.get(memory_id)
        while current is not None:
            chain.append(current)
            if current.supersedes is None:
                break
            current = await self.get(current.supersedes)
        chain.reverse()
        return chain

    async def set_superseded_by(self, memory_id: str, successor_id: str) -> None:
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            for table in ("durable_memory", "episodic_memory"):
                row = await conn.fetchrow(
                    f"SELECT superseded_by FROM {table} WHERE memory_id = $1",
                    memory_id,
                )
                if row is None:
                    continue
                if row["superseded_by"] is not None:
                    raise ImmutableViolation(f"superseded_by already set on {memory_id}")
                await conn.execute(
                    f"UPDATE {table} SET superseded_by = $1 WHERE memory_id = $2",
                    successor_id,
                    memory_id,
                )
                return
        raise RepoError(f"no memory with id {memory_id}")

    async def increment_contradiction_count(self, memory_id: str) -> None:
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            for table in ("durable_memory", "episodic_memory"):
                row = await conn.fetchrow(
                    f"SELECT memory_id FROM {table} WHERE memory_id = $1",
                    memory_id,
                )
                if row is not None:
                    await conn.execute(
                        f"UPDATE {table} SET contradiction_count = "
                        f"contradiction_count + 1 WHERE memory_id = $1",
                        memory_id,
                    )
                    return
        raise RepoError(f"no memory with id {memory_id}")

    async def touch_access(self, memory_id: str) -> None:
        now = datetime.now(UTC)
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            for table in ("durable_memory", "episodic_memory"):
                await conn.execute(
                    f"UPDATE {table} SET last_accessed_at = $1 WHERE memory_id = $2",
                    now,
                    memory_id,
                )

    async def decay_weight(self, memory_id: str, delta: float) -> float:
        m = await self.get(memory_id)
        if m is None:
            raise RepoError(f"no memory with id {memory_id}")
        new_weight = clamp_weight(m.tier, m.weight - delta)
        table = "durable_memory" if m.tier in DURABLE_TIERS else "episodic_memory"
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                f"UPDATE {table} SET weight = $1 WHERE memory_id = $2",
                new_weight,
                memory_id,
            )
        return new_weight

    async def soft_delete(self, memory_id: str) -> None:
        m = await self.get(memory_id)
        if m is None:
            raise RepoError(f"no memory with id {memory_id}")
        if m.immutable or m.tier in DURABLE_TIERS:
            raise ImmutableViolation(f"cannot delete immutable/durable memory {memory_id}")
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE episodic_memory SET deleted = TRUE WHERE memory_id = $1",
                memory_id,
            )

    async def find(
        self,
        *,
        self_id: str | None = None,
        tier: MemoryTier | None = None,
        tiers: Iterable[MemoryTier] | None = None,
        source: SourceKind | None = None,
        sources: Iterable[SourceKind] | None = None,
        intent_at_time: str | None = None,
        created_after: datetime | None = None,
        include_deleted: bool = False,
        include_superseded: bool = True,
    ) -> list[EpisodicMemory]:
        all_tiers = {tier} if tier is not None else set(tiers) if tiers else set(MemoryTier)
        durable = all_tiers & DURABLE_TIERS
        nondurable = all_tiers - DURABLE_TIERS
        results: list[EpisodicMemory] = []
        pool = await self._get_pool()
        if durable:
            results.extend(
                await self._find_in_table(
                    pool,
                    "durable_memory",
                    self_id=self_id,
                    tiers=durable,
                    source=source,
                    sources=sources,
                    intent_at_time=intent_at_time,
                    created_after=created_after,
                    include_deleted=False,
                    include_superseded=include_superseded,
                )
            )
        if nondurable:
            results.extend(
                await self._find_in_table(
                    pool,
                    "episodic_memory",
                    self_id=self_id,
                    tiers=nondurable,
                    source=source,
                    sources=sources,
                    intent_at_time=intent_at_time,
                    created_after=created_after,
                    include_deleted=include_deleted,
                    include_superseded=include_superseded,
                )
            )
        return results

    async def count_by_tier(self, tier: MemoryTier) -> int:
        table = "durable_memory" if tier in DURABLE_TIERS else "episodic_memory"
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                f"SELECT COUNT(*) AS cnt FROM {table} WHERE tier = $1",
                tier.value,
            )
        return int(row["cnt"])

    @staticmethod
    def _weight_in_bounds(memory: EpisodicMemory) -> bool:
        lo, hi = WEIGHT_BOUNDS[memory.tier]
        return lo <= memory.weight <= hi

    async def _validate_wisdom_invariants(self, memory: EpisodicMemory) -> None:
        if not memory.origin_episode_id:
            raise WisdomInvariantViolation(
                "WISDOM requires origin_episode_id pointing at a dream session marker"
            )
        lineage = memory.context.get("supersedes_via_lineage") if memory.context else None
        if not isinstance(lineage, list) or not lineage:
            raise WisdomInvariantViolation(
                "WISDOM requires context['supersedes_via_lineage'] as a non-empty list"
            )
        for mid in lineage:
            if await self.get(str(mid)) is None:
                raise WisdomInvariantViolation(
                    f"WISDOM lineage references unknown memory_id: {mid}"
                )
        if memory.supersedes is not None:
            prior = await self.get(memory.supersedes)
            if prior is not None and prior.tier == MemoryTier.WISDOM:
                raise WisdomInvariantViolation(
                    "WISDOM may not supersede existing WISDOM; extend instead"
                )
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            marker_row = await conn.fetchrow(
                "SELECT tier, source, content FROM episodic_memory "
                "WHERE memory_id = $1 OR origin_episode_id = $1 LIMIT 1",
                memory.origin_episode_id,
            )
        if marker_row is None:
            raise WisdomInvariantViolation(
                f"WISDOM origin_episode_id {memory.origin_episode_id} "
                f"does not resolve to any marker"
            )

    @staticmethod
    def _row_for_insert(m: EpisodicMemory, include_deleted: bool) -> tuple:
        base = (
            m.memory_id,
            m.self_id,
            m.tier.value,
            m.source.value,
            m.content,
            m.weight,
            m.affect,
            m.confidence_at_creation,
            m.surprise_delta,
            m.intent_at_time,
            m.supersedes,
            m.superseded_by,
            m.origin_episode_id,
            m.immutable,
            m.reinforcement_count,
            m.contradiction_count,
        )
        if include_deleted:
            base = base + (m.deleted,)
        return base + (
            m.created_at,
            m.last_accessed_at,
            json.dumps(m.context) if m.context else None,
        )

    @staticmethod
    async def _fetch_by_id(
        conn: asyncpg.Connection | asyncpg.pool.PoolConnectionProxy,
        memory_id: str,
        table: str,
    ) -> asyncpg.Record | None:
        return await conn.fetchrow(f"SELECT * FROM {table} WHERE memory_id = $1", memory_id)

    @staticmethod
    def _row_to_memory(row: asyncpg.Record, *, include_deleted: bool) -> EpisodicMemory:
        ctx = row["context"]
        return EpisodicMemory(
            memory_id=row["memory_id"],
            self_id=row["self_id"],
            tier=MemoryTier(row["tier"]),
            source=SourceKind(row["source"]),
            content=row["content"],
            weight=row["weight"],
            affect=row["affect"],
            confidence_at_creation=row["confidence_at_creation"],
            surprise_delta=row["surprise_delta"],
            intent_at_time=row["intent_at_time"],
            supersedes=row["supersedes"],
            superseded_by=row["superseded_by"],
            origin_episode_id=row["origin_episode_id"],
            immutable=row["immutable"],
            reinforcement_count=row["reinforcement_count"],
            contradiction_count=row["contradiction_count"],
            deleted=bool(row["deleted"]) if include_deleted else False,
            created_at=row["created_at"],
            last_accessed_at=row["last_accessed_at"],
            context=json.loads(ctx) if isinstance(ctx, str) else (ctx if ctx is not None else {}),
        )

    async def _find_in_table(
        self,
        pool: asyncpg.Pool,
        table: str,
        *,
        self_id: str | None,
        tiers: set[MemoryTier],
        source: SourceKind | None,
        sources: Iterable[SourceKind] | None,
        intent_at_time: str | None,
        created_after: datetime | None,
        include_deleted: bool,
        include_superseded: bool,
    ) -> list[EpisodicMemory]:
        where: list[str] = []
        params: list[object] = []
        n = 1
        if self_id is not None:
            where.append(f"self_id = ${n}")
            params.append(self_id)
            n += 1
        if tiers:
            placeholders = ",".join(f"${n + i}" for i in range(len(tiers)))
            where.append(f"tier IN ({placeholders})")
            params.extend(t.value for t in tiers)
            n += len(tiers)
        if source is not None:
            where.append(f"source = ${n}")
            params.append(source.value)
            n += 1
        elif sources is not None:
            sources_list = list(sources)
            placeholders = ",".join(f"${n + i}" for i in range(len(sources_list)))
            where.append(f"source IN ({placeholders})")
            params.extend(s.value for s in sources_list)
            n += len(sources_list)
        if intent_at_time is not None:
            where.append(f"intent_at_time = ${n}")
            params.append(intent_at_time)
            n += 1
        if created_after is not None:
            where.append(f"created_at > ${n}")
            params.append(created_after)
            n += 1
        if not include_deleted and table == "episodic_memory":
            where.append("deleted = FALSE")
        if not include_superseded:
            where.append("superseded_by IS NULL")

        sql = f"SELECT * FROM {table}"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY created_at DESC"

        async with pool.acquire() as conn:
            rows = await conn.fetch(sql, *params)
        return [
            self._row_to_memory(row, include_deleted=(table == "episodic_memory")) for row in rows
        ]

    @staticmethod
    def _split_schema(sql: str) -> list[str]:
        stmts: list[str] = []
        buf: list[str] = []
        in_dollar = False
        for line in sql.splitlines():
            stripped = line.strip()
            if not in_dollar and stripped.startswith("--"):
                continue
            count = line.count("$$")
            if count % 2 == 1:
                in_dollar = not in_dollar
            buf.append(line)
            if not in_dollar and stripped.endswith(";"):
                stmt = "\n".join(buf).strip()
                if stmt:
                    stmts.append(stmt)
                buf = []
        remainder = "\n".join(buf).strip()
        if remainder:
            stmts.append(remainder)
        return stmts


__all__ = ["PostgresRepo"]
