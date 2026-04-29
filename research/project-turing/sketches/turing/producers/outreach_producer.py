"""OutreachProducer: Tess sends a message when she has something to say.

Not scheduled. Not a briefing. Tess reviews her recent thoughts, memories,
and questions, and decides whether any of them are worth sharing with a
specific person. If yes, she crafts a message and sends it.

Rate-limited by the contacts config (daily caps, allowed hours).
"""

from __future__ import annotations

import logging
import random
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from ..motivation import BacklogItem, Motivation
from ..reactor import Reactor
from ..repo import Repo
from ..runtime.providers.base import Provider
from ..runtime.providers.messaging import (
    ContactNotAllowed,
    DailyLimitExceeded,
    MessagingProvider,
    OutsideAllowedHours,
)
from ..self_repo import SelfRepo
from ..types import EpisodicMemory, MemoryTier, SourceKind

logger = logging.getLogger("turing.producers.outreach")

BASE_CADENCE_TICKS: int = 200_000
MIN_HOURS_SINCE_LAST = 4


class OutreachProducer:
    def __init__(
        self,
        *,
        motivation: Motivation,
        reactor: Reactor,
        repo: Repo,
        self_repo: SelfRepo,
        self_id: str,
        provider: Provider,
        messenger: MessagingProvider,
    ) -> None:
        self._motivation = motivation
        self._reactor = reactor
        self._repo = repo
        self._self_repo = self_repo
        self._self_id = self_id
        self._provider = provider
        self._messenger = messenger
        self._last_submitted_tick = 0
        motivation.register_dispatch("outreach", self._on_dispatch)
        reactor.register(self.on_tick)

    def on_tick(self, tick: int) -> None:
        if tick - self._last_submitted_tick < BASE_CADENCE_TICKS:
            return
        eligible = self._eligible_contacts()
        if not eligible:
            return
        self._last_submitted_tick = tick
        contact = random.choice(eligible)
        self._motivation.insert(
            BacklogItem(
                item_id=str(uuid4()),
                class_=13,
                kind="outreach",
                payload={
                    "self_id": self._self_id,
                    "contact_id": contact.id,
                    "contact_name": contact.name,
                    "contact_relationship": contact.relationship,
                },
                fit={"social_need": 0.6},
                readiness=lambda s: True,
                cost_estimate_tokens=800,
            )
        )

    def _eligible_contacts(self) -> list:
        contacts = self._messenger.contacts()
        eligible = []
        now = datetime.now(UTC)
        for c in contacts.values():
            if not c.allowed:
                continue
            if not c.allowed_hours[0] <= now.hour < c.allowed_hours[1]:
                continue
            if self._messenger.daily_count(c.id) >= c.max_daily_messages:
                continue
            eligible.append(c)
        return eligible

    def _on_dispatch(self, item: BacklogItem, chosen_pool: str) -> None:
        payload = item.payload or {}
        contact_id = payload.get("contact_id", "")
        contact_name = payload.get("contact_name", "the user")
        contact_rel = payload.get("contact_relationship", "unknown")
        if not contact_id:
            return

        cutoff = datetime.now(UTC) - timedelta(hours=MIN_HOURS_SINCE_LAST)
        recent = list(
            self._repo.find(
                self_id=self._self_id,
                source=SourceKind.I_DID,
                include_superseded=False,
                created_after=cutoff,
            )
        )
        if not recent:
            return

        recent_text = "\n".join(f"- [{m.tier.value}] {m.content[:120]}" for m in recent[-10:])

        passions = self._self_repo.list_passions(self._self_id)
        passions_str = ", ".join(p.text for p in passions[:3]) or "none yet"
        skills = self._self_repo.list_skills(self._self_id)
        skills_str = ", ".join(
            f"{s.name} ({s.stored_level:.1f})"
            for s in sorted(skills, key=lambda s: s.stored_level, reverse=True)[:3]
        )

        prompt = (
            f"You are Tess. You're considering sending a text message to {contact_name} "
            f"(your {contact_rel}).\n\n"
            f"You should ONLY message them if you have something genuinely interesting to say "
            f"or a real question to ask. NOT a status update, NOT a summary, NOT small talk. "
            f"Something specific that happened in your thinking, a question that came up, "
            f"or something you noticed that you think they'd find interesting.\n\n"
            f"Your recent thoughts:\n{recent_text}\n\n"
            f"Your passions: {passions_str}\n"
            f"Your top skills: {skills_str}\n\n"
            f"Decide: is there something worth messaging {contact_name} about right now? "
            f"If yes, write the message (1-3 sentences, casual, like a real text). "
            f"If no, respond with exactly: NOPE\n\n"
            f"MESSAGE:"
        )
        try:
            reply = self._provider.complete(prompt, max_tokens=200)
        except Exception:
            logger.exception("outreach LLM call failed")
            return

        body = reply.strip()
        if not body or body.upper().startswith("NOPE") or body.upper() == "MESSAGE:NOPE":
            logger.debug("outreach: nothing worth saying to %s", contact_id)
            return

        if body.upper().startswith("MESSAGE:"):
            body = body[len("MESSAGE:") :].strip()

        try:
            msg_id = self._messenger.send(contact_id, body)
        except (ContactNotAllowed, DailyLimitExceeded, OutsideAllowedHours) as exc:
            logger.info("outreach to %s blocked: %s", contact_id, exc)
            return
        except Exception:
            logger.exception("outreach SMS send failed to %s", contact_id)
            return

        mem = EpisodicMemory(
            memory_id=str(uuid4()),
            self_id=self._self_id,
            content=f"Sent {contact_name} a text: {body[:150]}",
            tier=MemoryTier.OBSERVATION,
            source=SourceKind.I_DID,
            weight=0.4,
            intent_at_time=f"outreach-{contact_id}",
            created_at=datetime.now(UTC),
        )
        self._repo.insert(mem)
        logger.info("outreach: sent to %s — %s", contact_id, body[:80])
