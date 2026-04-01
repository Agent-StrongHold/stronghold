Generate a new protocol (interface) for Stronghold with its required fake and DI wiring.

Given: $ARGUMENTS (protocol name and purpose, e.g., "EmbeddingProvider — vector embedding generation")

## Pre-checks

1. **Parse input**: Extract protocol name (PascalCase) and purpose.
2. **Collision check**: Search `src/stronghold/protocols/` for existing protocols with similar names.
3. **Guard check**: Verify the protocol's purpose is mentioned in ARCHITECTURE.md.

## Generate files

### 1. Protocol definition: `src/stronghold/protocols/{name_snake}.py`

```python
"""Protocol for {purpose}."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

@runtime_checkable
class {ProtocolName}(Protocol):
    """TODO: Add docstring describing the contract."""

    async def {primary_method}(self, ...) -> ...:
        """TODO: Define the primary method signature."""
        ...
```

Follow existing protocol patterns:
- Read 2-3 existing protocols from `src/stronghold/protocols/` for style reference
- Use `@runtime_checkable` for all protocols
- Use `from __future__ import annotations`
- All methods async unless there's a strong reason not to
- Type hints on everything (mypy --strict)

### 2. Fake implementation: append to `tests/fakes.py`

```python
class Fake{ProtocolName}:
    """Fake {ProtocolName} for testing."""

    def __init__(self) -> None:
        self.calls: list[...] = []

    async def {primary_method}(self, ...) -> ...:
        self.calls.append(...)
        return ...  # sensible default
```

### 3. Fixture: append to `tests/conftest.py`

```python
@pytest.fixture
def fake_{name_snake}() -> Fake{ProtocolName}:
    return Fake{ProtocolName}()
```

### 4. Test stub: `tests/protocols/test_{name_snake}.py`

```python
def test_{name_snake}_fake_satisfies_protocol():
    """Verify the fake implements the protocol."""
    assert isinstance(Fake{ProtocolName}(), {ProtocolName})
```

## After generation

- Show the user where to wire the protocol in `container.py` (DI container)
- Remind: "Add the real implementation when you have one. The fake is enough to start writing dependent code."
- Run `pytest tests/ -x -q` to verify the fake satisfies the protocol
