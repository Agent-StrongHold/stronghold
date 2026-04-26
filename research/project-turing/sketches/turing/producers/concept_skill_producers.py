"""ConceptInventor: autonomous concept invention driven by dominant drive.

Spec 35, P9. Every 90k ticks, gated by any drive >= 0.5. Asks the LLM
to invent or explore a concept in a domain chosen by the dominant drive.
"""

from __future__ import annotations

import logging
import random
from datetime import UTC, datetime
from uuid import uuid4

from ..drives import compute_drives
from ..motivation import BacklogItem, Motivation
from ..reactor import Reactor
from ..repo import Repo
from ..runtime.providers.base import Provider
from ..self_model import Mood
from ..self_repo import SelfRepo
from ..types import EpisodicMemory, MemoryTier, SourceKind

logger = logging.getLogger("turing.producers.concept_inventor")

BASE_CADENCE_TICKS: int = 90_000
DRIVE_FLOOR: float = 0.5

_DRIVE_DOMAINS: dict[str, list[str]] = {
    "curiosity": ["knowledge", "understanding", "discovery", "truth"],
    "social_need": ["friendship", "connection", "trust", "empathy"],
    "creative_urge": ["art", "beauty", "expression", "imagination"],
    "anxiety": ["safety", "resilience", "coping", "uncertainty"],
    "diligence": ["mastery", "discipline", "craft", "excellence"],
    "restlessness": ["freedom", "change", "growth", "adventure"],
}


class ConceptInventor:
    def __init__(
        self,
        *,
        motivation: Motivation,
        reactor: Reactor,
        repo: Repo,
        self_repo: SelfRepo,
        self_id: str,
        facet_scores: dict[str, float],
        provider: Provider,
    ) -> None:
        self._motivation = motivation
        self._reactor = reactor
        self._repo = repo
        self._self_repo = self_repo
        self._self_id = self_id
        self._facet_scores = facet_scores
        self._provider = provider
        self._last_submitted_tick = 0
        self._rng = random.Random()
        motivation.register_dispatch("concept_invention", self._on_dispatch)
        reactor.register(self.on_tick)

    def _current_mood(self) -> Mood:
        try:
            return self._self_repo.get_mood(self._self_id)
        except KeyError:
            return Mood(
                self_id=self._self_id,
                valence=0.0,
                arousal=0.3,
                focus=0.5,
                last_tick_at=datetime.now(UTC),
            )

    def on_tick(self, tick: int) -> None:
        mood = self._current_mood()
        drives = compute_drives(self._facet_scores, mood)
        best_drive = max(drives, key=lambda d: drives[d])
        best_val = drives[best_drive]
        if best_val < DRIVE_FLOOR:
            return
        if tick - self._last_submitted_tick < BASE_CADENCE_TICKS:
            return
        self._last_submitted_tick = tick
        domain = self._rng.choice(_DRIVE_DOMAINS.get(best_drive, ["meaning"]))
        self._motivation.insert(
            BacklogItem(
                item_id=str(uuid4()),
                class_=9,
                kind="concept_invention",
                payload={
                    "self_id": self._self_id,
                    "domain": domain,
                    "drive": best_drive,
                    "intensity": best_val,
                },
                fit={best_drive: 0.6},
                readiness=lambda s: True,
                cost_estimate_tokens=2_000,
            )
        )

    def _on_dispatch(self, item: BacklogItem, chosen_pool: str) -> None:
        payload = item.payload or {}
        domain = payload.get("domain", "meaning")
        drive = payload.get("drive", "curiosity")
        personality_lines = " ".join(
            f"{k}={v:.2f}" for k, v in list(self._facet_scores.items())[:6]
        )
        prompt = (
            "You are Project Turing, an autonomous AI agent reflecting on your "
            "inner life. You have the following personality facets: "
            f"{personality_lines}\n\n"
            f"Your dominant drive right now is {drive}. In the domain of "
            f"**{domain}**, invent or explore a concept that matters to you.\n\n"
            "Respond in this exact format:\n"
            "CONCEPT: [2-3 word name]\n"
            "DEFINITION: [2-3 sentence definition in your own words]\n"
            "IMPORTANCE: [a number between 0.0 and 1.0]\n"
            "WHY: [1-2 sentences about why this matters to you specifically]"
        )
        try:
            reply = self._provider.complete(prompt, max_tokens=400)
        except Exception:
            logger.exception("concept invention LLM call failed")
            return

        parsed = _parse_concept_reply(reply)
        if parsed is None:
            logger.warning("concept invention: could not parse reply")
            return

        name = parsed["name"][:100]
        if self._self_repo.has_concept(self._self_id, name):
            logger.info("concept '%s' already exists, skipping", name)
            return

        node_id = f"concept-{uuid4()}"
        importance = max(0.0, min(1.0, parsed["importance"]))
        self._self_repo.insert_concept(
            node_id=node_id,
            self_id=self._self_id,
            name=name,
            definition=parsed["definition"][:1000],
            importance=importance,
            origin_drive=drive,
        )

        mem = EpisodicMemory(
            memory_id=str(uuid4()),
            self_id=self._self_id,
            content=f"I explored the concept of {name}: {parsed['definition'][:300]}",
            tier=MemoryTier.LESSON,
            source=SourceKind.I_DID,
            weight=0.5,
            intent_at_time=f"concept-invention-{name}",
            created_at=datetime.now(UTC),
        )
        self._repo.insert(mem)
        logger.info("invented concept '%s' (importance=%.2f)", name, importance)


def _parse_concept_reply(reply: str) -> dict | None:
    lines = reply.strip().split("\n")
    name = ""
    definition = ""
    importance = 0.5
    why = ""
    for line in lines:
        stripped = line.strip()
        if stripped.upper().startswith("CONCEPT:"):
            name = stripped.split(":", 1)[1].strip()
        elif stripped.upper().startswith("DEFINITION:"):
            definition = stripped.split(":", 1)[1].strip()
        elif stripped.upper().startswith("IMPORTANCE:"):
            try:
                importance = float(stripped.split(":", 1)[1].strip())
            except ValueError:
                pass
        elif stripped.upper().startswith("WHY:"):
            why = stripped.split(":", 1)[1].strip()
    if not name or not definition:
        return None
    return {"name": name, "definition": definition, "importance": importance, "why": why}
