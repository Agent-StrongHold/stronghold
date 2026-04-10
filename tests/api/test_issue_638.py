"""Tests for AuditLog protocol in memory.py."""

from __future__ import annotations

import pytest
from fastapi import FastAPI

from stronghold.security.sentinel.audit import InMemoryAuditLog

AUTH_HEADER = {"Authorization": "Bearer sk-test"}


@pytest.fixture
def app() -> FastAPI:
    """Create a FastAPI app with test container."""
    app = FastAPI()
    container = make_test_container()  # All 12+ required fields handled
    app.state.container = container
    return app


def test_auditlog_protocol_methods() -> None:
    """Verify AuditLog protocol methods and their signatures."""

    # Create an instance of the concrete implementation
    audit_log = InMemoryAuditLog()

    # Verify the protocol methods exist and are callable
    assert hasattr(audit_log, "log")
    assert callable(audit_log.log)

    assert hasattr(audit_log, "get_entries")
    assert callable(audit_log.get_entries)

    # Verify method signatures
    import inspect

    log_sig = inspect.signature(audit_log.log)
    assert log_sig.parameters["entry"].annotation is not None

    entries_sig = inspect.signature(audit_log.get_entries)
    assert "user_id" in entries_sig.parameters
    assert "agent_id" in entries_sig.parameters
    assert "org_id" in entries_sig.parameters
    assert "limit" in entries_sig.parameters


def test_auditlog_protocol_is_readable() -> None:
    """Verify AuditLog protocol definition is accessible and readable."""

    # Import the protocol directly
    from typing import Protocol

    from stronghold.security.sentinel.audit import InMemoryAuditLog

    # Verify the protocol exists and is a proper Protocol type
    assert isinstance(InMemoryAuditLog, type(Protocol))

    # Verify the protocol has the expected methods defined
    assert hasattr(InMemoryAuditLog, "log")
    assert hasattr(InMemoryAuditLog, "get_entries")

    # Verify method signatures in the protocol
    import inspect

    log_sig = inspect.signature(InMemoryAuditLog.log)
    assert "entry" in log_sig.parameters

    entries_sig = inspect.signature(InMemoryAuditLog.get_entries)
    assert "user_id" in entries_sig.parameters
    assert "agent_id" in entries_sig.parameters
    assert "org_id" in entries_sig.parameters
    assert "limit" in entries_sig.parameters
