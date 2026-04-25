"""Entry point. `python -m turing.runtime.main [flags]`.

Wires Repo + self_id + Motivation + Scheduler + DaydreamProducers +
ContradictionDetector + CoefficientTuner + Providers into a long-running
RealReactor tick loop.
"""

from __future__ import annotations

import argparse
import logging
import signal
import sys
import uuid
from dataclasses import dataclass
from typing import Any

from ..daydream import DaydreamProducer
from ..detectors.contradiction import ContradictionDetector
from ..dreaming import Dreamer
from ..motivation import Motivation
from ..repo import Repo
from ..scheduler import Scheduler
from ..self_identity import bootstrap_self_id
from ..tuning import CoefficientTuner
from .config import RuntimeConfig, load_config_from_env
from .instrumentation import setup_logging
from ..retrieval import semantic_retrieve
from ..tiers import WEIGHT_BOUNDS
from ..types import EpisodicMemory, MemoryTier, SourceKind
from ..working_memory import WorkingMemory
from ..write_paths import handle_affirmation
from .actor import Actor
from .chat import ChatBridge, start_chat_server
from .embedding_index import EmbeddingIndex
from .indexing_repo import IndexingRepo
from .journal import Journal
from .metrics import MetricsCollector, start_metrics_server
from .pools import PoolConfig, load_pools
from .providers.base import Provider
from .providers.fake import FakeProvider
from .providers.litellm import LiteLLMProvider
from .quota import FreeTierQuotaTracker
from .reactor import RealReactor
from .rss_fetcher import RSSFetcher
from .tools.base import ToolRegistry
from .tools.obsidian import ObsidianWriter
from .tools.rss import RSSReader
from .workload import WorkloadDriver, load_scenario
from .working_memory_maintenance import WorkingMemoryMaintenance


logger = logging.getLogger("turing.runtime.main")


def _resolve_scenario_path(scenario: str) -> str:
    """Locate a scenario YAML relative to the project-turing repo root."""
    from pathlib import Path

    direct = Path(scenario)
    if direct.is_file():
        return str(direct)

    # Try resolving relative to research/project-turing/scenarios/.
    anchor = Path(__file__).resolve()
    # __file__ = .../research/project-turing/sketches/turing/runtime/main.py
    project_root = anchor.parents[3]
    candidate = project_root / "scenarios" / f"{scenario}.yaml"
    if candidate.is_file():
        return str(candidate)
    raise FileNotFoundError(f"scenario not found: {scenario}")


def _select_chat_provider(
    providers: dict[str, Provider],
    weights: dict[str, float],
    roles: dict[str, str],
) -> Provider:
    """Highest-quality chat-role pool. Falls back to any pool if none are
    explicitly chat-role."""
    chat_pools = [n for n in providers if roles.get(n, "chat") == "chat"]
    pool_set = chat_pools or list(providers)
    if not pool_set:
        raise RuntimeError("no providers registered; cannot service chat")
    best_name = max(pool_set, key=lambda name: weights.get(name, 1.0))
    return providers[best_name]


def _select_embedding_provider(
    providers: dict[str, Provider],
    roles: dict[str, str],
) -> Provider | None:
    """Pick the embedding-role pool if one exists; otherwise None.

    None means "no semantic retrieval available" and the chat path falls
    back to keyword-based retrieval or bare LLM reply.
    """
    for name, role in roles.items():
        if role == "embedding":
            return providers[name]
    return None


def _think_about_rss_item(
    *,
    feed_item: Any,
    provider: Provider,
    repo: Any,
    self_id: str,
    index: EmbeddingIndex | None,
) -> None:
    """Reason about a newly-seen RSS item. Always write a weak summary;
    promote to OPINION if the LLM judged it interesting; mint an
    AFFIRMATION if also actionable.

    The summary stays in weak memory no matter what — pruning leaves
    regrettably-unjudged items alive enough to reconsider later.
    """
    title = getattr(feed_item, "title", "(untitled)")
    feed_url = getattr(feed_item, "feed_url", "")
    summary = getattr(feed_item, "summary", "") or ""
    link = getattr(feed_item, "link", "")

    # Pull in related memory as context for the reflection.
    related_text = ""
    if index is not None and index.size() > 0:
        hits = semantic_retrieve(
            repo,
            index,
            self_id,
            query=f"{title}\n{summary}",
            top_k=3,
            min_similarity=0.05,
        )
        if hits:
            related_text = "\n".join(f"- [{m.tier.value}] {m.content}" for m, _ in hits)

    prompt = (
        "You are Project Turing, reading an item from a subscribed feed.\n"
        "Respond with ONLY a JSON object on one line matching this schema:\n"
        '  {"opinion": "<what you think>", '
        '"proposed_action": "<what you would want to do, or empty>", '
        '"interest_score": <0..1>, '
        '"actionable": <true|false>, '
        '"summary": "<one-sentence record>"}\n'
        f"\nTitle: {title}\n"
        f"Feed: {feed_url}\n"
        f"Summary: {summary}\n"
        f"Link: {link}\n"
    )
    if related_text:
        prompt += f"\nYour related memory:\n{related_text}\n"

    try:
        reply = provider.complete(prompt, max_tokens=400)
    except Exception:
        logger.exception("rss thinking call failed; writing minimal summary")
        reply = ""

    parsed = _parse_rss_reflection(reply, fallback_summary=title)

    # 1. ALWAYS write a weak OBSERVATION summary.
    obs = EpisodicMemory(
        memory_id=str(uuid.uuid4()),
        self_id=self_id,
        tier=MemoryTier.OBSERVATION,
        source=SourceKind.I_DID,
        content=parsed["summary"][:500],
        weight=WEIGHT_BOUNDS[MemoryTier.OBSERVATION][0],  # floor
        intent_at_time=f"process-rss-{feed_url}",
        context={"feed_url": feed_url, "link": link, "title": title},
    )
    repo.insert(obs)

    # 2. Promote to OPINION if interesting enough.
    interest = float(parsed.get("interest_score", 0.0) or 0.0)
    if interest >= 0.6 and parsed.get("opinion"):
        op = EpisodicMemory(
            memory_id=str(uuid.uuid4()),
            self_id=self_id,
            tier=MemoryTier.OPINION,
            source=SourceKind.I_DID,
            content=f"about '{title}': {parsed['opinion'][:300]}",
            weight=WEIGHT_BOUNDS[MemoryTier.OPINION][0] + 0.1,
            intent_at_time=f"rss-opinion-{feed_url}",
            context={"feed_url": feed_url, "link": link},
        )
        repo.insert(op)

    # 3. Mint AFFIRMATION if actionable AND very interesting.
    if interest >= 0.8 and bool(parsed.get("actionable")) and parsed.get("proposed_action"):
        handle_affirmation(
            repo,
            self_id,
            content=(f"commit (from {feed_url}): {parsed['proposed_action'][:300]}"),
        )


def _parse_rss_reflection(reply: str, *, fallback_summary: str) -> dict[str, Any]:
    import json

    text = (reply or "").strip()
    # Pull the first {...} block if the model surrounded it with prose.
    if "{" in text and "}" in text:
        first = text.index("{")
        last = text.rindex("}")
        text = text[first : last + 1]
    try:
        parsed = json.loads(text)
        if not isinstance(parsed, dict):
            raise ValueError
    except Exception:
        parsed = {}
    return {
        "opinion": str(parsed.get("opinion", "") or ""),
        "proposed_action": str(parsed.get("proposed_action", "") or ""),
        "interest_score": parsed.get("interest_score", 0.0),
        "actionable": bool(parsed.get("actionable", False)),
        "summary": str(parsed.get("summary", fallback_summary) or fallback_summary),
    }


DEFAULT_BASE_PROMPT: str = (
    "You are Project Turing — an autonoetic agent with a persistent self.\n"
    "You remember: your regrets, accomplishments, commitments, wisdom.\n"
    "Speak in first person from that self. Be concise and honest."
)


def _load_base_prompt(path: str | None) -> str:
    if not path:
        return DEFAULT_BASE_PROMPT
    from pathlib import Path

    p = Path(path)
    if not p.is_file():
        logger.warning("base prompt not found at %s; using default", path)
        return DEFAULT_BASE_PROMPT
    return p.read_text(encoding="utf-8").strip()


def _build_chat_prompt(
    *,
    message: str,
    history: list[dict[str, Any]],
    repo: Any,
    self_id: str,
    index: EmbeddingIndex | None,
    base_prompt: str,
    working_memory: WorkingMemory | None,
) -> str:
    """Compose a chat prompt from:
    - OPERATOR-controlled base prompt (immutable by the self)
    - SELF-controlled working memory (edited by the wm_maintenance loop)
    - current WISDOM (identity)
    - semantically relevant durable memories
    - conversation history
    - the latest user message

    Keeps prompts bounded; missing sections (no index, no working memory)
    are silently skipped.
    """
    lines: list[str] = [
        "## Base framing (operator-set)",
        base_prompt,
        "",
    ]

    if working_memory is not None:
        wm_block = working_memory.render(self_id)
        lines.extend(
            [
                "## Your working memory (self-maintained)",
                wm_block,
                "",
            ]
        )

    # Current WISDOM.
    wisdom = list(
        repo.find(
            self_id=self_id,
            tier=MemoryTier.WISDOM,
            source=SourceKind.I_DID,
            include_superseded=False,
        )
    )
    if wisdom:
        lines.append("## What you know about yourself (WISDOM)")
        for w in wisdom[:5]:
            lines.append(f"- {w.content}")
        lines.append("")

    # Semantic retrieval across durable tiers.
    if index is not None and index.size() > 0:
        hits = semantic_retrieve(
            repo,
            index,
            self_id,
            query=message,
            top_k=5,
            tiers=[
                MemoryTier.REGRET,
                MemoryTier.ACCOMPLISHMENT,
                MemoryTier.AFFIRMATION,
                MemoryTier.LESSON,
                MemoryTier.OPINION,
            ],
            min_similarity=0.05,
        )
        if hits:
            lines.append("## Relevant memories")
            for memory, score in hits:
                tag = memory.tier.value
                lines.append(f"- [{tag}] {memory.content} _(relevance {score:.2f})_")
            lines.append("")

    if history:
        lines.append("## Conversation so far")
        for turn in history[-6:]:  # last 6 turns
            role = turn.get("role", "user")
            content = turn.get("content", "")
            lines.append(f"{role}: {content}")
        lines.append("")

    lines.append(f"user: {message}")
    lines.append("assistant:")
    return "\n".join(lines)


def _build_providers(
    cfg: RuntimeConfig,
) -> tuple[dict[str, Provider], dict[str, float]]:
    """Returns (providers_by_pool_name, quality_weights_by_pool_name)."""
    if cfg.use_fake_provider:
        return {"fake": FakeProvider(name="fake")}, {"fake": 0.1}

    assert cfg.litellm_base_url and cfg.litellm_virtual_key and cfg.pools_config_path
    pools: list[PoolConfig] = load_pools(cfg.pools_config_path)
    if not pools:
        raise ValueError(f"pools config has no pools: {cfg.pools_config_path}")
    providers: dict[str, Provider] = {}
    weights: dict[str, float] = {}
    for pool in pools:
        providers[pool.pool_name] = LiteLLMProvider(
            pool_config=pool,
            base_url=cfg.litellm_base_url,
            virtual_key=cfg.litellm_virtual_key,
        )
        weights[pool.pool_name] = pool.quality_weight
    return providers, weights


def _pool_roles(cfg: RuntimeConfig) -> dict[str, str]:
    """Returns {pool_name: role}. Empty or all-chat for FakeProvider mode."""
    if cfg.use_fake_provider:
        return {"fake": "chat"}
    assert cfg.pools_config_path
    pools = load_pools(cfg.pools_config_path)
    return {p.pool_name: p.role for p in pools}


def _make_imagine_for_provider(provider: Provider) -> Any:
    """Return an `imagine` callable that uses the given provider."""
    from ..daydream import default_imagine
    from ..types import EpisodicMemory

    def imagine(
        seed: EpisodicMemory,
        retrieved: list[EpisodicMemory],
        pool_name: str,
    ) -> list[tuple[str, str, str]]:
        prompt = (
            f"Seed memory: {seed.content!r}\n"
            f"Related ({len(retrieved)}): "
            + "; ".join(m.content for m in retrieved[:3])
            + "\nProduce one HYPOTHESIS that explores an alternative future."
        )
        try:
            reply = provider.complete(prompt, max_tokens=256)
        except Exception:
            logger.exception("provider %s failed during imagine", provider.name)
            return default_imagine(seed, retrieved, pool_name)
        return [
            (
                "hypothesis",
                reply.strip() or f"no reply from {provider.name}",
                seed.intent_at_time or "generic-intent",
            )
        ]

    return imagine


@dataclass
class RunArgs:
    tick_rate: int | None = None
    db: str | None = None
    journal_dir: str | None = None
    log_level: str | None = None
    log_format: str | None = None
    use_fake_provider: bool = False
    litellm_base_url: str | None = None
    litellm_virtual_key: str | None = None
    pools_config: str | None = None
    scenario: str | None = None
    duration: int | None = None
    metrics_port: int | None = None
    metrics_bind: str | None = None
    chat_port: int | None = None
    chat_bind: str | None = None
    obsidian_vault: str | None = None
    rss_feeds: str | None = None
    base_prompt: str | None = None
    smoke_test: bool = False

    def to_overrides(self) -> dict[str, Any]:
        overrides: dict[str, Any] = {}
        if self.tick_rate is not None:
            overrides["tick_rate_hz"] = self.tick_rate
        if self.db is not None:
            overrides["db_path"] = self.db
        if self.journal_dir is not None:
            overrides["journal_dir"] = self.journal_dir
        if self.log_level is not None:
            overrides["log_level"] = self.log_level
        if self.log_format is not None:
            overrides["log_format"] = self.log_format
        if self.use_fake_provider:
            overrides["use_fake_provider"] = True
        if self.litellm_base_url is not None:
            overrides["litellm_base_url"] = self.litellm_base_url
            overrides["use_fake_provider"] = False
        if self.litellm_virtual_key is not None:
            overrides["litellm_virtual_key"] = self.litellm_virtual_key
        if self.pools_config is not None:
            overrides["pools_config_path"] = self.pools_config
        if self.scenario is not None:
            overrides["scenario"] = self.scenario
        if self.metrics_port is not None:
            overrides["metrics_port"] = self.metrics_port
        if self.metrics_bind is not None:
            overrides["metrics_bind"] = self.metrics_bind
        if self.chat_port is not None:
            overrides["chat_port"] = self.chat_port
        if self.chat_bind is not None:
            overrides["chat_bind"] = self.chat_bind
        if self.obsidian_vault is not None:
            overrides["obsidian_vault_dir"] = self.obsidian_vault
        if self.rss_feeds is not None:
            overrides["rss_feeds"] = tuple(
                f.strip() for f in self.rss_feeds.split(",") if f.strip()
            )
        if self.base_prompt is not None:
            overrides["base_prompt_path"] = self.base_prompt
        return overrides


def _parse_argv(argv: list[str] | None = None) -> RunArgs:
    parser = argparse.ArgumentParser(prog="turing-runtime")
    parser.add_argument("--tick-rate", type=int)
    parser.add_argument("--db", type=str)
    parser.add_argument("--journal-dir", type=str, help="enable journal output at this directory")
    parser.add_argument("--log-level", type=str, choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    parser.add_argument("--log-format", type=str, choices=["plain", "json"])
    parser.add_argument(
        "--use-fake-provider",
        action="store_true",
        help="run with the FakeProvider (no LiteLLM needed)",
    )
    parser.add_argument("--litellm-base-url", type=str)
    parser.add_argument("--litellm-virtual-key", type=str)
    parser.add_argument("--pools-config", type=str, help="path to pools YAML")
    parser.add_argument("--scenario", type=str)
    parser.add_argument(
        "--duration", type=int, help="seconds to run before auto-stop (default: forever)"
    )
    parser.add_argument("--metrics-port", type=int, help="enable Prometheus endpoint on this port")
    parser.add_argument(
        "--metrics-bind",
        type=str,
        default=None,
        help="bind interface for the metrics endpoint (default 127.0.0.1)",
    )
    parser.add_argument("--chat-port", type=int, help="enable chat HTTP server on this port")
    parser.add_argument(
        "--chat-bind",
        type=str,
        default=None,
        help="bind interface for the chat server (default 127.0.0.1)",
    )
    parser.add_argument(
        "--obsidian-vault", type=str, help="enable Obsidian vault writes at this directory"
    )
    parser.add_argument(
        "--rss-feeds", type=str, help="comma-separated RSS/Atom feed URLs to subscribe to"
    )
    parser.add_argument(
        "--base-prompt", type=str, help="path to the operator-controlled base prompt markdown"
    )
    parser.add_argument(
        "--smoke-test", action="store_true", help="run a brief acceptance smoke and exit 0/1"
    )
    parsed = parser.parse_args(argv)
    return RunArgs(
        tick_rate=parsed.tick_rate,
        db=parsed.db,
        journal_dir=parsed.journal_dir,
        log_level=parsed.log_level,
        log_format=parsed.log_format,
        use_fake_provider=parsed.use_fake_provider,
        litellm_base_url=parsed.litellm_base_url,
        litellm_virtual_key=parsed.litellm_virtual_key,
        pools_config=parsed.pools_config,
        scenario=parsed.scenario,
        duration=parsed.duration,
        metrics_port=parsed.metrics_port,
        metrics_bind=parsed.metrics_bind,
        chat_port=parsed.chat_port,
        chat_bind=parsed.chat_bind,
        obsidian_vault=parsed.obsidian_vault,
        rss_feeds=parsed.rss_feeds,
        base_prompt=parsed.base_prompt,
        smoke_test=parsed.smoke_test,
    )


def build_and_run(argv: list[str] | None = None) -> int:
    args = _parse_argv(argv)

    if args.smoke_test:
        from .smoke import run_smoke

        return run_smoke()

    cfg = load_config_from_env(overrides=args.to_overrides())
    setup_logging(level=cfg.log_level, fmt=cfg.log_format)

    pool_label = "fake" if cfg.use_fake_provider else f"litellm({cfg.pools_config_path})"
    logger.info(
        "starting runtime tick_rate=%d db=%s pools=%s",
        cfg.tick_rate_hz,
        cfg.db_path,
        pool_label,
    )

    raw_repo = Repo(cfg.db_path if cfg.db_path != ":memory:" else None)
    self_id = bootstrap_self_id(raw_repo.conn)
    logger.info("self_id=%s", self_id)

    reactor = RealReactor(
        tick_rate_hz=cfg.tick_rate_hz,
        executor_workers=cfg.executor_workers,
    )
    motivation = Motivation(reactor)

    providers, quality_weights = _build_providers(cfg)
    pool_roles = _pool_roles(cfg)
    embedding_provider = _select_embedding_provider(providers, pool_roles)

    # Wrap the repo with an IndexingRepo if we have an embedding provider.
    embedding_index: EmbeddingIndex | None
    if embedding_provider is not None:
        embedding_index = EmbeddingIndex(embed_fn=embedding_provider.embed)
        repo = IndexingRepo(inner=raw_repo, index=embedding_index)
        rebuilt = repo.rebuild_index_from_repo(self_id)
        logger.info("embedding index rebuilt with %d memories", rebuilt)
    else:
        embedding_index = None
        repo = raw_repo

    scheduler = Scheduler(reactor, motivation)

    # Operator-controlled base prompt (immutable) + self-controlled working
    # memory (edited via the maintenance loop, below).
    base_prompt = _load_base_prompt(cfg.base_prompt_path)
    working_memory = WorkingMemory(raw_repo.conn)

    quota_tracker = FreeTierQuotaTracker()
    for pool_name, provider in providers.items():
        quota_tracker.register(
            provider,
            quality_weight=quality_weights.get(pool_name, 1.0),
        )
        # Only chat-role pools feed the daydream producers; embedding
        # pools shouldn't be daydreamed against.
        if pool_roles.get(pool_name, "chat") == "chat":
            DaydreamProducer(
                pool_name=pool_name,
                self_id=self_id,
                motivation=motivation,
                reactor=reactor,
                repo=repo,
                imagine=_make_imagine_for_provider(provider),
            )

    # Per-tick: refresh pressure_vec from the quota tracker. O(len(providers))
    # and cheap.
    def _refresh_pressure(tick: int) -> None:
        for pool_name, value in quota_tracker.pressure_vec().items():
            motivation.set_pressure(pool_name, value)

    reactor.register(_refresh_pressure)

    ContradictionDetector(
        repo=repo,
        motivation=motivation,
        reactor=reactor,
        self_id=self_id,
    )
    CoefficientTuner(
        motivation=motivation,
        reactor=reactor,
        repo=repo,
        self_id=self_id,
    )
    Dreamer(
        motivation=motivation,
        reactor=reactor,
        repo=repo,
        self_id=self_id,
    )

    # Self-editable working memory is maintained by a P13 RASO-level
    # reflection loop. The chat provider is the natural pick for the
    # maintenance LLM (same framing, same weights).
    WorkingMemoryMaintenance(
        motivation=motivation,
        reactor=reactor,
        repo=repo,
        working_memory=working_memory,
        provider=_select_chat_provider(providers, quality_weights, pool_roles),
        self_id=self_id,
    )

    if cfg.journal_dir:
        journal = Journal(repo=repo, self_id=self_id, journal_dir=cfg.journal_dir)
        reactor.register(journal.on_tick)
        logger.info("journal writing to %s", cfg.journal_dir)

    # Tool layer + Actor.
    tool_registry = ToolRegistry()
    if cfg.obsidian_vault_dir:
        tool_registry.register(ObsidianWriter(vault_dir=cfg.obsidian_vault_dir))
        logger.info("obsidian writes enabled at %s", cfg.obsidian_vault_dir)
    if cfg.rss_feeds:
        rss_reader = RSSReader(feeds=cfg.rss_feeds)
        tool_registry.register(rss_reader)
        logger.info("rss reader registered with %d feed(s)", len(cfg.rss_feeds))

        # Schedule periodic polling; each new item lands as P7 rss_item.
        RSSFetcher(reader=rss_reader, motivation=motivation, reactor=reactor)

        # Dispatch handler for rss_item: thinks about the item, writes a
        # weak summary always, promotes to OPINION if interesting, mints
        # AFFIRMATION if actionable + very interesting.
        rss_chat_provider = _select_chat_provider(providers, quality_weights, pool_roles)

        def _on_dispatch_rss_item(item: BacklogItem, chosen_pool: str) -> None:
            payload = item.payload or {}
            feed_item = payload.get("feed_item")
            if feed_item is None:
                return
            try:
                _think_about_rss_item(
                    feed_item=feed_item,
                    provider=rss_chat_provider,
                    repo=repo,
                    self_id=self_id,
                    index=embedding_index,
                )
            except Exception:
                logger.exception(
                    "rss_item dispatch failed for %s", getattr(feed_item, "item_id", "?")
                )

        motivation.register_dispatch("rss_item", _on_dispatch_rss_item)

    if tool_registry.names():
        actor = Actor(repo=repo, self_id=self_id, registry=tool_registry)
        reactor.register(actor.on_tick)

    # Chat HTTP server + dispatch handler that uses an LLM provider to reply.
    stop_chat: Any = None
    if cfg.chat_port is not None:
        bridge = ChatBridge()

        # Pick the highest-quality registered pool for chat replies.
        chat_provider = _select_chat_provider(providers, quality_weights, pool_roles)

        def _on_chat_dispatch(item: BacklogItem, chosen_pool: str) -> None:
            payload = item.payload or {}
            message = str(payload.get("message", ""))
            history = payload.get("history") or []
            try:
                prompt = _build_chat_prompt(
                    message=message,
                    history=history,
                    repo=repo,
                    self_id=self_id,
                    index=embedding_index,
                    base_prompt=base_prompt,
                    working_memory=working_memory,
                )
                reply = chat_provider.complete(prompt, max_tokens=400)
            except Exception:
                logger.exception("chat dispatch failed")
                reply = "(I encountered an error generating a reply.)"
            bridge.resolve(item.item_id, reply)

        motivation.register_dispatch("chat_message", _on_chat_dispatch)

        stop_chat = start_chat_server(
            motivation=motivation,
            repo=repo,
            self_id=self_id,
            bridge=bridge,
            port=cfg.chat_port,
            host=cfg.chat_bind,
            journal_dir=cfg.journal_dir,
        )

    if cfg.scenario:
        scenario_path = _resolve_scenario_path(cfg.scenario)
        logger.info("loading scenario %s", scenario_path)
        scenario = load_scenario(scenario_path)
        WorkloadDriver(
            scenario=scenario,
            motivation=motivation,
            reactor=reactor,
            scheduler=scheduler,
            repo=repo,
            self_id=self_id,
        )

    stop_metrics: Any = None
    if cfg.metrics_port is not None:
        collector = MetricsCollector()

        def _refresh_metrics(tick: int) -> None:
            status = reactor.get_status()
            collector.update(
                turing_tick_count=status.tick_count,
                turing_drift_ms_p99=status.drift_ms_p99,
            )
            for pool, value in quota_tracker.pressure_vec().items():
                collector.set_labeled("turing_pressure", (pool,), value)
                window = quota_tracker.window(pool)
                if window is not None:
                    collector.set_labeled("turing_quota_headroom", (pool,), window.headroom)
            # Durable counts: cheap enough every tick, but only refresh
            # every 10th tick to avoid DB thrash.
            if tick % 10 == 0:
                for tier in ("regret", "accomplishment", "affirmation", "wisdom"):
                    n = repo.conn.execute(
                        "SELECT COUNT(*) FROM durable_memory WHERE tier = ?",
                        (tier,),
                    ).fetchone()[0]
                    collector.set_labeled("turing_durable_memories_total", (tier,), n)

        reactor.register(_refresh_metrics)
        stop_metrics = start_metrics_server(collector, port=cfg.metrics_port, host=cfg.metrics_bind)

    def _handle_signal(signum: int, _frame: Any) -> None:
        logger.info("signal %d received; stopping reactor", signum)
        reactor.stop()

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    if args.duration is not None:
        import threading

        threading.Timer(args.duration, reactor.stop).start()

    reactor.run_forever()
    status = reactor.get_status()
    logger.info(
        "reactor stopped tick_count=%d drift_p99_ms=%.2f",
        status.tick_count,
        status.drift_ms_p99,
    )
    if stop_metrics is not None:
        stop_metrics()
    if stop_chat is not None:
        stop_chat()
    repo.close()
    return 0


if __name__ == "__main__":
    sys.exit(build_and_run())
