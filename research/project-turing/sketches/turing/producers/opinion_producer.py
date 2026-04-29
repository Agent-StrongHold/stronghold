"""OpinionFormer: promotes reinforced observations into OPINION memories.

Gathers high-weight I_DID observations that share a topic (grouped by
intent_at_time prefix). If enough distinct observations reinforce the same
theme, produces an OPINION-tier memory that represents a settled view.
"""

from __future__ import annotations

import logging
import random
from collections import Counter
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from ..motivation import BacklogItem, Motivation
from ..reactor import Reactor
from ..repo import Repo
from ..runtime.providers.base import Provider
from ..self_repo import SelfRepo
from ..types import EpisodicMemory, MemoryTier, SourceKind

logger = logging.getLogger("turing.producers.opinion")

BASE_CADENCE_TICKS: int = 120_000
MIN_OBSERVATIONS = 3
MIN_WEIGHT = 0.6
LOOKBACK_HOURS = 48


class OpinionFormer:
    def __init__(
        self,
        *,
        motivation: Motivation,
        reactor: Reactor,
        repo: Repo,
        self_repo: SelfRepo,
        self_id: str,
        provider: Provider,
    ) -> None:
        self._motivation = motivation
        self._reactor = reactor
        self._repo = repo
        self._self_repo = self_repo
        self._self_id = self_id
        self._provider = provider
        self._last_submitted_tick = 0
        motivation.register_dispatch("opinion_formation", self._on_dispatch)
        reactor.register(self.on_tick)

    def on_tick(self, tick: int) -> None:
        if tick - self._last_submitted_tick < BASE_CADENCE_TICKS:
            return
        cutoff = datetime.now(UTC) - timedelta(hours=LOOKBACK_HOURS)
        recent = list(
            self._repo.find(
                self_id=self._self_id,
                source=SourceKind.I_DID,
                include_superseded=False,
                created_after=cutoff,
            )
        )
        candidates = [
            m for m in recent if m.weight >= MIN_WEIGHT and m.tier == MemoryTier.OBSERVATION
        ]
        if len(candidates) < MIN_OBSERVATIONS:
            return
        topic_counts: Counter[str] = Counter()
        topic_memories: dict[str, list[EpisodicMemory]] = {}
        for m in candidates:
            intent = m.intent_at_time.split("-")[0] if m.intent_at_time else "general"
            topic_counts[intent] += 1
            topic_memories.setdefault(intent, []).append(m)
        strong_topics = {t for t, c in topic_counts.items() if c >= MIN_OBSERVATIONS}
        if not strong_topics:
            return
        topic = random.choice(list(strong_topics))
        mems = topic_memories[topic]
        self._last_submitted_tick = tick
        self._motivation.insert(
            BacklogItem(
                item_id=str(uuid4()),
                class_=11,
                kind="opinion_formation",
                payload={
                    "self_id": self._self_id,
                    "topic": topic,
                    "observation_count": len(mems),
                    "summaries": [m.content[:150] for m in mems[-5:]],
                },
                fit={"curiosity": 0.4, "diligence": 0.5},
                readiness=lambda s: True,
                cost_estimate_tokens=1_000,
            )
        )

    def _on_dispatch(self, item: BacklogItem, chosen_pool: str) -> None:
        payload = item.payload or {}
        topic = payload.get("topic", "general")
        summaries = payload.get("summaries", [])
        count = payload.get("observation_count", 0)
        if not summaries:
            return
        prompt = (
            f"You have made {count} observations about '{topic}' recently:\n\n"
            + "\n".join(f"- {s}" for s in summaries)
            + "\n\nBased on these observations, form an opinion. "
            "State it plainly in 2-3 sentences. No hedging, no disclaimers. "
            "Say what you actually think."
        )
        try:
            reply = self._provider.complete(prompt, max_tokens=200)
        except Exception:
            logger.exception("opinion formation LLM call failed")
            return
        content = reply.strip()
        if not content:
            return
        mem = EpisodicMemory(
            memory_id=str(uuid4()),
            self_id=self._self_id,
            content=content[:2000],
            tier=MemoryTier.OPINION,
            source=SourceKind.I_DID,
            weight=0.7,
            intent_at_time=f"opinion-{topic}",
            created_at=datetime.now(UTC),
        )
        self._repo.insert(mem)
        logger.info("formed opinion on '%s' from %d observations", topic, count)
