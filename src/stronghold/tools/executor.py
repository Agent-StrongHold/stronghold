"""Tool dispatcher: routes tool calls to registered executors.

Looks up the executor from the registry by name, runs the PreToolCall hook
chain (if configured), then calls the executor with a timeout and returns a
ToolResult. Falls back to HTTP endpoint if the tool definition has an
endpoint URL configured.

PreToolCall hooks (S1.2) are inspected between lookup and execution. Verdicts:
Allow (proceed), Deny (short-circuit, return error), Repair (mutate args for
subsequent hooks). An empty hook chain is a pass-through — back-compatible
with callers that construct ToolDispatcher(registry) and call
execute(tool_name, args).
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

from stronghold.protocols.tool_hooks import (
    AllowVerdict,
    DenyVerdict,
    RepairVerdict,
)
from stronghold.types.errors import ConfigError

if TYPE_CHECKING:
    from collections.abc import Sequence

    from stronghold.protocols.tool_hooks import PreToolCallHook
    from stronghold.security.sentinel.audit import InMemoryAuditLog
    from stronghold.tools.registry import InMemoryToolRegistry
    from stronghold.types.auth import AuthContext
    from stronghold.types.tool import ToolResult

logger = logging.getLogger("stronghold.tools.executor")

DEFAULT_TIMEOUT = 30.0  # seconds
DEFAULT_HOOK_TIMEOUT = 1.0  # seconds — fail-open on hook timeout


class ToolDispatcher:
    """Routes tool calls to registered executors with timeout protection.

    Hooks are inspected in order between tool lookup and execution. First deny
    short-circuits; repairs chain through to subsequent hooks and the executor.
    """

    def __init__(
        self,
        registry: InMemoryToolRegistry,
        default_timeout: float = DEFAULT_TIMEOUT,
        *,
        hooks: Sequence[PreToolCallHook] = (),
        hook_timeout: float = DEFAULT_HOOK_TIMEOUT,
        audit_log: InMemoryAuditLog | None = None,
    ) -> None:
        self._registry = registry
        self._default_timeout = default_timeout
        self._hooks: tuple[PreToolCallHook, ...] = tuple(hooks)
        self._hook_timeout = hook_timeout
        self._audit_log = audit_log

    async def execute(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        *,
        auth: AuthContext | None = None,
    ) -> str:
        """Execute a tool by name. Returns string result for LLM consumption.

        This is the callback signature expected by ReactStrategy's tool_executor.

        Args:
            tool_name: Registered tool name.
            arguments: Arguments forwarded to the executor (may be repaired by hooks).
            auth: AuthContext for the caller. Required when a hook chain is configured.

        Raises:
            ConfigError: hooks are configured but auth is None (fail-closed).
        """
        # Look up executor
        executor = self._registry.get_executor(tool_name)
        if executor is None:
            # Check if tool has an HTTP endpoint
            defn = self._registry.get(tool_name)
            if defn and defn.endpoint:
                return await self._execute_http(defn.endpoint, tool_name, arguments)
            return f"Error: Tool '{tool_name}' not registered"

        # Run the PreToolCall hook chain. Repairs chain; first deny short-circuits.
        if self._hooks:
            if auth is None:
                msg = (
                    "ToolDispatcher has hooks configured but received auth=None. "
                    "This would bypass every hook; refusing fail-closed."
                )
                raise ConfigError(msg)
            hook_outcome = await self._run_hook_chain(tool_name, arguments, auth)
            if isinstance(hook_outcome, DenyVerdict):
                return (
                    f"Error: Tool '{tool_name}' denied by {hook_outcome.hook_name}: "
                    f"{hook_outcome.reason}"
                )
            # hook_outcome is the (possibly repaired) arguments dict
            arguments = hook_outcome

        # Execute with timeout
        try:
            result: ToolResult = await asyncio.wait_for(
                executor(arguments),
                timeout=self._default_timeout,
            )
            return result.content if result.success else f"Error: {result.error}"
        except TimeoutError:
            logger.warning("Tool %s timed out after %ss", tool_name, self._default_timeout)
            return f"Error: Tool '{tool_name}' timed out after {self._default_timeout}s"
        except Exception as e:
            logger.warning("Tool %s failed: %s", tool_name, e)
            return f"Error: Tool '{tool_name}' failed: {e}"

    async def _run_hook_chain(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        auth: AuthContext,
    ) -> DenyVerdict | dict[str, Any]:
        """Run hooks in order. Returns DenyVerdict on block, else the final arguments."""
        current_args = dict(arguments)
        for hook in self._hooks:
            verdict = await self._call_hook(hook, tool_name, current_args, auth)
            await self._audit_verdict(tool_name, hook, verdict, auth)
            if isinstance(verdict, DenyVerdict):
                return verdict
            if isinstance(verdict, RepairVerdict):
                current_args = dict(verdict.new_arguments)
            # AllowVerdict: no-op
        return current_args

    async def _call_hook(
        self,
        hook: PreToolCallHook,
        tool_name: str,
        arguments: dict[str, Any],
        auth: AuthContext,
    ) -> AllowVerdict | DenyVerdict | RepairVerdict:
        """Call a single hook with a timeout. Fail-open on timeout or exception."""
        try:
            return await asyncio.wait_for(
                hook.check(tool_name, arguments, auth),
                timeout=self._hook_timeout,
            )
        except TimeoutError:
            logger.warning(
                "PreToolCall hook %s timed out on %s; treating as Allow",
                getattr(hook, "name", type(hook).__name__),
                tool_name,
            )
            return AllowVerdict()
        except Exception:
            logger.exception(
                "PreToolCall hook %s raised on %s; treating as Allow",
                getattr(hook, "name", type(hook).__name__),
                tool_name,
            )
            return AllowVerdict()

    async def _audit_verdict(
        self,
        tool_name: str,
        hook: PreToolCallHook,
        verdict: AllowVerdict | DenyVerdict | RepairVerdict,
        auth: AuthContext,
    ) -> None:
        """Emit one audit entry per hook verdict (AC 6)."""
        if self._audit_log is None:
            return
        from stronghold.types.security import AuditEntry  # noqa: PLC0415

        if isinstance(verdict, AllowVerdict):
            verdict_str = "allow"
            detail = ""
        elif isinstance(verdict, DenyVerdict):
            verdict_str = "deny"
            detail = verdict.reason
        else:
            verdict_str = "repair"
            detail = verdict.reason
        await self._audit_log.log(
            AuditEntry(
                boundary="pretool_hook",
                user_id=auth.user_id,
                org_id=auth.org_id,
                team_id=auth.team_id,
                tool_name=tool_name,
                verdict=verdict_str,
                detail=f"{getattr(hook, 'name', type(hook).__name__)}: {detail}",
            )
        )

    # SSRF protection: block internal/metadata endpoints
    # Covers full RFC1918, loopback, link-local, metadata, IPv6 private
    _BLOCKED_URL_PREFIXES = (
        # HTTP variants
        "http://localhost",
        "http://127.",  # Full 127.0.0.0/8
        "http://0.",
        "http://0.0.0.0",
        "http://[::1]",  # IPv6 loopback
        "http://[fe80:",  # IPv6 link-local
        "http://[fc",  # IPv6 unique local (fc00::/7)
        "http://[fd",  # IPv6 unique local (fc00::/7)
        "http://169.254.",  # AWS/cloud metadata
        "http://metadata.",
        "http://kubernetes.",
        "http://10.",  # RFC1918 10.0.0.0/8
        "http://172.16.",
        "http://172.17.",
        "http://172.18.",
        "http://172.19.",
        "http://172.20.",
        "http://172.21.",
        "http://172.22.",
        "http://172.23.",
        "http://172.24.",
        "http://172.25.",
        "http://172.26.",
        "http://172.27.",
        "http://172.28.",
        "http://172.29.",
        "http://172.30.",
        "http://172.31.",
        "http://192.168.",  # RFC1918 192.168.0.0/16
        # HTTPS variants — redirects from public HTTPS to private IPs
        "https://localhost",
        "https://127.",
        "https://0.",
        "https://0.0.0.0",
        "https://[::1]",
        "https://[fe80:",
        "https://[fc",
        "https://[fd",
        "https://169.254.",
        "https://metadata.",
        "https://kubernetes.",
        "https://10.",
        "https://172.16.",
        "https://172.17.",
        "https://172.18.",
        "https://172.19.",
        "https://172.20.",
        "https://172.21.",
        "https://172.22.",
        "https://172.23.",
        "https://172.24.",
        "https://172.25.",
        "https://172.26.",
        "https://172.27.",
        "https://172.28.",
        "https://172.29.",
        "https://172.30.",
        "https://172.31.",
        "https://192.168.",
        # Dangerous schemes
        "file://",
        "gopher://",
        "ftp://",
        "dict://",
        "ldap://",
    )

    @staticmethod
    def _resolve_blocks_private(hostname: str) -> str | None:
        """Resolve *hostname* via DNS and return the offending IP if any
        resolved address is private/internal. Returns None if all addresses
        are public (or the hostname cannot be resolved).

        This defeats DNS rebinding attacks where a hostname initially points
        at a public IP but later resolves to an internal one.
        """
        import ipaddress  # noqa: PLC0415
        import socket  # noqa: PLC0415

        try:
            addrinfos = socket.getaddrinfo(hostname, None, socket.AF_UNSPEC, socket.SOCK_STREAM)
        except socket.gaierror:
            return None  # Unresolvable — will fail at connect time

        for _family, _type, _proto, _canonname, sockaddr in addrinfos:
            ip_str: str = str(sockaddr[0])
            try:
                addr = ipaddress.ip_address(ip_str)
            except ValueError:
                continue
            if (
                addr.is_private
                or addr.is_loopback
                or addr.is_link_local
                or addr.is_reserved
                or addr.is_multicast
            ):
                return ip_str
        return None

    async def _execute_http(
        self,
        endpoint: str,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> str:
        """Fallback: execute tool via HTTP POST to configured endpoint.

        Validates endpoint URL against SSRF blocklist before making request.
        Includes DNS rebinding protection: hostnames are resolved and checked
        against the private IP blocklist.
        """
        from urllib.parse import urlparse  # noqa: PLC0415

        # SSRF protection: reject internal/dangerous URLs
        endpoint_lower = endpoint.lower()
        for prefix in self._BLOCKED_URL_PREFIXES:
            if endpoint_lower.startswith(prefix):
                logger.warning("SSRF blocked for tool %s: %s", tool_name, endpoint)
                return "Error: Tool endpoint blocked by security policy"

        if not endpoint_lower.startswith("https://"):
            logger.warning("Non-HTTPS endpoint for tool %s: %s", tool_name, endpoint)
            return "Error: Tool endpoints must use HTTPS"

        # DNS rebinding protection: resolve hostname and verify it's not internal
        try:
            parsed = urlparse(endpoint)
            hostname = parsed.hostname or ""
        except Exception:
            logger.warning("Malformed endpoint URL for tool %s: %s", tool_name, endpoint)
            return "Error: Malformed tool endpoint URL"

        if hostname:
            blocked_ip = self._resolve_blocks_private(hostname)
            if blocked_ip is not None:
                logger.warning(
                    "SSRF DNS rebinding blocked for tool %s: %s resolves to %s",
                    tool_name,
                    hostname,
                    blocked_ip,
                )
                return "Error: Tool endpoint blocked by security policy"

        try:
            import httpx  # noqa: PLC0415

            async with httpx.AsyncClient(
                timeout=self._default_timeout,
                follow_redirects=False,
            ) as client:
                resp = await client.post(
                    endpoint,
                    json={"tool_name": tool_name, "arguments": arguments},
                )
                if resp.status_code == 200:  # noqa: PLR2004
                    data = resp.json()
                    return str(data.get("result", data.get("content", str(data))))
                return f"Error: HTTP tool returned {resp.status_code}"
        except Exception as e:
            return f"Error: HTTP tool '{tool_name}' failed: {e}"
