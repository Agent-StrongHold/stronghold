"""DI container: wires protocols to implementations."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import httpx

from stronghold.agents.context_builder import ContextBuilder
from stronghold.agents.factory import create_agents
from stronghold.agents.intents import IntentRegistry
from stronghold.agents.store import InMemoryAgentStore
from stronghold.agents.task_queue import InMemoryTaskQueue
from stronghold.api.litellm_client import LiteLLMClient
from stronghold.classifier.engine import ClassifierEngine
from stronghold.events import Reactor
from stronghold.memory.learnings.extractor import ToolCorrectionExtractor
from stronghold.memory.learnings.store import InMemoryLearningStore
from stronghold.memory.outcomes import InMemoryOutcomeStore
from stronghold.playbooks.registry import InMemoryPlaybookRegistry
from stronghold.prompts.store import InMemoryPromptManager
from stronghold.quota.tracker import InMemoryQuotaTracker
from stronghold.router.selector import RouterEngine
from stronghold.scheduling.store import InMemoryScheduleStore
from stronghold.security.auth_static import StaticKeyAuthProvider
from stronghold.security.gate import Gate
from stronghold.security.rate_limiter import InMemoryRateLimiter
from stronghold.security.sentinel.audit import InMemoryAuditLog
from stronghold.security.sentinel.policy import Sentinel
from stronghold.security.strikes import InMemoryStrikeTracker
from stronghold.security.tool_policy import ToolPolicyProtocol, create_tool_policy
from stronghold.security.warden.detector import Warden
from stronghold.sessions.store import InMemorySessionStore
from stronghold.tools.executor import ToolDispatcher
from stronghold.tools.registry import InMemoryToolRegistry
from stronghold.tracing.noop import NoopTracingBackend
from stronghold.tracing.phoenix_backend import PhoenixTracingBackend
from stronghold.types.auth import PermissionTable
from stronghold.types.errors import ConfigError

if TYPE_CHECKING:
    from stronghold.agents.base import Agent
    from stronghold.protocols.memory import AuditLog, LearningStore, OutcomeStore, SessionStore
    from stronghold.protocols.prompts import PromptManager
    from stronghold.protocols.quota import QuotaTracker
    from stronghold.protocols.tracing import TracingBackend
    from stronghold.types.config import StrongholdConfig

logger = logging.getLogger("stronghold.container")


@dataclass
class Container:
    """Holds all wired dependencies."""

    config: StrongholdConfig
    auth_provider: StaticKeyAuthProvider
    permission_table: PermissionTable
    router: RouterEngine
    classifier: ClassifierEngine
    quota_tracker: QuotaTracker
    prompt_manager: PromptManager
    learning_store: LearningStore
    learning_extractor: ToolCorrectionExtractor
    outcome_store: OutcomeStore
    session_store: SessionStore
    audit_log: AuditLog
    warden: Warden
    gate: Gate
    sentinel: Sentinel
    tracer: TracingBackend
    context_builder: ContextBuilder
    intent_registry: IntentRegistry
    llm: LiteLLMClient
    tool_registry: InMemoryToolRegistry
    tool_dispatcher: ToolDispatcher
    playbook_registry: InMemoryPlaybookRegistry = field(default_factory=InMemoryPlaybookRegistry)
    tool_policy: ToolPolicyProtocol | None = None
    tool_catalog: Any = None
    skill_catalog: Any = None
    resource_catalog: Any = None
    vault_client: Any = None
    mason_queue: Any = None
    agent_store: InMemoryAgentStore = field(default_factory=lambda: InMemoryAgentStore({}))
    rate_limiter: Any = field(default_factory=InMemoryRateLimiter)  # RateLimiter protocol
    reactor: Reactor = field(default_factory=Reactor)
    task_queue: InMemoryTaskQueue = field(default_factory=InMemoryTaskQueue)
    agents: dict[str, Agent] = field(default_factory=dict)
    coin_ledger: Any = None
    tournament: Any = None
    # Emissary MCP gateway plane (wired by create_container; opt-in via DI).
    # The fields are typed Any to keep the Container dataclass independent of
    # the security/mcp module imports — the actual instances are constructed
    # in create_container and surfaced here for callers (chat handler, admin
    # routes, agent runtimes) that need them.
    mcp_tool_catalog: Any = None  # security.tool_catalog.InMemoryToolCatalog
    keyward: Any = None  # security.keyward.Keyward
    composer: Any = None  # mcp.composer.Composer
    mcp_client: Any = None  # mcp.client.MCPClient
    emissary: Any = None  # mcp.emissary.Emissary
    tool_declaration_validator: Any = (
        None  # security.sentinel.tool_declarations.ToolDeclarationValidator
    )
    canary_manager: Any = None
    orchestrator: Any = None  # OrchestratorEngine, set in app.py lifespan
    learning_approval_gate: Any = None
    learning_promoter: Any = None
    strike_tracker: Any = None  # InMemoryStrikeTracker
    db_pool: Any = None  # asyncpg.Pool when using PostgreSQL
    sa_engine: Any = None  # SQLAlchemy async engine (for SQLModel queries)
    redis_client: Any = None  # redis.asyncio.Redis (distributed cache/sessions/rate-limit)
    prompt_cache: Any = None  # RedisPromptCache (write-through cache)
    mcp_registry: Any = None  # MCPRegistry
    schedule_store: InMemoryScheduleStore = field(default_factory=InMemoryScheduleStore)
    mcp_deployer: Any = None  # K8sDeployer
    conduit: Any = None  # Conduit — wired in __post_init__ or create_container

    def __post_init__(self) -> None:
        """Auto-wire Conduit pipeline if not already set."""
        if self.conduit is None:
            from stronghold.conduit import Conduit as ConduitPipeline  # noqa: PLC0415

            self.conduit = ConduitPipeline(self)

    async def route_request(
        self,
        messages: list[dict[str, Any]],
        *,
        auth: Any = None,
        session_id: str | None = None,
        intent_hint: str = "",
        status_callback: Any = None,
    ) -> dict[str, Any]:
        """Delegate to Conduit pipeline. All requests flow through here."""
        result: dict[str, Any] = await self.conduit.route_request(
            messages,
            auth=auth,
            session_id=session_id,
            intent_hint=intent_hint,
            status_callback=status_callback,
        )
        return result


def _wire_auth(
    config: StrongholdConfig,
) -> tuple[StaticKeyAuthProvider, PermissionTable]:
    """Wire auth provider chain: session cookie → cookie (BFF) → JWT → static key."""
    from stronghold.security.auth_composite import CompositeAuthProvider  # noqa: PLC0415
    from stronghold.security.auth_session_cookie import SessionCookieAuthProvider  # noqa: PLC0415

    static_auth = StaticKeyAuthProvider(api_key=config.router_api_key)
    session_cookie_auth = SessionCookieAuthProvider(
        api_key=config.router_api_key,
        cookie_name=config.auth.session_cookie_name,
    )

    if config.auth.jwks_url:
        from stronghold.security.auth_cookie import CookieAuthProvider  # noqa: PLC0415
        from stronghold.security.auth_jwt import JWTAuthProvider  # noqa: PLC0415

        jwt_auth = JWTAuthProvider(
            jwks_url=config.auth.jwks_url,
            issuer=config.auth.issuer,
            audience=config.auth.audience,
        )
        providers: list[StaticKeyAuthProvider] = [session_cookie_auth, jwt_auth, static_auth]  # type: ignore[list-item]

        if config.auth.client_id and config.auth.token_url:
            cookie_auth = CookieAuthProvider(
                jwt_provider=jwt_auth,
                cookie_name=config.auth.session_cookie_name,
            )
            providers.insert(1, cookie_auth)  # type: ignore[arg-type]
            logger.info(
                "Auth: BFF cookie auth enabled (cookie=%s)",
                config.auth.session_cookie_name,
            )

        auth_provider: StaticKeyAuthProvider = CompositeAuthProvider(providers)  # type: ignore[assignment]
        logger.info(
            "Auth: composite (session + cookie + JWT + static key) — JWKS: %s",
            config.auth.jwks_url,
        )
    else:
        auth_provider = CompositeAuthProvider([session_cookie_auth, static_auth])  # type: ignore[assignment]
        logger.info("Auth: composite (session cookie + static key)")

    permission_table = PermissionTable.from_config(config.permissions)
    return auth_provider, permission_table


async def _wire_persistence(
    config: StrongholdConfig,
) -> tuple[Any, QuotaTracker, PromptManager, LearningStore, OutcomeStore, SessionStore, AuditLog]:
    """Wire persistence layer: PostgreSQL or InMemory."""
    db_pool: Any = None

    if config.database_url:
        from stronghold.persistence import get_pool, run_migrations  # noqa: PLC0415
        from stronghold.persistence.pg_audit import PgAuditLog  # noqa: PLC0415
        from stronghold.persistence.pg_learnings import PgLearningStore  # noqa: PLC0415
        from stronghold.persistence.pg_outcomes import PgOutcomeStore  # noqa: PLC0415
        from stronghold.persistence.pg_prompts import PgPromptManager  # noqa: PLC0415
        from stronghold.persistence.pg_quota import PgQuotaTracker  # noqa: PLC0415
        from stronghold.persistence.pg_sessions import PgSessionStore  # noqa: PLC0415

        db_pool = await get_pool(config.database_url)
        await run_migrations(db_pool)
        logger.info("Persistence: PostgreSQL (%s)", config.database_url.split("@")[-1])
        return (
            db_pool,
            PgQuotaTracker(db_pool),
            PgPromptManager(db_pool),
            PgLearningStore(db_pool),
            PgOutcomeStore(db_pool),
            PgSessionStore(db_pool),
            PgAuditLog(db_pool),
        )

    logger.info("Persistence: InMemory (no DATABASE_URL set)")
    return (
        None,
        InMemoryQuotaTracker(),
        InMemoryPromptManager(),
        InMemoryLearningStore(),
        InMemoryOutcomeStore(),
        InMemorySessionStore(),
        InMemoryAuditLog(),
    )


async def create_container(config: StrongholdConfig) -> Container:
    """Wire all dependencies and create the container."""
    if not config.router_api_key:
        msg = (
            "ROUTER_API_KEY is required. Set it via environment variable or config. "
            "Refusing to start with empty/default API key."
        )
        raise ConfigError(msg)

    if not config.jwt_secret:
        config.jwt_secret = config.router_api_key

    # ── Auth ──
    auth_provider, permission_table = _wire_auth(config)
    learning_extractor = ToolCorrectionExtractor()

    # ── Persistence (PostgreSQL or InMemory) ──
    (
        db_pool,
        quota_tracker,
        prompt_manager,
        learning_store,
        outcome_store,
        session_store,
        audit_log,
    ) = await _wire_persistence(config)

    # ── SQLAlchemy engine (for SQLModel queries) ──
    # NOTE: This creates a second connection pool alongside asyncpg. Both hit the
    # same database. The asyncpg pool serves the legacy pg_* modules; the SQLAlchemy
    # engine serves new SQLModel-based code (PgAgentRegistry). As modules migrate
    # to SQLModel, the asyncpg pool will be removed. Track max_connections accordingly.
    sa_engine = None
    if config.database_url:
        from stronghold.models.engine import get_engine  # noqa: PLC0415

        sa_engine = get_engine(config.database_url)
        logger.info("SQLAlchemy async engine initialized")

    # ── Redis (distributed sessions, rate limiting, cache) ──
    redis_client = None
    if config.redis_url:
        from stronghold.cache import get_redis  # noqa: PLC0415

        try:
            redis_client = await get_redis(config.redis_url)
            masked = (
                config.redis_url.split("@")[-1] if "@" in config.redis_url else config.redis_url
            )
            logger.info("Redis connected: %s", masked)
        except Exception:
            logger.warning("Redis unavailable at %s — falling back to InMemory", config.redis_url)

    # ── Rate limiter (Redis if available + enabled, InMemory otherwise) ──
    rate_limiter: Any
    if redis_client and config.rate_limit.enabled:
        from stronghold.cache.rate_limiter import RedisRateLimiter  # noqa: PLC0415

        rate_limiter = RedisRateLimiter(
            redis=redis_client,
            max_requests=config.rate_limit.requests_per_minute,
            window_seconds=60,
        )
        logger.info("Rate limiter: Redis (distributed)")
    else:
        rate_limiter = InMemoryRateLimiter(config.rate_limit)
        if not config.rate_limit.enabled:
            logger.info("Rate limiter: disabled by config")
        else:
            logger.info("Rate limiter: InMemory (local)")

    # ── Session store override (Redis if available) ──
    if redis_client:
        from stronghold.cache.session_store import RedisSessionStore  # noqa: PLC0415

        session_store = RedisSessionStore(
            redis=redis_client,
            ttl_seconds=config.sessions.ttl_seconds,
            max_messages=config.sessions.max_messages,
        )
        logger.info("Sessions: Redis (distributed, TTL=%ds)", config.sessions.ttl_seconds)

    # ── Prompt/agent cache (Redis if available) ──
    prompt_cache = None
    if redis_client:
        from stronghold.cache.prompt_cache import RedisPromptCache  # noqa: PLC0415

        prompt_cache = RedisPromptCache(redis=redis_client, ttl_seconds=300)
        logger.info("Prompt cache: Redis (TTL=300s)")

    # ── Core services ──
    router = RouterEngine(quota_tracker)
    classifier = ClassifierEngine()
    warden = Warden()
    strike_tracker = InMemoryStrikeTracker()
    gate = Gate(warden=warden, strike_tracker=strike_tracker)
    sentinel = Sentinel(
        warden=warden,
        permission_table=permission_table,
        audit_log=audit_log,
    )
    tracer: TracingBackend = (
        PhoenixTracingBackend(endpoint=config.phoenix_endpoint)
        if config.phoenix_endpoint
        else NoopTracingBackend()
    )
    context_builder = ContextBuilder()
    intent_registry = IntentRegistry()

    # Create tool registry + dispatcher
    tool_registry = InMemoryToolRegistry()
    tool_dispatcher = ToolDispatcher(tool_registry)

    # Agent-oriented playbook registry (peer of tool_registry).
    # Empty at startup; playbooks register themselves from phase D onward.
    playbook_registry = InMemoryPlaybookRegistry()

    # Tool policy (Casbin-based, ADR-K8S-019)
    try:
        tool_policy: ToolPolicyProtocol | None = create_tool_policy()
        logger.info("Tool policy loaded")
    except Exception:
        logger.warning("Tool policy config not found, running without policy enforcement")
        tool_policy = None

    # Catalogs (ADR-K8S-021/022/023)
    from stronghold.resources.catalog import ResourceCatalog  # noqa: PLC0415
    from stronghold.skills.catalog import SkillCatalog  # noqa: PLC0415
    from stronghold.tools.catalog import ToolCatalog  # noqa: PLC0415

    tool_catalog = ToolCatalog()
    skill_catalog = SkillCatalog()
    resource_catalog = ResourceCatalog()

    # Register all Mason tools
    from stronghold.tools.file_ops import FILE_OPS_TOOL_DEF, FileOpsExecutor  # noqa: PLC0415
    from stronghold.tools.github import GITHUB_TOOL_DEF, GitHubToolExecutor  # noqa: PLC0415
    from stronghold.tools.shell_exec import (  # noqa: PLC0415
        RUN_BANDIT_DEF,
        RUN_MYPY_DEF,
        RUN_PYTEST_DEF,
        RUN_RUFF_CHECK_DEF,
        RUN_RUFF_FORMAT_DEF,
        SHELL_TOOL_DEF,
        QualityGateExecutor,
        ShellExecutor,
    )
    from stronghold.tools.workspace import WORKSPACE_TOOL_DEF, WorkspaceManager  # noqa: PLC0415

    github_tool = GitHubToolExecutor()
    tool_registry.register(GITHUB_TOOL_DEF, github_tool.execute)

    file_ops = FileOpsExecutor()
    tool_registry.register(FILE_OPS_TOOL_DEF, file_ops.execute)

    shell = ShellExecutor()
    tool_registry.register(SHELL_TOOL_DEF, shell.execute)

    workspace = WorkspaceManager()
    tool_registry.register(WORKSPACE_TOOL_DEF, workspace.execute)

    # Quality gate convenience tools
    qg = QualityGateExecutor(shell)
    tool_registry.register(RUN_PYTEST_DEF, qg.make_executor("pytest {path} -v"))
    tool_registry.register(RUN_RUFF_CHECK_DEF, qg.make_executor("ruff check src/stronghold/"))
    tool_registry.register(
        RUN_RUFF_FORMAT_DEF,
        qg.make_executor("ruff format --check src/stronghold/"),
    )
    tool_registry.register(RUN_MYPY_DEF, qg.make_executor("mypy src/stronghold/ --strict"))
    tool_registry.register(RUN_BANDIT_DEF, qg.make_executor("bandit -r src/stronghold/ -ll"))

    # Create the LLM client — the ONLY connection to LiteLLM
    llm = LiteLLMClient(
        base_url=config.litellm_url,
        api_key=config.litellm_key,
    )

    # ── Load agents from GitAgent directory (seed data) ──
    # In production with PostgreSQL, agents persist in the database.
    # This seeds from the filesystem on first boot or when using InMemory stores.
    from pathlib import Path  # noqa: PLC0415

    from stronghold.agents.strategies.tool_http import HTTPToolExecutor  # noqa: PLC0415
    from stronghold.quota.coins import NoOpCoinLedger, PgCoinLedger  # noqa: PLC0415

    if config.agents_dir:
        agents_dir = Path(config.agents_dir)
    else:
        # Try source layout first, then /app/ (Docker), then relative
        candidates = [
            Path(__file__).resolve().parents[2] / "agents",
            Path("/app/agents"),
            Path("agents"),
        ]
        agents_dir = next((p for p in candidates if p.is_dir()), candidates[0])
    # Tool executor: use registered tools first, fall back to HTTP MCP
    dev_tools = HTTPToolExecutor(base_url="http://dev-tools-mcp:8300")

    async def _tool_exec(name: str, args: dict, *, auth: Any = None) -> str:  # type: ignore[type-arg]
        # Policy gate (ADR-K8S-019): check before any execution
        if tool_policy is not None and auth is not None:
            user_id = getattr(auth, "user_id", "")
            org_id = getattr(auth, "org_id", "")
            if not tool_policy.check_tool_call(user_id, org_id, name):
                raise PermissionError(f"Tool call denied by policy: {name}")

        # Try registered native tools first
        if name in tool_registry:
            return await tool_dispatcher.execute(name, args)
        # Fall back to HTTP MCP server
        return await dev_tools.call(name, args)

    coin_ledger = PgCoinLedger(db_pool, config) if db_pool else NoOpCoinLedger()

    # Learning approval gate + promoter must exist before create_agents so each
    # Agent receives the promoter at construction. Wiring them after create_agents
    # leaves agent._learning_promoter as None and the auto-promotion path in
    # Agent.handle silently no-ops.
    from stronghold.memory.learnings.approval import LearningApprovalGate  # noqa: PLC0415
    from stronghold.memory.learnings.promoter import LearningPromoter  # noqa: PLC0415

    approval_gate = LearningApprovalGate()
    learning_promoter = LearningPromoter(
        learning_store,
        threshold=config.learnings.promotion_threshold,
        approval_gate=approval_gate,
    )

    agents = await create_agents(
        agents_dir=agents_dir,
        prompt_manager=prompt_manager,
        llm=llm,
        context_builder=context_builder,
        warden=warden,
        sentinel=sentinel,
        learning_store=learning_store,
        learning_extractor=learning_extractor,
        outcome_store=outcome_store,
        session_store=session_store,
        quota_tracker=quota_tracker,
        coin_ledger=coin_ledger,
        tracer=tracer,
        tool_executor=_tool_exec,
        sa_engine=sa_engine,
        learning_promoter=learning_promoter,
        tool_registry=tool_registry,
    )

    reactor = Reactor()

    # Tournament system
    from stronghold.agents.tournament import Tournament  # noqa: PLC0415

    tournament = Tournament()

    # Canary deployment manager
    from stronghold.skills.canary import CanaryManager  # noqa: PLC0415

    canary_manager = CanaryManager()

    # MCP server registry + K8s deployer
    from stronghold.mcp.registry import MCPRegistry  # noqa: PLC0415

    mcp_registry = MCPRegistry()
    mcp_deployer = None
    try:
        from stronghold.mcp.deployer import K8sDeployer  # noqa: PLC0415

        mcp_deployer = K8sDeployer()
        logger.info("MCP: K8s deployer available")
    except Exception:
        logger.info("MCP: K8s deployer unavailable (no cluster access)")

    # ── Emissary MCP gateway plane ──
    # Catalog / Keyward / Composer / MCPClient / Emissary are wired here so
    # the chat handler, admin routes, and agent runtimes can reach them via
    # the Container. Backend registrations themselves are populated by a
    # separate loader (follow-up); the gateway accepts traffic only after
    # backends are registered, so wiring here is safe with an empty catalog.
    from stronghold.mcp.client import MCPClient  # noqa: PLC0415
    from stronghold.mcp.composer import Composer  # noqa: PLC0415
    from stronghold.mcp.emissary import Emissary  # noqa: PLC0415
    from stronghold.mcp.invokers import (  # noqa: PLC0415
        make_local_host_invoker,
        make_remote_invoker,
    )
    from stronghold.security.keyward import Keyward, KeywardConfig  # noqa: PLC0415
    from stronghold.security.sentinel.tool_declarations import (  # noqa: PLC0415
        ToolDeclarationValidator,
    )
    from stronghold.security.tool_catalog import InMemoryToolCatalog  # noqa: PLC0415
    from stronghold.types.security import TargetKind  # noqa: PLC0415

    # Build persisters first if a Postgres pool is available, then hand
    # write-through callbacks to the in-memory components. Without a pool,
    # the catalog/composer/emissary/keyward all operate purely in-memory
    # (existing behaviour).
    catalog_persistence = None
    registration_persistence = None
    revocation_persistence = None
    composite_persistence = None
    if db_pool is not None:
        from stronghold.persistence.pg_mcp import (  # noqa: PLC0415
            PgCatalogPersistence,
            PgCompositePersistence,
            PgRegistrationPersistence,
            PgRevocationPersistence,
        )

        catalog_persistence = PgCatalogPersistence(db_pool)
        registration_persistence = PgRegistrationPersistence(db_pool)
        revocation_persistence = PgRevocationPersistence(db_pool)
        composite_persistence = PgCompositePersistence(db_pool)
        logger.info("Emissary plane persistence wired to Postgres")

    # Persist-write-through helpers. Each returns None and schedules the
    # async DB write as a fire-and-forget task. The Task return value is
    # explicitly discarded so the helper conforms to the ``Callable[..., None]``
    # signature the in-memory components expect.
    def _persist_catalog_approve(entry: object) -> None:
        if catalog_persistence is not None:
            asyncio.create_task(catalog_persistence.approve(entry))  # type: ignore[arg-type]

    def _persist_catalog_revoke(fp_value: str, scope: object) -> None:
        if catalog_persistence is not None:
            asyncio.create_task(catalog_persistence.revoke(fp_value, scope))  # type: ignore[arg-type]

    def _persist_composite_upsert(definition: object) -> None:
        if composite_persistence is not None:
            asyncio.create_task(composite_persistence.upsert(definition))  # type: ignore[arg-type]

    def _persist_composite_remove(fp_value: str) -> None:
        if composite_persistence is not None:
            asyncio.create_task(composite_persistence.remove(fp_value))

    def _persist_registration_upsert(registration: object) -> None:
        if registration_persistence is not None:
            asyncio.create_task(registration_persistence.upsert(registration))  # type: ignore[arg-type]

    def _persist_registration_remove(fp_value: str) -> None:
        if registration_persistence is not None:
            asyncio.create_task(registration_persistence.remove(fp_value))

    mcp_tool_catalog = InMemoryToolCatalog(
        persist_approve=_persist_catalog_approve if catalog_persistence is not None else None,
        persist_revoke=_persist_catalog_revoke if catalog_persistence is not None else None,
    )
    keyward = Keyward(
        catalog=mcp_tool_catalog,
        # Reuse jwt_secret for Keyward signing — config/loader.py already
        # validates ≥32 chars. A dedicated keyward signing key with rotation
        # is a follow-up.
        config=KeywardConfig(signing_key=config.jwt_secret),
        persist_revoke=(revocation_persistence.add if revocation_persistence is not None else None),
    )
    composer = Composer(
        persist_upsert=_persist_composite_upsert if composite_persistence is not None else None,
        persist_remove=_persist_composite_remove if composite_persistence is not None else None,
    )
    mcp_http = httpx.AsyncClient(timeout=30)
    mcp_client = MCPClient(http=mcp_http)

    invokers: dict[Any, Any] = {
        TargetKind.REMOTE_PROXY: make_remote_invoker(mcp_client),
    }
    # LOCAL_HOST requires a deployer that implements McpDeployerClient
    # (deploy_tool_mcp/stop_tool_mcp/health). The current K8sDeployer uses
    # a richer per-server interface (deploy(server)/stop(server)/...) and
    # does not match — wiring waits for a McpDeployerClient adapter.
    from stronghold.protocols.mcp import McpDeployerClient  # noqa: PLC0415

    if mcp_deployer is not None and isinstance(mcp_deployer, McpDeployerClient):
        invokers[TargetKind.LOCAL_HOST] = make_local_host_invoker(
            deployer=mcp_deployer,
            registry=mcp_registry,
            http=mcp_http,
        )

    emissary = Emissary(
        catalog=mcp_tool_catalog,
        keyward=keyward,
        warden=warden,
        composer=composer,
        invokers=invokers,
        persist_register=(
            _persist_registration_upsert if registration_persistence is not None else None
        ),
        persist_unregister=(
            _persist_registration_remove if registration_persistence is not None else None
        ),
    )
    tool_declaration_validator = ToolDeclarationValidator(catalog=mcp_tool_catalog)
    logger.info(
        "Emissary plane wired (invokers=%s)",
        sorted(str(k) for k in invokers),
    )

    # Hydrate from Postgres at startup. Persisters return real records;
    # we use the hydrate_* methods (which skip write-through) so we don't
    # echo back into the database during recovery.
    if (
        catalog_persistence is not None
        and registration_persistence is not None
        and revocation_persistence is not None
        and composite_persistence is not None
    ):
        from stronghold.persistence.pg_mcp import (  # noqa: PLC0415
            hydrate_emissary_plane,
        )

        hydrated = await hydrate_emissary_plane(
            catalog_persistence=catalog_persistence,
            registration_persistence=registration_persistence,
            revocation_persistence=revocation_persistence,
            composite_persistence=composite_persistence,
            catalog_apply=mcp_tool_catalog.hydrate,
            registration_apply=emissary.hydrate_backend,
            revocation_apply=lambda token_id: keyward.hydrate_revocations([token_id]),
            composite_apply=composer.hydrate,
        )
        logger.info("Emissary plane hydrated from Postgres: %s", hydrated)

    # Bootstrap approved tools from a YAML file if configured. The loader
    # populates both the catalog and the Emissary backends from a single
    # source of truth so the two stay in sync.
    if config.mcp_tools_file:
        from stronghold.mcp.registration_loader import (  # noqa: PLC0415
            RegistrationFileError,
            load_registrations,
        )

        try:
            count = load_registrations(
                path=config.mcp_tools_file,
                catalog=mcp_tool_catalog,
                emissary=emissary,
            )
            logger.info("Emissary backends loaded from %s: %d", config.mcp_tools_file, count)
        except RegistrationFileError as exc:
            # Fail hard at startup — partial registration is worse than not
            # starting at all.
            raise ConfigError(f"mcp_tools_file load failed: {exc}") from exc

    container = Container(
        config=config,
        auth_provider=auth_provider,
        permission_table=permission_table,
        router=router,
        classifier=classifier,
        quota_tracker=quota_tracker,
        prompt_manager=prompt_manager,
        learning_store=learning_store,
        learning_extractor=learning_extractor,
        outcome_store=outcome_store,
        session_store=session_store,
        audit_log=audit_log,
        warden=warden,
        gate=gate,
        sentinel=sentinel,
        tracer=tracer,
        context_builder=context_builder,
        intent_registry=intent_registry,
        llm=llm,
        tool_registry=tool_registry,
        tool_dispatcher=tool_dispatcher,
        playbook_registry=playbook_registry,
        tool_policy=tool_policy,
        tool_catalog=tool_catalog,
        skill_catalog=skill_catalog,
        resource_catalog=resource_catalog,
        agent_store=InMemoryAgentStore(agents, prompt_manager),
        rate_limiter=rate_limiter,
        reactor=reactor,
        agents=agents,
        coin_ledger=coin_ledger,
        tournament=tournament,
        canary_manager=canary_manager,
        learning_approval_gate=approval_gate,
        learning_promoter=learning_promoter,
        strike_tracker=strike_tracker,
        db_pool=db_pool,
        sa_engine=sa_engine,
        redis_client=redis_client,
        prompt_cache=prompt_cache,
        mcp_registry=mcp_registry,
        mcp_deployer=mcp_deployer,
        mcp_tool_catalog=mcp_tool_catalog,
        keyward=keyward,
        composer=composer,
        mcp_client=mcp_client,
        emissary=emissary,
        tool_declaration_validator=tool_declaration_validator,
    )

    # Conduit pipeline is auto-wired via __post_init__

    # Register reactor triggers (after container is built)
    from stronghold.triggers import register_core_triggers  # noqa: PLC0415

    register_core_triggers(container)

    return container
