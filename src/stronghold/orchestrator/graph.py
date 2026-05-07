"""Pipeline graph data model — PipelineNode and PipelineGraph."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Iterable, Iterator

# Maps node_name → output text produced by that node.
RunContext = dict[str, str]


@dataclass(frozen=True)
class PipelineNode:
    """A single node in the pipeline DAG."""

    name: str
    agent_name: str
    prompt_template: str
    depends_on: tuple[str, ...] = ()
    skip_if: Callable[[RunContext], bool] | None = None
    timeout_seconds: float = 600.0
    on_complete: Callable[[Any, str], Awaitable[None]] | None = None


class PipelineGraph:
    """Directed acyclic graph of PipelineNodes."""

    def __init__(self, nodes: Iterable[PipelineNode]) -> None:
        self._nodes: dict[str, PipelineNode] = {}
        for node in nodes:
            if node.name in self._nodes:
                raise ValueError(f"Duplicate node name: {node.name!r}")
            self._nodes[node.name] = node

    def ready(
        self,
        completed: frozenset[str],
        skipped: frozenset[str],
    ) -> list[PipelineNode]:
        """Nodes whose every dependency is in completed | skipped, and which
        are not themselves already in completed | skipped."""
        satisfied = completed | skipped
        return [
            node
            for node in self._nodes.values()
            if node.name not in satisfied and all(dep in satisfied for dep in node.depends_on)
        ]

    def validate(self) -> list[str]:
        """Return error strings. Empty list means the graph is valid."""
        errors: list[str] = []
        names = set(self._nodes)

        for node in self._nodes.values():
            for dep in node.depends_on:
                if dep not in names:
                    errors.append(f"Node {node.name!r} depends on undeclared node {dep!r}")

        # Three-color DFS cycle detection (0=white/unvisited, 1=gray/active, 2=black/done)
        color: dict[str, int] = {n: 0 for n in names}

        def _dfs(name: str) -> bool:
            color[name] = 1
            node = self._nodes.get(name)
            if node:
                for dep in node.depends_on:
                    if dep not in color:
                        continue
                    if color[dep] == 1:
                        errors.append(f"Cycle detected involving node {dep!r}")
                        return True
                    if color[dep] == 0 and _dfs(dep):
                        return True
            color[name] = 2
            return False

        for name in names:
            if color[name] == 0:
                _dfs(name)

        return errors

    def __len__(self) -> int:
        return len(self._nodes)

    def __contains__(self, name: object) -> bool:
        return name in self._nodes

    def __iter__(self) -> Iterator[PipelineNode]:
        return iter(self._nodes.values())
