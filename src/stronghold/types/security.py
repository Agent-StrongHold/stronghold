"""Security types: Warden verdicts, Sentinel verdicts, audit entries, trust tiers.

Warden detects threats (two ingress points: user input + tool results).
Sentinel enforces policy (every boundary crossing).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from stronghold.types.auth import AuthContext


class TrustTier(StrEnum):
    """Trust tiers for agents and skills.

    Promotion requires passing review gates. Provenance caps apply:
    community-origin agents can never exceed T3 regardless of reviews.

    Tier  | Path                                      | Reviews
    ------+-------------------------------------------+---------------------------
    T0    | Built-in (shipped with Stronghold)         | Code-reviewed, hardcoded
    T1    | Admin-created + AI security review         | Admin + Warden
    T2    | Admin-created (no review yet)              | Admin trust alone
          | OR User-created + AI review + admin review | User + Warden + Admin
    T3    | User-created + AI review                   | User + Warden
          | OR Community + user + AI + admin (CAPPED)  | All 4 gates, max for ext.
    T4    | User-created (no review)                   | Starting point
          | OR Community + user review + AI review     | 2 gates, no admin yet
    Skull | Community + raw user import                | Trust nothing
    """

    SKULL = "skull"  # Community import, no reviews, trust nothing
    T4 = "t4"  # User-created (no review) / community with user+AI review
    T3 = "t3"  # User + AI review / community capped here
    T2 = "t2"  # Admin-created / user + AI + admin review
    T1 = "t1"  # Admin-created + AI security review
    T0 = "t0"  # Built-in, shipped with Stronghold


class Provenance(StrEnum):
    """Origin of an agent or skill. Permanent — never changes after creation."""

    BUILTIN = "builtin"  # Shipped with Stronghold
    ADMIN = "admin"  # Created by an org admin
    USER = "user"  # Created by an approved user
    COMMUNITY = "community"  # Imported from external URL/marketplace


@dataclass(frozen=True)
class WardenVerdict:
    """Result of Warden threat detection scan."""

    clean: bool = True
    sanitized_content: str | None = None
    blocked: bool = False
    flags: tuple[str, ...] = ()
    confidence: float = 1.0
    reasoning_trace: str | None = None
    # Set when Warden detects something severe enough to invalidate
    # the credentials a tool was issued for the call. Drives the
    # Warden→Keyward revocation coupling at the Emissary boundary.
    revoke: RevocationCriteria | None = None


@dataclass(frozen=True)
class Violation:
    """A single policy violation detected by Sentinel."""

    boundary: str
    rule: str
    severity: str = "error"  # error, warning, info
    detail: str = ""
    repair_action: str | None = None


@dataclass(frozen=True)
class SentinelVerdict:
    """Result of Sentinel policy check."""

    allowed: bool = True
    repaired: bool = False
    repaired_data: Any = None
    violations: tuple[Violation, ...] = ()


@dataclass(frozen=True)
class AuditEntry:
    """A single audit log entry — every boundary crossing is logged."""

    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    boundary: str = ""
    user_id: str = ""
    org_id: str = ""
    team_id: str = ""
    agent_id: str = ""
    tool_name: str | None = None
    verdict: str = "allowed"
    violations: tuple[Violation, ...] = ()
    trace_id: str = ""
    request_id: str = ""
    detail: str = ""


@dataclass(frozen=True)
class GateResult:
    """Result of Gate input processing."""

    sanitized_text: str = ""
    improved_text: str | None = None
    clarifying_questions: tuple[ClarifyingQuestion, ...] = ()
    warden_verdict: WardenVerdict = field(default_factory=WardenVerdict)
    blocked: bool = False
    block_reason: str = ""
    # Strike escalation data (populated when blocked)
    strike_number: int = 0  # Current strike count after this violation
    scrutiny_level: str = "normal"  # normal | elevated | locked | disabled
    locked_until: str = ""  # ISO timestamp if locked
    account_disabled: bool = False


@dataclass(frozen=True)
class ClarifyingQuestion:
    """A question the Gate asks to improve the user's request."""

    question: str = ""
    options: tuple[str, ...] = ()  # a, b, c, d options
    allow_freetext: bool = True


# ---------------------------------------------------------------------------
# Tool catalog, credential issuance, and MCP gateway types.
#
# These power the Emissary (MCP gateway), Keyward (credential issuer), the
# Composer (composite tool orchestrator), and the Sentinel tool-declaration
# validator. Trust tier, Provenance, WardenVerdict, AuditEntry above carry
# their existing semantics — the new types compose with them.
# ---------------------------------------------------------------------------


class Scope(StrEnum):
    """Tool/permission scope walk. Maps onto AuthContext's org/team/user.

    PLATFORM is the implicit Stronghold-system level; only SYSTEM identity
    (SYSTEM_ORG_ID) approves at this scope.
    """

    USER = "user"
    TEAM = "team"
    ORG = "org"
    PLATFORM = "platform"


@dataclass(frozen=True)
class ToolFingerprint:
    """Canonical fingerprint of a tool declaration.

    ``value`` is the sha256 hex of the canonical JSON of (name, description,
    input_schema). ``schema_hash`` is the hash of input_schema alone — kept
    separately so rug-pull diagnostics can distinguish "name same, schema
    drifted" from "totally different tool".
    """

    value: str
    name: str
    schema_hash: str


@dataclass(frozen=True)
class CatalogEntry:
    """A tool's approval record at a specific scope level."""

    fingerprint: ToolFingerprint
    trust_tier: TrustTier
    provenance: Provenance
    approved_at_scope: Scope
    org_id: str = ""
    team_id: str = ""
    user_id: str = ""
    allowed_audiences: frozenset[str] = frozenset()
    declared_caps: frozenset[str] = frozenset()
    approved_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    approved_by: str = ""
    expires_at: datetime | None = None


@dataclass(frozen=True)
class RevocationCriteria:
    """Match criteria for revoking issued tokens.

    Any combination of fields narrows the set; an empty criteria revokes
    nothing (revoke is not a wildcard).
    """

    token_id: str | None = None
    tool: ToolFingerprint | None = None
    user_id: str | None = None
    audience: str | None = None
    reason: str = ""


@dataclass(frozen=True)
class IssuedToken:
    """A short-lived credential minted by Keyward for a tool call."""

    id: str  # JTI
    tool: ToolFingerprint
    principal_user_id: str
    principal_org_id: str
    audience: str  # canonical URI per RFC 8707
    scopes: frozenset[str]
    issued_at: datetime
    ttl_seconds: int
    serialized: str  # JWT or compatible bearer string


@dataclass(frozen=True)
class TokenRequest:
    """Caller's request for a per-call token."""

    tool: ToolFingerprint
    auth: AuthContext
    audience: str
    requested_scopes: frozenset[str]
    call_id: str
    idempotency_key: str | None = None


@dataclass(frozen=True)
class TokenResult:
    """Keyward's response. Exactly one of token / error_kind is non-empty."""

    token: IssuedToken | None = None
    error: str | None = None
    error_kind: str = ""  # unauthorized | audience_denied | scope_escalation | unavailable


@dataclass(frozen=True)
class TokenStatus:
    """Current state of an issued token (introspection result)."""

    token_id: str
    revoked: bool
    expires_at: datetime


# --- Sessions (Emissary) -------------------------------------------------


@dataclass(frozen=True)
class SessionId:
    """Opaque session handle returned by Emissary.start_session."""

    value: str


@dataclass(frozen=True)
class Session:
    """An Emissary session bound to one principal for stateful tools."""

    id: SessionId
    auth: AuthContext
    started_at: datetime
    last_activity: datetime
    affinity_instance: str | None = None
    active_tools: frozenset[ToolFingerprint] = frozenset()


# --- MCP gateway request/response ----------------------------------------


class TargetKind(StrEnum):
    """How a tool is realised behind the gateway."""

    COMPOSITE = "composite"
    LOCAL_HOST = "local_host"
    REMOTE_PROXY = "remote_proxy"
    FIRST_PARTY = "first_party"


@dataclass(frozen=True)
class ToolDescriptor:
    """A single entry in the principal-filtered tools list."""

    fingerprint: ToolFingerprint
    name: str
    description: str
    input_schema: dict[str, Any]
    target_kind: TargetKind
    trust_tier: TrustTier
    scope: Scope


@dataclass(frozen=True)
class ToolCallRequest:
    """A single tool invocation routed through Emissary."""

    fingerprint: ToolFingerprint
    args: dict[str, Any]
    auth: AuthContext
    session: SessionId | None = None
    call_id: str = ""
    idempotency_key: str | None = None


@dataclass(frozen=True)
class ToolCallResult:
    """Result of an Emissary tool invocation, including the Warden verdict."""

    content: Any
    is_error: bool
    warden_verdict: WardenVerdict
    duration_ms: int = 0
    token_id: str | None = None
    partial: bool = False


# --- Composites ----------------------------------------------------------


@dataclass(frozen=True)
class CompositeStep:
    """One step in a composite definition."""

    id: str
    tool: ToolFingerprint
    args_template: dict[str, Any]
    on_error: str = "abort"  # retry | skip | abort | rollback
    parallel_group: str | None = None


@dataclass(frozen=True)
class CompositeDefinition:
    """A higher-level tool composed of atomic steps."""

    fingerprint: ToolFingerprint
    name: str
    description: str
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    steps: tuple[CompositeStep, ...]
    # Effective tier of the composite — must be ≤ min(constituent atomic tiers).
    trust_tier: TrustTier = TrustTier.T3


@dataclass(frozen=True)
class StepResult:
    """Outcome of one composite step."""

    step_id: str
    output: Any = None
    error: str | None = None


@dataclass(frozen=True)
class CompositeResult:
    """Aggregate composite outcome. ``partial`` flags any non-clean exit."""

    outputs: dict[str, Any]
    step_results: tuple[StepResult, ...]
    partial: bool = False
