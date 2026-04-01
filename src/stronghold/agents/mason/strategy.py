"""Mason strategy: incremental commits with issue documentation.

Each step produces a small, committed artifact documented on the
GitHub issue. Nothing is wasted — every step is a save point.

Pipeline:
  1. Post architecture plan as issue comment
  2. Post acceptance criteria as issue comment
  3. Generate + commit evidence-driven tests (TDD stubs)
  4. Generate + commit implementation (make tests pass)
  5. Document red/green in issue comment
  6. Generate + commit edge case tests
  7. Post summary to issue
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Coroutine
from typing import TYPE_CHECKING, Any

from stronghold.types.agent import ReasoningResult

if TYPE_CHECKING:
    from stronghold.protocols.llm import LLMClient
    from stronghold.protocols.tracing import Trace
    from stronghold.types.agent import AgentIdentity

logger = logging.getLogger("stronghold.mason.strategy")

StatusCallback = Callable[[str], Coroutine[Any, Any, None]]


async def _noop_status(msg: str) -> None:
    pass


class MasonStrategy:
    """Incremental strategy — small commits, each documented on the issue."""

    async def reason(
        self,
        messages: list[dict[str, Any]],
        model: str,
        llm: LLMClient,
        *,
        tools: list[dict[str, Any]] | None = None,
        tool_executor: Any = None,
        identity: AgentIdentity | None = None,
        status_callback: StatusCallback | None = None,
        trace: Trace | None = None,
        **kwargs: Any,
    ) -> ReasoningResult:
        """Run the incremental pipeline."""
        status = status_callback or _noop_status
        tool_history: list[dict[str, Any]] = []
        ex = tool_executor

        # Extract context from messages
        ws_path = ""
        issue_num = 0
        owner = ""
        repo = ""
        issue_title = ""
        for m in messages:
            c = str(m.get("content", ""))
            for line in c.split("\n"):
                s = line.strip()
                if s.startswith("Workspace:"):
                    ws_path = s.split(":", 1)[1].strip()
                elif s.startswith("Repository:"):
                    parts = s.split(":", 1)[1].strip().split("/")
                    if len(parts) == 2:
                        owner, repo = parts[0].strip(), parts[1].strip()
                elif "issue #" in s.lower():
                    import re

                    match = re.search(r"#(\d+)", s)
                    if match:
                        issue_num = int(match.group(1))
                    # Title is after the number
                    title_match = re.search(r"#\d+:?\s*(.*)", s)
                    if title_match:
                        issue_title = title_match.group(1).strip()

        if not ws_path or not issue_num:
            return ReasoningResult(
                response="Missing workspace or issue number.",
                done=True,
            )

        # Helper: ask LLM a question and get text back
        async def ask_llm(prompt: str) -> str:
            await status("  LLM thinking...")
            heartbeat = asyncio.create_task(_heartbeat(status))
            try:
                resp = await llm.complete(
                    [{"role": "user", "content": prompt}],
                    model,
                )
            finally:
                heartbeat.cancel()
            return resp.get("choices", [{}])[0].get("message", {}).get("content", "")

        # Helper: post comment on GitHub issue
        async def comment(body: str) -> None:
            if ex:
                await ex(
                    "github",
                    {
                        "action": "post_pr_comment",
                        "owner": owner,
                        "repo": repo,
                        "issue_number": issue_num,
                        "body": body,
                    },
                )

        # Helper: read a file from workspace
        async def read_file(path: str) -> str:
            if not ex:
                return ""
            result = await ex(
                "file_ops",
                {
                    "action": "read",
                    "path": path,
                    "workspace": ws_path,
                },
            )
            r = str(result)
            if "Error" in r[:20] or "not found" in r:
                return ""
            return r

        # Helper: write a file to workspace
        async def write_file(path: str, content: str) -> bool:
            if not ex:
                return False
            await ex(
                "file_ops",
                {
                    "action": "write",
                    "path": path,
                    "content": content,
                    "workspace": ws_path,
                },
            )
            return True

        # Helper: commit and push
        async def save(msg: str) -> None:
            if not ex:
                return
            await ex(
                "workspace",
                {
                    "action": "commit",
                    "issue_number": issue_num,
                    "message": msg,
                },
            )
            await ex(
                "workspace",
                {
                    "action": "push",
                    "issue_number": issue_num,
                },
            )

        # ── STEP 1: Architecture Plan ──
        await status("Step 1/7: Architecture plan")
        plan = await ask_llm(
            f"You are analyzing GitHub issue #{issue_num}: {issue_title}\n\n"
            f"Write a short architecture plan (under 300 words):\n"
            f"- What modules/files need to change\n"
            f"- How the change fits into the existing architecture\n"
            f"- Any protocols or types needed\n"
            f"- Testing approach\n\n"
            f"Be specific about file paths. This is for the Stronghold "
            f"agent governance platform (Python, FastAPI, protocol-driven DI)."
        )
        await comment(f"## Architecture Plan\n\n{plan}\n\n---\n*Mason — Step 1/7*")
        await status("Step 1 complete — architecture plan posted")

        # ── STEP 2: Acceptance Criteria ──
        await status("Step 2/7: Acceptance criteria")
        criteria = await ask_llm(
            f"Based on this architecture plan for issue #{issue_num}:\n\n"
            f"{plan}\n\n"
            f"Write testable acceptance criteria. Each criterion must be:\n"
            f"- A concrete, falsifiable statement\n"
            f"- Mappable to at least one test\n"
            f"Format as a numbered list."
        )
        await comment(f"## Acceptance Criteria\n\n{criteria}\n\n---\n*Mason — Step 2/7*")
        await status("Step 2 complete — acceptance criteria posted")

        # ── STEP 3: Evidence-driven tests (TDD stubs) ──
        await status("Step 3/7: Writing tests")

        # Read existing relevant files for context
        existing_context = ""
        if "fakes.py" in plan or "tests/" in plan:
            fakes = await read_file("tests/fakes.py")
            if fakes:
                existing_context += f"tests/fakes.py (first 2000 chars):\n{fakes[:2000]}\n\n"

        test_code = await ask_llm(
            f"Issue #{issue_num}: {issue_title}\n\n"
            f"Architecture plan:\n{plan}\n\n"
            f"Acceptance criteria:\n{criteria}\n\n"
            f"{existing_context}"
            f"Write a pytest test file that validates EACH acceptance "
            f"criterion. Rules:\n"
            f"- Use real classes, NEVER unittest.mock\n"
            f"- Import from stronghold.* (the real package)\n"
            f"- Use fakes from tests/fakes.py where needed\n"
            f"- Tests should FAIL initially (TDD red phase)\n\n"
            f"Output ONLY the Python code, no markdown fences, no explanation. "
            f"Start with the imports."
        )

        # Determine test file path from the plan
        test_path = self._infer_test_path(plan, issue_title)
        # Clean code fences if LLM added them
        test_code = self._strip_fences(test_code)

        await write_file(test_path, test_code)
        await save(f"mason: add tests for #{issue_num}")
        await comment(
            f"## Tests Written\n\n"
            f"File: `{test_path}`\n"
            f"```python\n{test_code[:2000]}\n```\n"
            f"{'(truncated)' if len(test_code) > 2000 else ''}\n\n"
            f"---\n*Mason — Step 3/7 (tests committed)*"
        )
        await status(f"Step 3 complete — tests committed ({test_path})")

        # ── STEP 4: Implementation ──
        await status("Step 4/7: Writing implementation")

        # Read files that need modification
        impl_context = ""
        for fp in self._extract_paths(plan):
            content = await read_file(fp)
            if content:
                impl_context += f"\n=== EXISTING: {fp} ===\n{content[:3000]}\n"

        impl_code = await ask_llm(
            f"Issue #{issue_num}: {issue_title}\n\n"
            f"Tests (must pass):\n```python\n{test_code[:3000]}\n```\n\n"
            f"Existing files:{impl_context}\n\n"
            f"Write the implementation to make these tests pass.\n"
            f"For EACH file, output:\n"
            f"=== FILE: path/to/file.py ===\n"
            f"(complete file content)\n"
            f"=== END ===\n\n"
            f"CRITICAL: For existing files, preserve ALL existing code. "
            f"Only add/modify what's needed."
        )

        files_written = await self._write_file_blocks(
            impl_code,
            ws_path,
            ex,
            tool_history,
            status,
        )
        if files_written > 0:
            await save(f"mason: implement #{issue_num} ({files_written} files)")
            await status(f"Step 4 complete — {files_written} files committed")
        else:
            await status("Step 4: no files generated")

        # ── STEP 5: Red/Green check ──
        await status("Step 5/7: Running tests (red/green)")
        test_result = ""
        if ex:
            r = await ex(
                "shell",
                {
                    "command": f"python -m pytest {test_path} -v --tb=short 2>&1 | tail -30",
                    "workspace": ws_path,
                },
            )
            test_result = str(r)[:2000]

        passed = '"passed": true' in test_result
        color = "GREEN" if passed else "RED"
        await comment(
            f"## Test Results: {color}\n\n```\n{test_result[:1500]}\n```\n\n---\n*Mason — Step 5/7*"
        )
        await status(f"Step 5 complete — tests {color}")

        # ── STEP 6: Edge cases ──
        await status("Step 6/7: Edge case tests")
        edge_code = await ask_llm(
            f"Issue #{issue_num}: {issue_title}\n\n"
            f"The main tests are in {test_path}. Now write ADDITIONAL "
            f"edge case tests. Cover:\n"
            f"- Empty/null inputs\n"
            f"- Boundary conditions\n"
            f"- Error cases\n"
            f"- Multi-tenant isolation (org_id scoping)\n\n"
            f"Output ONLY Python test code, no fences. "
            f"These will be APPENDED to the existing test file."
        )
        edge_code = self._strip_fences(edge_code)

        if edge_code.strip() and "def test_" in edge_code:
            # Append to existing test file
            existing_tests = await read_file(test_path)
            if existing_tests:
                combined = existing_tests.rstrip() + "\n\n\n" + edge_code
                await write_file(test_path, combined)
            else:
                await write_file(test_path, edge_code)
            await save(f"mason: edge case tests for #{issue_num}")
            await comment(
                f"## Edge Cases Added\n\n"
                f"```python\n{edge_code[:1500]}\n```\n\n"
                f"---\n*Mason — Step 6/7*"
            )
            await status("Step 6 complete — edge cases committed")
        else:
            await status("Step 6: no edge cases generated")

        # ── STEP 7: Summary ──
        await status("Step 7/7: Summary")
        await comment(
            f"## Mason Complete\n\n"
            f"- Architecture plan: posted\n"
            f"- Acceptance criteria: posted\n"
            f"- Tests: `{test_path}`\n"
            f"- Implementation: {files_written} files\n"
            f"- Test result: {color}\n"
            f"- Edge cases: {'added' if 'def test_' in edge_code else 'skipped'}\n\n"
            f"---\n*Mason — Done*"
        )
        await status("Pipeline complete")

        return ReasoningResult(
            response=(
                f"Mason completed issue #{issue_num}. "
                f"Tests: {color}. Files: {files_written}. "
                f"All steps documented on the issue."
            ),
            done=True,
            tool_history=tool_history,
        )

    @staticmethod
    def _strip_fences(code: str) -> str:
        """Remove markdown code fences if present."""
        lines = code.strip().split("\n")
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        return "\n".join(lines)

    @staticmethod
    def _infer_test_path(plan: str, title: str) -> str:
        """Infer a test file path from the plan or title."""
        import re

        # Look for test file mentions in the plan
        match = re.search(r"tests/\S+\.py", plan)
        if match:
            return match.group(0)
        # Generate from title
        slug = re.sub(r"[^a-z0-9]+", "_", title.lower()).strip("_")[:40]
        return f"tests/test_{slug}.py"

    @staticmethod
    def _extract_paths(text: str) -> list[str]:
        """Extract file paths from text."""
        import re

        paths = re.findall(r"src/stronghold/\S+\.py", text)
        return list(dict.fromkeys(paths))[:10]

    @staticmethod
    async def _write_file_blocks(
        content: str,
        ws_path: str,
        tool_executor: Any,
        tool_history: list[dict[str, Any]],
        status: StatusCallback,
    ) -> int:
        """Parse === FILE: path === blocks and write each file."""
        files_written = 0
        parts = content.split("=== FILE:")
        for part in parts[1:]:
            lines = part.strip().split("\n")
            if not lines:
                continue
            file_path = lines[0].strip().rstrip("=").strip()
            code_lines: list[str] = []
            in_code = False
            for line in lines[1:]:
                if line.strip() == "=== END ===" or (line.startswith("=== FILE:") and in_code):
                    break
                if line.strip().startswith("```") and not in_code:
                    in_code = True
                    continue
                if line.strip() == "```" and in_code:
                    break
                # If no fences, take all lines until END or next FILE
                if not in_code and not line.strip().startswith("```"):
                    in_code = True
                if in_code:
                    code_lines.append(line)

            if not code_lines or not file_path:
                continue

            file_content = "\n".join(code_lines).rstrip() + "\n"
            await status(f"  Writing {file_path}")
            await tool_executor(
                "file_ops",
                {
                    "action": "write",
                    "path": file_path,
                    "content": file_content,
                    "workspace": ws_path,
                },
            )
            tool_history.append(
                {
                    "tool_name": "file_ops",
                    "arguments": {"action": "write", "path": file_path},
                    "result": f"wrote {len(file_content)} bytes",
                }
            )
            files_written += 1
            await asyncio.sleep(0.1)

        return files_written


async def _heartbeat(status: StatusCallback) -> None:
    elapsed = 0
    while True:
        await asyncio.sleep(15)
        elapsed += 15
        await status(f"  LLM thinking... ({elapsed}s)")
