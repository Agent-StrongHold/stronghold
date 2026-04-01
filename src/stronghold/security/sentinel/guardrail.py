"""Unified guardrail interface chaining Sentinel validation, PII filter, and token optimizer.

LiteLLM guardrail plugin entry point: validates tool arguments before calls,
filters PII and optimizes tokens after calls. Every boundary crossing is audit-logged.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from stronghold.types.security import AuditEntry, Violation

if TYPE_CHECKING:
    from collections.abc import Callable

    from stronghold.protocols.memory import AuditLog
    from stronghold.security.sentinel.pii_filter import PIIMatch
    from stronghold.types.auth import AuthContext
    from stronghold.types.security import SentinelVerdict

    # Type aliases for the pluggable callables
    ValidatorFn = Callable[[dict[str, Any], dict[str, Any]], SentinelVerdict]
    PIIFilterFn = Callable[[str], tuple[str, list[PIIMatch]]]
    TokenOptimizerFn = Callable[[str, str], str]

logger = logging.getLogger("stronghold.sentinel.guardrail")


class SentinelGuardrail:
    """Unified guardrail chaining validation, PII filter, and token optimization.

    pre_call: validate + repair args against schema, audit log.
    post_call: PII filter, token optimize, audit log.
    """

    def __init__(
        self,
        *,
        validator: ValidatorFn,
        pii_filter: PIIFilterFn,
        token_optimizer: TokenOptimizerFn,
        audit_log: AuditLog | None = None,
    ) -> None:
        self._validator = validator
        self._pii_filter = pii_filter
        self._token_optimizer = token_optimizer
        self._audit_log = audit_log

    async def pre_call(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        schema: dict[str, Any] | None = None,
        auth: AuthContext | None = None,
    ) -> dict[str, Any]:
        """Validate and repair args against schema, audit log the call.

        Returns cleaned arguments. When no schema is provided, arguments
        pass through unchanged.
        """
        violations: list[Violation] = []
        cleaned = dict(arguments)
        repaired = False

        if schema is not None:
            verdict = self._validator(arguments, schema)
            if verdict.violations:
                violations.extend(verdict.violations)
            if verdict.repaired and verdict.repaired_data is not None:
                cleaned = dict(verdict.repaired_data)
                repaired = True

        await self._log_audit(
            boundary="pre_call",
            tool_name=tool_name,
            auth=auth,
            verdict_str="allowed",
            violations=tuple(violations),
            detail=f"repaired={repaired}" if repaired else "",
        )

        return cleaned

    async def post_call(
        self,
        tool_name: str,
        result: str,
        auth: AuthContext | None = None,
    ) -> str:
        """PII filter on result, token optimize, audit log.

        Returns cleaned result string.
        """
        violations: list[Violation] = []
        processed = result

        # 1. PII filter
        processed, pii_matches = self._pii_filter(processed)
        if pii_matches:
            violations.append(
                Violation(
                    boundary="post_call",
                    rule="pii_detected",
                    severity="warning",
                    detail=f"Redacted {len(pii_matches)} PII pattern(s): "
                    + ", ".join(m.pii_type for m in pii_matches),
                )
            )

        # 2. Token optimization
        processed = self._token_optimizer(processed, tool_name)

        # 3. Audit log
        verdict_str = "clean" if not violations else "flagged"
        await self._log_audit(
            boundary="post_call",
            tool_name=tool_name,
            auth=auth,
            verdict_str=verdict_str,
            violations=tuple(violations),
        )

        return processed

    async def _log_audit(
        self,
        *,
        boundary: str,
        tool_name: str,
        auth: AuthContext | None,
        verdict_str: str,
        violations: tuple[Violation, ...] = (),
        detail: str = "",
    ) -> None:
        """Log an audit entry if audit_log is configured.

        Never raises -- audit failures are logged but do not block the request.
        """
        if self._audit_log is None:
            return
        try:
            await self._audit_log.log(
                AuditEntry(
                    boundary=boundary,
                    user_id=auth.user_id if auth else "",
                    org_id=auth.org_id if auth else "",
                    team_id=auth.team_id if auth else "",
                    tool_name=tool_name,
                    verdict=verdict_str,
                    violations=violations,
                    detail=detail,
                )
            )
        except Exception:
            logger.exception("Audit log write failed (boundary=%s, tool=%s)", boundary, tool_name)
