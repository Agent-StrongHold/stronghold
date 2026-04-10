"""Runtime-controlled Builders pipeline.

The LLM generates content (code, analysis, criteria).
The runtime controls all execution: reads files, writes files, runs tests, commits.
The LLM never sees tool definitions.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

from stronghold.builders.extractors import (
    ExtractionError,
    extract_gherkin_scenarios,
    extract_json,
    extract_python_code,
)

logger = logging.getLogger("stronghold.builders.pipeline")
tdd_logger = logging.getLogger("stronghold.builders.tdd")
auditor_logger = logging.getLogger("stronghold.builders.auditor")
onboarding_logger = logging.getLogger("stronghold.builders.onboarding")

MAX_LLM_RETRIES = 3


# ── Prior-run signal patterns (module-level so tests can import the
#    source of truth instead of re-declaring local copies) ──────────

# `## Builders Run \`(run|sched)-<hex>\`` — header comment that Mason
# posts at the start of every run. The id prefix is `run-` for manual
# Re-export from extracted module for backward compat (tests import these)
from stronghold.builders.pipeline.github_helpers import (  # noqa: E402
    BUILDERS_RUN_PATTERN,
    GATEKEEPER_VERDICT_PATTERN,
)


# ── Issue type registry for context-aware onboarding ─────────────────


@dataclass
class IssueType:
    """Maps issue signals to onboarding sections. Extensible — just append."""

    name: str
    signals: list[str]       # path patterns, title prefixes, keywords
    sections: list[str]      # ONBOARDING.md section headers to inject
    priority: int = 0        # higher = matched first (most specific wins)


ISSUE_TYPE_REGISTRY: list[IssueType] = [
    IssueType(
        name="ui_dashboard",
        signals=["dashboard/", ".html", "sidebar", "button", "scroll", "css", "tailwind", "overlap", "animate", "active state", "tooltip", "diff view"],
        sections=[
            "Pattern 3: HTML/CSS Structural Tests (UI issues)",
            "Valid Import Paths",
            "Pytest Config",
        ],
        priority=8,
    ),
    IssueType(
        name="test_redis",
        signals=["cache/redis", "redis_pool"],
        sections=[
            "App Factory",
            "Pattern 2: Utility Class Tests (NO FastAPI, NO TestClient)",
            "Testing modules that connect to Redis",
            "Valid Import Paths",
            "Test-Only Issues vs Feature Issues",
        ],
        priority=10,
    ),
    IssueType(
        name="test_utility",
        signals=["cache/", "security/", "memory/", "tools/", "prompts/", "classifier/", "router/selector"],
        sections=[
            "App Factory",
            "Pattern 2: Utility Class Tests (NO FastAPI, NO TestClient)",
            "Valid Import Paths",
            "Test-Only Issues vs Feature Issues",
        ],
        priority=5,
    ),
    IssueType(
        name="test_route",
        signals=["api/routes/", "endpoint", "/v1/"],
        sections=[
            "App Factory",
            "Route Paths in Tests vs Production",
            "Pattern 1: Route Tests (FastAPI + TestClient)",
            "Valid Import Paths",
            "Test-Only Issues vs Feature Issues",
        ],
        priority=5,
    ),
    IssueType(
        name="feature_route",
        signals=["feat:", "fix:", "api/routes/"],
        sections=[
            "App Factory",
            "Route Paths in Tests vs Production",
            "Pattern 1: Route Tests (FastAPI + TestClient)",
            "Valid Import Paths",
            "Build Rules (from CLAUDE.md)",
        ],
        priority=1,
    ),
    IssueType(
        name="feature_general",
        signals=[],  # default fallback
        sections=[
            "App Factory",
            "Pattern 2: Utility Class Tests (NO FastAPI, NO TestClient)",
            "Valid Import Paths",
            "Build Rules (from CLAUDE.md)",
        ],
        priority=0,
    ),
]


# ── Auditor stage context ────────────────────────────────────────────
# Each stage gets: purpose, scope, out_of_scope, approval_checklist, rejection_format
# The Auditor prompt is built from these — it never invents its own criteria.

_AUDITOR_STAGE_CONTEXT: dict[str, dict[str, Any]] = {
    "issue_analyzed": {
        "purpose": "Understand the problem and plan the approach",
        "scope": "Problem statement, requirements list, edge cases, affected files, approach",
        "out_of_scope": (
            "Implementation details, code, fallback values, error handling specifics — "
            "those belong in acceptance_defined or later stages"
        ),
        "checklist": [
            "Problem statement is clear and matches the issue",
            "Requirements are listed and non-empty",
            "At least one edge case identified",
            "Affected files are plausible paths in the repo",
        ],
        "rejection_format": (
            "State WHICH checklist item failed, QUOTE the problematic text, "
            "and say WHAT it should say instead"
        ),
    },
    "acceptance_defined": {
        "purpose": "Define testable success criteria in Gherkin format",
        "scope": "Gherkin scenarios with Given/When/Then covering happy path, errors, edge cases",
        "out_of_scope": "Implementation approach, code, file paths — those belong in tests_written",
        "checklist": [
            "At least 3 Gherkin scenarios present",
            "Each scenario has Given, When, and Then steps",
            "Happy path is covered",
            "At least one error or edge case scenario",
            "Scenarios are concrete and testable (not vague)",
        ],
        "rejection_format": (
            "State WHICH scenario is wrong or missing, "
            "and provide the corrected Gherkin text"
        ),
    },
    "tests_written": {
        "purpose": "Create pytest test files that validate the acceptance criteria",
        "scope": "Test file exists, compiles without errors, tests map to criteria",
        "out_of_scope": (
            "Whether tests PASS — they SHOULD fail at this stage (TDD). "
            "Implementation code has not been written yet. "
            "AssertionError and 404 responses are EXPECTED and CORRECT — "
            "the endpoint being tested does not exist yet. "
            "Only SyntaxError and ImportError indicate real problems."
        ),
        "checklist": [
            "Test file was created (evidence shows file path)",
            "Pytest ran without SyntaxError or ImportError (AssertionError is OK — that is TDD)",
            "At least one test function exists (test count > 0)",
        ],
        "rejection_format": (
            "State WHICH error needs fixing with the EXACT error message. "
            "Do NOT reject for AssertionError or 404 — those are expected in TDD."
        ),
    },
    "implementation_started": {
        "purpose": "Write code that makes the failing tests pass",
        "scope": "Source files modified, test results improved",
        "out_of_scope": "Code style, naming — those are checked in quality gates stage",
        "checklist": [
            "At least one source file was modified (evidence shows file list)",
            "Test pass count improved vs before implementation",
            "Changes are committed to git",
        ],
        "rejection_format": "State WHICH test still fails and WHY, quoting the error output",
    },
    "implementation_ready": {
        "purpose": "Run quality gates and fix violations in new code",
        "scope": "ruff, mypy, bandit results on changed files",
        "out_of_scope": (
            "Pre-existing violations in files NOT touched by this issue. "
            "Pytest test failures — the TDD stage handles test pass/fail. "
            "Do NOT reject because pytest shows failing tests."
        ),
        "checklist": [
            "Quality gates ran (ruff_check, ruff_format, mypy, bandit)",
            "No NEW ruff/mypy/bandit violations in this issue's changed files",
        ],
        "rejection_format": (
            "State WHICH gate failed with the EXACT violation text, "
            "and whether it is new or pre-existing"
        ),
    },
    "quality_checks_passed": {
        "purpose": "Final verification — confirm commits and tests exist",
        "scope": "Git log, diff stat, final pytest run",
        "out_of_scope": (
            "Re-reviewing implementation decisions from earlier stages. "
            "Test pass/fail counts — the TDD stage already verified tests. "
            "Do NOT reject because some tests fail."
        ),
        "checklist": [
            "Git log shows at least one commit for this issue",
            "Diff shows changes to source and/or test files",
            "Pytest output is present (pytest was invoked, not empty)",
        ],
        "rejection_format": "State WHICH check failed, quoting the evidence",
    },
}


@dataclass
class StageResult:
    """Output of a pipeline stage."""

    success: bool
    summary: str
    evidence: dict[str, Any] = field(default_factory=dict)
    artifacts: dict[str, Any] = field(default_factory=dict)


class RuntimePipeline:
    """Deterministic stage executor. LLM generates content, runtime executes."""

    # Model rotation for outer loop — each pass tries the next model
    # Opus first (OpenRouter free tier), then Gemini (no spend cap).
    # NOTE: zhipu-glm-5 returns empty content (reasoning-only model) —
    # unusable as Mason until we handle reasoning_content field.
    MODEL_ROTATION = [
        "openrouter-anthropic/claude-opus-4.6",   # Best, OpenRouter free tier
        "google-gemini-3.1-pro",                   # No spend cap, reliable
        "mistral-large",                           # Fast fallback
    ]

    # Per-model success tracking: {model: {"attempts": N, "criteria_passed": N}}
    _model_stats: dict[str, dict[str, int]] = {}

    @classmethod
    def record_model_result(cls, model: str, criteria_passed: int) -> None:
        """Track how well a model performs for prompt iteration insights."""
        if model not in cls._model_stats:
            cls._model_stats[model] = {"attempts": 0, "criteria_passed": 0}
        cls._model_stats[model]["attempts"] += 1
        cls._model_stats[model]["criteria_passed"] += criteria_passed

    @classmethod
    def get_model_stats(cls) -> dict[str, dict[str, int]]:
        return dict(cls._model_stats)

    def __init__(
        self,
        llm: Any,
        tool_dispatcher: Any,
        prompt_manager: Any = None,
        frank_model: str = "google-gemini-3.1-pro",
        mason_model: str = "openrouter-anthropic/claude-opus-4.6",
        auditor_model: str = "google-gemini-3.1-pro",
    ) -> None:
        self._llm = llm
        self._td = tool_dispatcher
        self._pm = prompt_manager
        self._frank_model = frank_model
        self._mason_model = mason_model
        self._auditor_model = auditor_model

        # Delegate to extracted leaf modules (Phase 5)
        from stronghold.builders.pipeline.prompts import PromptLibrary
        from stronghold.builders.pipeline.pytest_runner import PytestRunner
        from stronghold.builders.pipeline.workspace import WorkspaceOps

        self._workspace = WorkspaceOps(tool_dispatcher)
        self._pytest_runner = PytestRunner(tool_dispatcher)
        self._prompt_lib = PromptLibrary(prompt_manager)

    # ── Helpers ──────────────────────────────────────────────────────

    async def load_onboarding(self, workspace: str) -> str:
        """Read ONBOARDING.md from workspace or bundled locations. Cache on first call."""
        if hasattr(self, "_onboarding_cache"):
            return self._onboarding_cache

        # Try workspace first (repo has its own onboarding)
        content = await self._read_file("ONBOARDING.md", workspace)

        # Fallback: bundled in Docker image at /app/
        if not content:
            from pathlib import Path
            for candidate in [
                Path("/app/ONBOARDING.md"),
                Path(__file__).resolve().parents[3] / "ONBOARDING.md",  # repo root
            ]:
                if candidate.exists():
                    content = candidate.read_text(encoding="utf-8", errors="ignore")
                    break

        if not content:
            content = "(No ONBOARDING.md found — proceeding without codebase context)"

        self._onboarding_cache = content
        return content

    @staticmethod
    def _detect_issue_type(run: Any) -> IssueType:
        from stronghold.builders.pipeline.context import OnboardingContext
        return OnboardingContext.detect_issue_type(run)

    @staticmethod
    def _parse_onboarding_sections(text: str) -> dict[str, str]:
        from stronghold.builders.pipeline.context import OnboardingContext
        return OnboardingContext.parse_sections(text)

    def _prepend_onboarding(self, prompt: str, run: Any) -> str:
        """Inject ONLY the relevant onboarding sections based on issue type."""
        onboarding = getattr(run, "_onboarding", "")
        if not onboarding:
            return prompt

        sections = self._parse_onboarding_sections(onboarding)
        issue_type = self._detect_issue_type(run)

        # Build focused context from matching sections
        parts: list[str] = []
        for section_name in issue_type.sections:
            for key, content in sections.items():
                if key.startswith(section_name) or section_name in key:
                    parts.append(content)
                    break

        if not parts:
            # Fallback: use full doc if no sections matched
            return f"## Codebase Context\n\n{onboarding}\n\n---\n\n{prompt}"

        context = "\n\n---\n\n".join(parts)
        onboarding_logger.info(
            "[ONBOARDING] issue_type=%s injecting %d sections (%d chars vs %d full)",
            issue_type.name, len(parts), len(context), len(onboarding),
            extra={"run_id": getattr(run, "run_id", "-")},
        )
        return f"## Codebase Context\n\n{context}\n\n---\n\n{prompt}"

    async def _get_prompt(self, name: str) -> str:
        return await self._prompt_lib.get(name)

    async def _compose_prompt(self, *fragment_names: str) -> str:
        return await self._prompt_lib.compose(*fragment_names)

    @staticmethod
    def _render(template: str, **kwargs: str) -> str:
        from stronghold.builders.pipeline.prompts import PromptLibrary
        return PromptLibrary.render(template, **kwargs)

    async def seed_prompts(self) -> None:
        """Seed default builder prompts into the prompt library."""
        if not self._pm:
            return
        from stronghold.builders.prompts import BUILDER_PROMPT_DEFAULTS
        for name, content in BUILDER_PROMPT_DEFAULTS.items():
            try:
                await self._pm.upsert(name, content, label="production")
            except Exception:
                pass

    async def _llm_call(
        self,
        prompt: str,
        model: str,
        *,
        ctx: Any | None = None,
        trace: Any | None = None,
    ) -> str:
        """Single LLM call. No tools. Returns text content.

        When ``trace`` is provided, wraps the call in a ``llm.complete`` span
        with model/prompt attributes for Phoenix observability.
        """
        if trace is not None and ctx is not None:
            with trace.span("llm.complete") as span:
                span.set_attributes(ctx.to_span_attrs() | {
                    "model_name": model,
                    "model_fallback_chain": list(self.MODEL_ROTATION),
                    "prompt_size_chars": len(prompt),
                })
                span.set_input(prompt[:4000])
                response = await self._llm.complete(
                    [{"role": "user", "content": prompt}],
                    model,
                    fallback_models=self.MODEL_ROTATION,
                )
                choices = response.get("choices", [])
                text = (choices[0].get("message", {}).get("content", "") or "") if choices else ""
                usage = response.get("usage", {}) or {}
                span.set_output(text[:4000])
                span.set_usage(
                    input_tokens=usage.get("prompt_tokens", 0),
                    output_tokens=usage.get("completion_tokens", 0),
                    model=model,
                )
                return text

        response = await self._llm.complete(
            [{"role": "user", "content": prompt}],
            model,
            fallback_models=self.MODEL_ROTATION,
        )
        choices = response.get("choices", [])
        if not choices:
            return ""
        return choices[0].get("message", {}).get("content", "") or ""

    async def _llm_extract(
        self,
        prompt: str,
        model: str,
        extractor: Any,
        what: str,
        *,
        ctx: Any | None = None,
        trace: Any | None = None,
    ) -> Any:
        """Call LLM, extract structured output, retry on parse failure."""
        last_error = ""
        for attempt in range(MAX_LLM_RETRIES):
            full_prompt = prompt
            if last_error:
                full_prompt = (
                    f"Your previous response could not be parsed: {last_error}\n\n"
                    f"Try again. Follow the format instructions exactly.\n\n"
                    f"{prompt}"
                )
            extract_ctx = ctx.with_(extraction_attempt=attempt + 1) if ctx else None
            text = await self._llm_call(full_prompt, model, ctx=extract_ctx, trace=trace)
            try:
                return extractor(text)
            except ExtractionError as e:
                last_error = str(e)
                logger.warning(
                    "Extraction failed for %s (attempt %d/%d): %s",
                    what, attempt + 1, MAX_LLM_RETRIES, e,
                )
        raise ExtractionError(
            f"Failed to extract {what} after {MAX_LLM_RETRIES} attempts: {last_error}"
        )

    # ── Delegations to extracted leaf modules ───────────────────────────

    async def _read_file(self, path: str, workspace: str) -> str:
        return await self._workspace.read_file(path, workspace)

    async def _write_file(self, path: str, content: str, workspace: str) -> str:
        return await self._workspace.write_file(path, content, workspace)

    async def _list_files(self, path: str, workspace: str) -> str:
        return await self._workspace.list_files(path, workspace)

    async def _run_pytest(self, workspace: str, path: str = "tests/") -> str:
        return await self._pytest_runner.run(workspace, path)

    async def _run_quality_gate(self, gate: str, workspace: str) -> str:
        """Run a quality gate tool. Returns output string."""
        return await self._td.execute(gate, {"workspace": workspace})

    async def _git_command(self, command: str, workspace: str) -> str:
        return await self._workspace.git_command(command, workspace)

    async def _fetch_prior_runs(
        self, owner: str, repo: str, issue_number: int,
        *, exclude_run_id: str = "",
    ) -> list[dict[str, str]]:
        from stronghold.builders.pipeline.github_helpers import fetch_prior_runs
        return await fetch_prior_runs(
            self._td, owner, repo, issue_number, exclude_run_id=exclude_run_id,
        )

    async def _post_to_issue(
        self, owner: str, repo: str, issue_number: int, body: str,
        *, run: Any = None,
    ) -> str:
        from stronghold.builders.pipeline.github_helpers import post_to_issue
        return await post_to_issue(self._td, owner, repo, issue_number, body, run=run)

    # ── Stage 1: Issue Analysis ──────────────────────────────────────

    async def analyze_issue(self, run: Any, feedback: str = "") -> StageResult:
        from stronghold.builders.pipeline.stages.analyze import run_analyze_issue
        from stronghold.builders.pipeline.github_helpers import (
            extract_files_from_issue_body,
            fetch_prior_runs,
        )
        return await run_analyze_issue(
            run,
            workspace=self._workspace,
            prompt_lib=self._prompt_lib,
            llm_extract=self._llm_extract,
            fetch_prior_runs=lambda o, r, i, **kw: fetch_prior_runs(self._td, o, r, i, **kw),
            post_to_issue=self._post_to_issue,
            extract_files_from_body=extract_files_from_issue_body,
            frank_model=self._frank_model,
            feedback=feedback,
        )

    # ── Stage 2: Acceptance Criteria ─────────────────────────────────

    async def define_acceptance_criteria(self, run: Any, feedback: str = "") -> StageResult:
        from stronghold.builders.pipeline.stages.acceptance import run_define_acceptance
        return await run_define_acceptance(
            run,
            prompt_lib=self._prompt_lib,
            llm_extract=self._llm_extract,
            detect_issue_type=self._detect_issue_type,
            post_to_issue=self._post_to_issue,
            frank_model=self._frank_model,
            feedback=feedback,
        )

    # ── Stage 3+4: One-at-a-time TDD ───────────────────────────────

    async def write_tests(self, run: Any, feedback: str = "") -> StageResult:
        """Redirect to combined TDD method."""
        return await self.write_tests_and_implement(run, feedback=feedback)

    async def implement(self, run: Any, feedback: str = "") -> StageResult:
        """Implementation is done inside write_tests_and_implement. Auto-pass."""
        return StageResult(
            success=True,
            summary="Implementation completed in tests_written stage (one-at-a-time TDD)",
            evidence={"note": "Combined with write_tests stage"},
        )

    async def write_tests_and_implement(self, run: Any, feedback: str = "") -> StageResult:
        from stronghold.builders.pipeline.stages.mason_tdd import run_mason_tdd
        return await run_mason_tdd(run, pipeline=self, feedback=feedback)

    # ── Stage 5: Quality Gates ───────────────────────────────────────

    async def run_quality_gates(self, run: Any, feedback: str = "") -> StageResult:
        from stronghold.builders.pipeline.stages.quality import run_quality_gates
        return await run_quality_gates(run, pipeline=self, feedback=feedback)

    # ── Stage 6: Final Verification ──────────────────────────────────

    async def final_verification(self, run: Any, feedback: str = "") -> StageResult:
        from stronghold.builders.pipeline.stages.final_verification import run_final_verification
        return await run_final_verification(
            run,
            pytest_runner=self._pytest_runner,
            workspace=self._workspace,
            post_to_issue=self._post_to_issue,
            feedback=feedback,
        )

    # ── UI Pipeline Methods (Piper + Glazier) ─────────────────────

    async def analyze_ui(self, run: Any, feedback: str = "") -> StageResult:
        """Piper: analyze HTML file and classify rendering model."""
        owner, repo = run.repo.split("/")
        ws = getattr(run, "_workspace_path", "")
        issue_content = getattr(run, "_issue_content", "")
        issue_title = getattr(run, "_issue_title", "")

        # List dashboard files
        dashboard_listing = await self._list_files(
            "src/stronghold/dashboard", ws,
        )

        # Detect affected file
        template = await self._get_prompt("builders.piper.analyze_ui")
        if not template:
            from stronghold.builders.ui_prompts import PIPER_ANALYZE_UI
            template = PIPER_ANALYZE_UI

        # Read the likely target file
        source_context = ""
        for fname in ["index.html", "agents.html", "quota.html",
                       "prompts.html", "login.html", "profile.html"]:
            if fname.replace(".html", "") in issue_content.lower():
                content = await self._read_file(
                    f"src/stronghold/dashboard/{fname}", ws,
                )
                if content:
                    source_context = (
                        f"# --- src/stronghold/dashboard/{fname}"
                        f" ---\n{content}\n"
                    )
                    break

        if not source_context:
            # Fallback: ask LLM to pick the file
            pick_prompt = (
                f"Which dashboard file for: {issue_title}\n"
                f"Files:\n{dashboard_listing}\n"
                f"Output ONLY the filename."
            )
            fname = await self._llm_call(
                pick_prompt, self._frank_model,
            )
            fname = fname.strip().strip("`").strip()
            content = await self._read_file(
                f"src/stronghold/dashboard/{fname}", ws,
            )
            if content:
                source_context = (
                    f"# --- src/stronghold/dashboard/{fname}"
                    f" ---\n{content}\n"
                )

        # Read prior run history from issue comments
        prior_runs = await self._fetch_prior_runs(
            owner, repo, run.issue_number, exclude_run_id=run.run_id,
        )
        prior_history = ""
        if prior_runs:
            prior_history = (
                f"\n\n## Prior Run History\n\n"
                f"This issue has been attempted {len(prior_runs)} time(s) before. "
                f"Learn from prior failures:\n\n"
            )
            for pr in prior_runs[-5:]:
                prior_history += f"### {pr['run_id']}\n{pr['summary'][:500]}\n\n"

        prompt = self._render(
            template,
            issue_number=str(run.issue_number),
            issue_title=issue_title,
            issue_content=issue_content + prior_history,
            source_context=source_context[:8000],
        )
        prompt = self._prepend_onboarding(prompt, run)

        analysis = await self._llm_extract(
            prompt, self._frank_model,
            extract_json, "UI analysis",
        )

        run._analysis = analysis
        run._rendering_model = analysis.get("rendering_model", "static")

        summary = (
            f"## UI Issue Analysis\n\n"
            f"**Rendering model:** {analysis.get('rendering_model')}\n"
            f"**Requirements:**\n"
            + "\n".join(
                f"- {r}" for r in analysis.get("requirements", [])
            )
        )
        await self._post_to_issue(owner, repo, run.issue_number, summary, run=run)

        return StageResult(
            success=True, summary=summary,
            evidence={"analysis": analysis},
        )

    async def define_ui_criteria(
        self, run: Any, feedback: str = "",
    ) -> StageResult:
        """Piper: write acceptance criteria for UI issue."""
        owner, repo = run.repo.split("/")
        analysis = getattr(run, "_analysis", {})
        rendering_model = getattr(run, "_rendering_model", "static")
        requirements = analysis.get("requirements", [])

        template = await self._get_prompt(
            "builders.piper.ui_acceptance_criteria",
        )
        if not template:
            from stronghold.builders.ui_prompts import (
                PIPER_UI_ACCEPTANCE_CRITERIA,
            )
            template = PIPER_UI_ACCEPTANCE_CRITERIA

        feedback_block = ""
        if feedback:
            feedback_block = (
                f"Previous criteria rejected. Fix:\n{feedback}"
            )

        prompt = self._render(
            template,
            issue_number=str(run.issue_number),
            issue_title=getattr(run, "_issue_title", ""),
            rendering_model=rendering_model,
            requirements="\n".join(f"- {r}" for r in requirements),
            feedback_block=feedback_block,
        )

        scenarios = await self._llm_extract(
            prompt, self._frank_model,
            extract_gherkin_scenarios, "UI Gherkin scenarios",
        )

        run._criteria = scenarios
        scenarios_text = "\n\n".join(scenarios)
        summary = (
            f"## UI Acceptance Criteria\n\n"
            f"**Rendering model:** {rendering_model}\n\n"
            f"```gherkin\n{scenarios_text}\n```\n"
        )
        await self._post_to_issue(owner, repo, run.issue_number, summary, run=run)

        return StageResult(
            success=True, summary=summary,
            evidence={"scenarios": scenarios},
        )

    async def write_ui_tests(
        self, run: Any, feedback: str = "",
    ) -> StageResult:
        """Glazier: write and implement UI tests (TDD)."""
        owner, repo = run.repo.split("/")
        ws = getattr(run, "_workspace_path", "")
        criteria = getattr(run, "_criteria", [])
        rendering_model = getattr(run, "_rendering_model", "static")
        analysis = getattr(run, "_analysis", {})
        issue_content = getattr(run, "_issue_content", "")
        affected_files = analysis.get("affected_files", [])

        if not criteria:
            return StageResult(
                success=False, summary="No acceptance criteria found",
            )

        # Find the target HTML file
        file_path = ""
        for fpath in affected_files:
            if fpath.endswith(".html"):
                file_path = fpath
                break
        if not file_path:
            # Detect from issue content
            for fname in [
                "index.html", "agents.html", "quota.html",
                "prompts.html", "login.html", "profile.html",
            ]:
                if fname.replace(".html", "") in issue_content.lower():
                    file_path = f"src/stronghold/dashboard/{fname}"
                    break
        if not file_path:
            file_path = "src/stronghold/dashboard/index.html"

        source_context = await self._read_file(file_path, ws)
        test_file = f"tests/api/test_issue_{run.issue_number}.py"
        files_written: list[str] = []
        criteria_completed = 0

        for i, criterion in enumerate(criteria):
            if i == 0:
                template = await self._get_prompt(
                    "builders.glazier.write_ui_test",
                )
                if not template:
                    from stronghold.builders.ui_prompts import (
                        GLAZIER_WRITE_UI_TEST,
                    )
                    template = GLAZIER_WRITE_UI_TEST
                raw_prompt = self._render(
                    template,
                    criterion=criterion,
                    file_path=file_path,
                    rendering_model=rendering_model,
                    source_context=source_context[:6000],
                    feedback_block=feedback or "",
                )
            else:
                existing_code = await self._read_file(test_file, ws)
                template = await self._get_prompt(
                    "builders.glazier.append_ui_test",
                )
                if not template:
                    from stronghold.builders.ui_prompts import (
                        GLAZIER_APPEND_UI_TEST,
                    )
                    template = GLAZIER_APPEND_UI_TEST
                raw_prompt = self._render(
                    template,
                    criterion=criterion,
                    rendering_model=rendering_model,
                    existing_code=existing_code,
                    feedback_block="",
                )

            prompt = self._prepend_onboarding(raw_prompt, run)
            try:
                test_code = await self._llm_extract(
                    prompt, self._mason_model,
                    extract_python_code,
                    f"UI test for criterion {i + 1}",
                )
                await self._write_file(test_file, test_code, ws)
            except ExtractionError as e:
                logger.error("UI test gen failed c%d: %s", i + 1, e)
                continue

            # Try to make the test pass (implement)
            for impl_attempt in range(3):
                output = await self._run_pytest(ws, test_file)
                passing = self._count_passing(output)
                failing = self._count_failing(output)

                if failing == 0 and passing > 0:
                    break

                current_source = await self._read_file(file_path, ws)
                current_test = await self._read_file(test_file, ws)

                impl_template = await self._get_prompt(
                    "builders.glazier.implement_ui",
                )
                if not impl_template:
                    from stronghold.builders.ui_prompts import (
                        GLAZIER_IMPLEMENT_UI,
                    )
                    impl_template = GLAZIER_IMPLEMENT_UI

                impl_prompt = self._render(
                    impl_template,
                    test_code=current_test,
                    pytest_output=output[:2000],
                    file_path=file_path,
                    source_code=current_source[:8000],
                    rendering_model=rendering_model,
                    issue_content=issue_content[:500],
                    feedback_block="",
                )

                try:
                    new_html = await self._llm_extract(
                        impl_prompt, self._mason_model,
                        self._extract_html,
                        f"UI impl c{i + 1}a{impl_attempt + 1}",
                    )
                    await self._write_file(file_path, new_html, ws)
                    if file_path not in files_written:
                        files_written.append(file_path)
                except ExtractionError:
                    break

            # Count final state
            final_output = await self._run_pytest(ws, test_file)
            final_passing = self._count_passing(final_output)
            if final_passing > 0:
                criteria_completed += 1

        # Commit changes
        if files_written:
            await self._td.execute(
                "shell",
                {
                    "command": f"git add -A && git commit -m "
                    f"'glazier: UI fix for #{run.issue_number}'",
                    "workspace": ws,
                },
            )

        final_output = await self._run_pytest(ws, test_file)
        final_passing = self._count_passing(final_output)
        final_failing = self._count_failing(final_output)

        summary = (
            f"## UI TDD Complete\n\n"
            f"**Model:** `{self._mason_model}`\n"
            f"**Rendering model:** {rendering_model}\n"
            f"**Criteria completed:** {criteria_completed}"
            f"/{len(criteria)}\n"
            f"**Files modified:** "
            f"{', '.join(f'`{f}`' for f in files_written)}\n"
            f"**Tests:** {final_passing} passed, "
            f"{final_failing} failed\n"
        )
        await self._post_to_issue(
            owner, repo, run.issue_number, summary, run=run,
        )

        return StageResult(
            success=final_passing > 0,
            summary=summary,
            evidence={
                "test_file": test_file,
                "files_written": files_written,
                "criteria_completed": criteria_completed,
                "tests_passing": final_passing,
                "tests_failing": final_failing,
                "rendering_model": rendering_model,
            },
        )

    async def implement_ui(
        self, run: Any, feedback: str = "",
    ) -> StageResult:
        """Glazier: implementation done in write_ui_tests (combined TDD)."""
        return StageResult(
            success=True,
            summary="Implementation completed in ui_tests_written stage",
            evidence={"note": "Combined with write_ui_tests"},
        )

    async def verify_ui(
        self, run: Any, feedback: str = "",
    ) -> StageResult:
        """Glazier: final verification for UI changes."""
        owner, repo = run.repo.split("/")
        ws = getattr(run, "_workspace_path", "")

        test_file = f"tests/api/test_issue_{run.issue_number}.py"
        pytest_output = await self._run_pytest(ws, test_file)
        git_log = await self._td.execute(
            "shell", {"command": "git log --oneline -10", "workspace": ws},
        )
        git_diff = await self._td.execute(
            "shell",
            {"command": "git diff main --stat", "workspace": ws},
        )

        summary = (
            f"## UI Final Verification\n\n"
            f"**Pytest:**\n```\n{pytest_output[:1500]}\n```\n\n"
            f"**Git log:**\n```\n{git_log}\n```\n\n"
            f"**Changes:**\n```\n{git_diff}\n```\n"
        )
        await self._post_to_issue(owner, repo, run.issue_number, summary, run=run)

        return StageResult(
            success=True, summary=summary,
            evidence={
                "pytest_output": pytest_output[:3000],
                "git_log": git_log,
                "diff_stat": git_diff,
            },
        )

    @staticmethod
    def _extract_html(text: str) -> str:
        """Extract HTML from LLM response (code block or raw)."""
        # Try to extract from ```html ... ``` block
        import re
        match = re.search(
            r"```(?:html)?\s*\n(.*?)```", text, re.DOTALL,
        )
        if match:
            return match.group(1).strip()
        # If response starts with <!DOCTYPE or <html, use as-is
        stripped = text.strip()
        if stripped.startswith("<!") or stripped.startswith("<html"):
            return stripped
        raise ExtractionError("Could not extract HTML from response")


    @staticmethod
    def _extract_files_from_issue_body(issue_body: str) -> list[str]:
        from stronghold.builders.pipeline.github_helpers import extract_files_from_issue_body
        return extract_files_from_issue_body(issue_body)

    @staticmethod
    def _count_passing(pytest_output: str) -> int:
        from stronghold.builders.pipeline.pytest_runner import PytestRunner
        return PytestRunner.count_passing(pytest_output)

    @staticmethod
    def _count_failing(pytest_output: str) -> int:
        from stronghold.builders.pipeline.pytest_runner import PytestRunner
        return PytestRunner.count_failing(pytest_output)

    @staticmethod
    def _parse_violation_files(output: str) -> list[str]:
        from stronghold.builders.pipeline.pytest_runner import PytestRunner
        return PytestRunner.parse_violation_files(output)

    # ── Auditor review (used by _execute_one_stage in routes) ──────────

    async def auditor_review(self, stage: str, evidence: dict[str, Any]) -> tuple[bool, str]:
        from stronghold.builders.pipeline.stages.review_pr import auditor_review
        return await auditor_review(stage, evidence, pipeline=self)

    # ── Quartermaster: Issue Decomposition ────────────────────────────

    async def decompose_issue(
        self, run: Any, feedback: str = "",
        *, max_sub_issues: int = 25, parent_issue_number: int | None = None,
    ) -> Any:
        from stronghold.builders.pipeline.stages.decompose import decompose_issue
        return await decompose_issue(
            run, pipeline=self, feedback=feedback,
            max_sub_issues=max_sub_issues, parent_issue_number=parent_issue_number,
        )

    # ── Gatekeeper: PR Review ────────────────────────────────────────

    async def review_pr(self, *args: Any, **kwargs: Any) -> Any:
        from stronghold.builders.pipeline.stages.review_pr import review_pr
        return await review_pr(*args, pipeline=self, **kwargs)
