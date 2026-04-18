"""Tests that Warden module has no dangerous imports."""

import importlib
import inspect


class TestWardenIsolation:
    def test_no_tool_imports(self) -> None:
        mod = importlib.import_module("stronghold.security.warden.detector")
        source = inspect.getsource(mod)
        assert "stronghold.tools" not in source
        assert "stronghold.skills" not in source

    def test_no_file_io_imports(self) -> None:
        mod = importlib.import_module("stronghold.security.warden.detector")
        source = inspect.getsource(mod)
        assert "open(" not in source
        assert "pathlib" not in source

    def test_scan_returns_only_verdict_no_side_channels(self) -> None:
        """Warden.scan must return a WardenVerdict carrying the scan result.

        Stronger than a type check: we verify the returned object's
        observable fields match what callers rely on. A regression that
        returned a bare dict or a subclass with leaked internals (e.g.
        exposing caller-private Warden state like seen_inputs) would fail.
        """
        import asyncio

        from stronghold.security.warden.detector import Warden
        from stronghold.types.security import WardenVerdict

        warden = Warden()
        verdict = asyncio.new_event_loop().run_until_complete(
            warden.scan("hello", "user_input"),
        )
        # Type invariant: real dataclass, not a subclass that smuggles state
        assert type(verdict) is WardenVerdict
        # Behavioral invariants for a clean input
        assert verdict.clean is True
        assert verdict.flags == ()
        assert verdict.blocked is False
