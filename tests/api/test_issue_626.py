"""Tests for FakeOutcomeStore skeleton in tests/fakes.py."""

from __future__ import annotations

from pathlib import Path

FAKES_PY_PATH = Path(__file__).parent.parent / "tests" / "fakes.py"


class TestFakeOutcomeStoreSkeleton:
    def test_fake_outcome_store_class_exists(self) -> None:
        """Verify FakeOutcomeStore class skeleton exists in tests/fakes.py."""
        source = FAKES_PY_PATH.read_text()
        assert "class FakeOutcomeStore" in source
        # Find the class definition and check its body
        lines = source.splitlines()
        in_class = False
        class_lines = []
        for line in lines:
            if line.strip().startswith("class FakeOutcomeStore"):
                in_class = True
            elif in_class and (
                line.strip()
                and not line.strip().startswith("#")
                and not line.strip().startswith('"""')
            ):
                if line.strip().startswith(("def ", "async def ")):
                    break
                class_lines.append(line)
        # Class body should be empty or only contain pass
        class_body = "\n".join(class_lines).strip()
        assert class_body == "" or class_body == "pass", f"Unexpected class body: {class_body}"

    def test_fake_outcome_store_implements_outcome_store_protocol(self) -> None:
        """Verify FakeOutcomeStore implements OutcomeStore protocol."""
        source = FAKES_PY_PATH.read_text()
        assert "class FakeOutcomeStore" in source
        # Check that it inherits from OutcomeStore or implements required methods
        lines = source.splitlines()
        in_class = False
        for line in lines:
            if line.strip().startswith("class FakeOutcomeStore"):
                in_class = True
                assert "(OutcomeStore)" in line, (
                    f"FakeOutcomeStore should inherit from OutcomeStore: {line}"
                )
            elif (
                in_class
                and line.strip().startswith("def ")
                or line.strip().startswith("async def ")
            ):
                break
