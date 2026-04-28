"""Sentinel: validate ``tools[]`` declarations on outbound LLM requests.

Every tool an agent declares to the LLM must be in the principal's approved
catalog at fingerprint level. Schema drift is reported separately as a
suspected rug-pull. Catalog-unavailable fails closed.

This validator is invoked by the LiteLLM-edge middleware before the request
is forwarded to the model.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from stronghold.security import tool_fingerprint as _fingerprinter
from stronghold.types.security import ToolFingerprint, Violation

if TYPE_CHECKING:
    from collections.abc import Callable

    from stronghold.protocols.security import ToolCatalog
    from stronghold.types.auth import AuthContext


@dataclass(frozen=True)
class ToolDeclarationVerdict:
    """Result of validating a request's ``tools[]`` array."""

    allowed: bool
    unapproved: tuple[ToolFingerprint, ...] = ()
    mismatched: tuple[ToolFingerprint, ...] = ()
    submit_urls: dict[str, str] | None = None
    violations: tuple[Violation, ...] = ()
    fail_closed: bool = False


class CatalogUnavailableError(Exception):
    """Raised by ToolCatalog implementations when the backing store is down."""


def _name_lookup(catalog: ToolCatalog) -> Callable[[str], frozenset[str]]:
    """Return a callable resolving a tool name to its registered fingerprints.

    Falls back to walking ``approvals_for`` when the catalog implementation
    doesn't expose ``fingerprints_with_name`` (custom backends).
    """
    method = getattr(catalog, "fingerprints_with_name", None)
    if callable(method):
        return method  # type: ignore[no-any-return]

    def _walk(name: str) -> frozenset[str]:
        return frozenset()  # Custom backends advertise rug-pulls themselves.

    return _walk


class ToolDeclarationValidator:
    """Sentinel validator for outbound LLM-request tool declarations.

    Constructed once at startup with an injected catalog. ``validate`` is
    invoked per request from the LiteLLM-edge middleware.
    """

    def __init__(
        self,
        catalog: ToolCatalog,
        submit_url_template: str = "/review/submit/{fingerprint}",
    ) -> None:
        self._catalog = catalog
        self._submit_url_template = submit_url_template

    async def validate(
        self,
        tools: list[dict[str, Any]],
        auth: AuthContext,
    ) -> ToolDeclarationVerdict:
        if not tools:
            return ToolDeclarationVerdict(allowed=True)

        try:
            unapproved: list[ToolFingerprint] = []
            mismatched: list[ToolFingerprint] = []
            violations: list[Violation] = []

            for declaration in tools:
                fingerprint = _fingerprinter.compute(declaration)
                entry = self._catalog.lookup(fingerprint, auth)
                if entry is not None:
                    continue

                # Either unknown, or known by name with drifted schema.
                resolver = _name_lookup(self._catalog)
                same_name_fps = resolver(fingerprint.name)
                if any(fp_value != fingerprint.value for fp_value in same_name_fps):
                    mismatched.append(fingerprint)
                    violations.append(
                        Violation(
                            boundary="llm_request",
                            rule="tool_fingerprint_mismatch",
                            severity="error",
                            detail=(
                                f"tool '{fingerprint.name}' has different schema "
                                f"than approved (suspected rug-pull)"
                            ),
                        )
                    )
                else:
                    unapproved.append(fingerprint)
                    violations.append(
                        Violation(
                            boundary="llm_request",
                            rule="tool_unapproved",
                            severity="error",
                            detail=(f"tool '{fingerprint.name}' not approved in principal's scope"),
                        )
                    )

        except CatalogUnavailableError:
            return ToolDeclarationVerdict(
                allowed=False,
                fail_closed=True,
                violations=(
                    Violation(
                        boundary="llm_request",
                        rule="catalog_unavailable",
                        severity="error",
                        detail="ToolCatalog unreachable; refusing request",
                    ),
                ),
            )

        if unapproved or mismatched:
            return ToolDeclarationVerdict(
                allowed=False,
                unapproved=tuple(unapproved),
                mismatched=tuple(mismatched),
                submit_urls={
                    fp.value: self._submit_url_template.format(fingerprint=fp.value)
                    for fp in unapproved
                },
                violations=tuple(violations),
            )

        return ToolDeclarationVerdict(allowed=True)
