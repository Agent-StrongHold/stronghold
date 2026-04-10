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

    from stronghold.security.sentinel.audit import AuditLogProtocol

    # Verify the protocol exists and is a proper Protocol type
    assert isinstance(AuditLogProtocol, type(Protocol))

    # Verify the protocol has the expected methods defined
    assert hasattr(AuditLogProtocol, "log")
    assert hasattr(AuditLogProtocol, "get_entries")

    # Verify method signatures in the protocol
    import inspect

    log_sig = inspect.signature(AuditLogProtocol.log)
    assert "entry" in log_sig.parameters

    entries_sig = inspect.signature(AuditLogProtocol.get_entries)
    assert "user_id" in entries_sig.parameters
    assert "agent_id" in entries_sig.parameters
    assert "org_id" in entries_sig.parameters
    assert "limit" in entries_sig.parameters


def test_auditlog_protocol_structure() -> None:
    """Verify AuditLog protocol structure by extracting all method names and parameter types."""

    import inspect

    from stronghold.security.sentinel.audit import AuditLogProtocol

    # Get all members of the protocol
    protocol_members = inspect.getmembers(AuditLogProtocol)

    # Filter for callable attributes (methods)
    methods = [
        name
        for name, member in protocol_members
        if inspect.isfunction(member) or inspect.ismethod(member)
    ]

    # Verify expected methods exist
    assert "log" in methods
    assert "get_entries" in methods

    # Extract method signatures
    log_sig = inspect.signature(AuditLogProtocol.log)
    get_entries_sig = inspect.signature(AuditLogProtocol.get_entries)

    # Verify parameter names and types for log method
    log_params = list(log_sig.parameters.keys())
    assert "entry" in log_params
    assert log_sig.parameters["entry"].annotation is not None

    # Verify parameter names and types for get_entries method
    entries_params = list(get_entries_sig.parameters.keys())
    expected_entries_params = ["user_id", "agent_id", "org_id", "limit"]
    for param in expected_entries_params:
        assert param in entries_params
        assert get_entries_sig.parameters[param].annotation is not None
