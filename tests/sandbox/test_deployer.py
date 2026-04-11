"""Tests for MCPDeployerClient (ADR-K8S-025/026)."""

from __future__ import annotations

from stronghold.sandbox.deployer import FakeMCPDeployerClient


async def test_spawn_returns_pod_metadata() -> None:
    deployer = FakeMCPDeployerClient()
    result = await deployer.spawn("sandbox.shell", tenant_id="acme", user_id="alice")
    assert "pod_id" in result
    assert result["status"] == "running"
    assert result["tenant_id"] == "acme"
    assert result["template"] == "sandbox.shell"
    assert "endpoint" in result


async def test_spawn_unique_ids() -> None:
    deployer = FakeMCPDeployerClient()
    r1 = await deployer.spawn("sandbox.shell", tenant_id="acme")
    r2 = await deployer.spawn("sandbox.python", tenant_id="acme")
    assert r1["pod_id"] != r2["pod_id"]


async def test_reap_existing_pod() -> None:
    deployer = FakeMCPDeployerClient()
    result = await deployer.spawn("sandbox.shell", tenant_id="acme")
    assert await deployer.reap(result["pod_id"]) is True


async def test_reap_nonexistent_pod() -> None:
    deployer = FakeMCPDeployerClient()
    assert await deployer.reap("nonexistent") is False


async def test_status_running_pod() -> None:
    deployer = FakeMCPDeployerClient()
    result = await deployer.spawn("sandbox.shell", tenant_id="acme")
    status = await deployer.status(result["pod_id"])
    assert status["status"] == "running"


async def test_status_not_found() -> None:
    deployer = FakeMCPDeployerClient()
    status = await deployer.status("nonexistent")
    assert status["status"] == "not_found"


async def test_list_active_all() -> None:
    deployer = FakeMCPDeployerClient()
    await deployer.spawn("sandbox.shell", tenant_id="acme")
    await deployer.spawn("sandbox.python", tenant_id="evil")
    pods = await deployer.list_active()
    assert len(pods) == 2


async def test_list_active_filtered() -> None:
    deployer = FakeMCPDeployerClient()
    await deployer.spawn("sandbox.shell", tenant_id="acme")
    await deployer.spawn("sandbox.python", tenant_id="evil")
    pods = await deployer.list_active(tenant_id="acme")
    assert len(pods) == 1
    assert pods[0]["tenant_id"] == "acme"


async def test_health() -> None:
    deployer = FakeMCPDeployerClient()
    assert await deployer.health() is True


async def test_close() -> None:
    deployer = FakeMCPDeployerClient()
    await deployer.close()  # Should not raise


async def test_spawn_with_env_overrides() -> None:
    deployer = FakeMCPDeployerClient()
    result = await deployer.spawn(
        "sandbox.shell", tenant_id="acme",
        env_overrides={"CUSTOM_VAR": "value"},
    )
    assert result["status"] == "running"


async def test_spawn_endpoint_is_valid_k8s_dns() -> None:
    deployer = FakeMCPDeployerClient()
    result = await deployer.spawn("sandbox.shell", tenant_id="acme")
    endpoint = result["endpoint"]
    assert endpoint.startswith("http://")
    assert ".svc.cluster.local:" in endpoint
    assert result["pod_id"] in endpoint


async def test_reap_then_status_not_found() -> None:
    deployer = FakeMCPDeployerClient()
    result = await deployer.spawn("sandbox.shell", tenant_id="acme")
    await deployer.reap(result["pod_id"])
    status = await deployer.status(result["pod_id"])
    assert status["status"] == "not_found"


async def test_spawn_preserves_session_id() -> None:
    deployer = FakeMCPDeployerClient()
    result = await deployer.spawn("sandbox.shell", tenant_id="acme", session_id="sess-123")
    status = await deployer.status(result["pod_id"])
    assert status["session_id"] == "sess-123"


# ── Real MCPDeployerClient HTTP tests (respx-mocked) ────────────────

import httpx
import pytest
import respx

from stronghold.sandbox.deployer import MCPDeployerClient


@respx.mock
async def test_real_client_init_default_url() -> None:
    """Default URL comes from env var or localhost:8300."""
    client = MCPDeployerClient()
    assert client._base_url
    await client.close()


@respx.mock
async def test_real_client_custom_url() -> None:
    client = MCPDeployerClient(base_url="http://custom:9000")
    assert client._base_url == "http://custom:9000"
    await client.close()


@respx.mock
async def test_real_client_spawn_posts_correct_payload() -> None:
    route = respx.post("http://localhost:8300/spawn").mock(
        return_value=httpx.Response(200, json={
            "pod_id": "sandbox-abc",
            "status": "running",
            "endpoint": "http://sandbox-abc.stronghold-mcp.svc.cluster.local:3000",
        }),
    )
    client = MCPDeployerClient()
    result = await client.spawn(
        "sandbox.python", tenant_id="acme", user_id="alice",
        session_id="s-1", env_overrides={"X": "y"},
    )
    assert route.called
    sent = route.calls.last.request
    import json as _json
    body = _json.loads(sent.content)
    assert body["template"] == "sandbox.python"
    assert body["tenant_id"] == "acme"
    assert body["user_id"] == "alice"
    assert body["session_id"] == "s-1"
    assert body["env"] == {"X": "y"}
    assert result["pod_id"] == "sandbox-abc"
    await client.close()


@respx.mock
async def test_real_client_spawn_raises_on_5xx() -> None:
    respx.post("http://localhost:8300/spawn").mock(
        return_value=httpx.Response(500, text="internal error"),
    )
    client = MCPDeployerClient()
    with pytest.raises(httpx.HTTPStatusError):
        await client.spawn("sandbox.shell", tenant_id="acme")
    await client.close()


@respx.mock
async def test_real_client_reap_uses_post() -> None:
    route = respx.post("http://localhost:8300/reap").mock(
        return_value=httpx.Response(200, json={"ok": True}),
    )
    client = MCPDeployerClient()
    result = await client.reap("sandbox-abc")
    assert route.called
    assert result is True
    import json as _json
    body = _json.loads(route.calls.last.request.content)
    assert body == {"pod_id": "sandbox-abc"}
    await client.close()


@respx.mock
async def test_real_client_reap_404_returns_false() -> None:
    respx.post("http://localhost:8300/reap").mock(
        return_value=httpx.Response(404),
    )
    client = MCPDeployerClient()
    assert await client.reap("missing") is False
    await client.close()


@respx.mock
async def test_real_client_reap_5xx_raises() -> None:
    respx.post("http://localhost:8300/reap").mock(
        return_value=httpx.Response(500),
    )
    client = MCPDeployerClient()
    with pytest.raises(httpx.HTTPStatusError):
        await client.reap("x")
    await client.close()


@respx.mock
async def test_real_client_status_uses_get_with_path() -> None:
    respx.get("http://localhost:8300/status/sandbox-abc").mock(
        return_value=httpx.Response(
            200, json={"status": "running", "pod_id": "sandbox-abc"},
        ),
    )
    client = MCPDeployerClient()
    result = await client.status("sandbox-abc")
    assert result["status"] == "running"
    await client.close()


@respx.mock
async def test_real_client_health_ok() -> None:
    respx.get("http://localhost:8300/health").mock(return_value=httpx.Response(200))
    client = MCPDeployerClient()
    assert await client.health() is True
    await client.close()


@respx.mock
async def test_real_client_health_500() -> None:
    respx.get("http://localhost:8300/health").mock(return_value=httpx.Response(500))
    client = MCPDeployerClient()
    assert await client.health() is False
    await client.close()


@respx.mock
async def test_real_client_health_network_error() -> None:
    respx.get("http://localhost:8300/health").mock(
        side_effect=httpx.ConnectError("refused"),
    )
    client = MCPDeployerClient()
    assert await client.health() is False
    await client.close()


@respx.mock
async def test_real_client_list_active_passes_tenant_filter() -> None:
    route = respx.get("http://localhost:8300/list").mock(
        return_value=httpx.Response(
            200, json={"pods": [{"pod_id": "p1", "tenant_id": "acme"}]},
        ),
    )
    client = MCPDeployerClient()
    result = await client.list_active(tenant_id="acme")
    assert route.called
    assert route.calls.last.request.url.params["tenant_id"] == "acme"
    assert len(result) == 1
    await client.close()


@respx.mock
async def test_real_client_list_active_no_tenant() -> None:
    """No tenant filter → no query param."""
    route = respx.get("http://localhost:8300/list").mock(
        return_value=httpx.Response(200, json={"pods": []}),
    )
    client = MCPDeployerClient()
    result = await client.list_active()
    assert route.called
    assert result == []
    await client.close()
