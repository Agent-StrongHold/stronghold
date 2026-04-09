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
            elif in_class:
                if (
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
