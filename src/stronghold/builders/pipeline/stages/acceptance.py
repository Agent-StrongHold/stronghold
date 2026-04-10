"""Acceptance criteria stage (Frank/Archie) — writes Gherkin scenarios."""

from __future__ import annotations

from typing import Any


async def run_define_acceptance(
    run: Any,
    *,
    prompt_lib: Any,
    llm_extract: Any,
    detect_issue_type: Any,
    post_to_issue: Any,
    frank_model: str,
    feedback: str = "",
) -> Any:
    """Frank writes Gherkin acceptance criteria."""
    from stronghold.builders.extractors import extract_gherkin_scenarios
    from stronghold.builders.pipeline import StageResult
    from stronghold.builders.pipeline.prompts import PromptLibrary

    owner, repo = run.repo.split("/")
    issue_content = getattr(run, "_issue_content", "")
    issue_title = getattr(run, "_issue_title", "")

    analysis = {}
    for artifact in run.artifacts:
        if artifact.type == "issue_analyzed_output":
            analysis = getattr(run, "_analysis", {})
            break

    requirements = analysis.get("requirements", [issue_content])
    edge_cases = analysis.get("edge_cases", [])

    locked = getattr(run, "_locked_criteria", set())
    old_criteria = getattr(run, "_criteria", [])

    feedback_block = ""
    if feedback:
        feedback_block = f"Previous criteria rejected. Fix:\n{feedback}"

    issue_type = detect_issue_type(run)
    if issue_type.name == "ui_dashboard":
        feedback_block += (
            "\n\nTESTING CONSTRAINT: These criteria will be tested by "
            "reading the HTML file with Python and checking for string "
            "patterns. There is NO browser, NO JavaScript execution. "
            "Criteria MUST be statically verifiable:\n"
            "- GOOD: 'HTML contains a script that references "
            "window.location.pathname'\n"
            "- GOOD: 'HTML contains the class border-emerald-500'\n"
            "- BAD: 'Non-active items should NOT have active "
            "classes' (cannot test without a browser)\n"
            "- BAD: 'Click on nav item and verify it becomes "
            "active' (no browser available)\n"
        )

    if locked and old_criteria:
        locked_info = "\n".join(
            f"- Criterion {i + 1}: {'LOCKED (tests pass — do NOT change)' if i in locked else 'FAILED — must be rewritten'}: {c[:80]}"
            for i, c in enumerate(old_criteria)
        )
        feedback_block += (
            f"\n\nPREVIOUS ATTEMPT RESULTS:\n{locked_info}\n\n"
            f"Keep the locked criteria EXACTLY as they are. "
            f"Only rewrite the FAILED criteria. "
            f"Return ALL criteria (locked + rewritten) in order.\n"
        )

    template = await prompt_lib.get("builders.frank.acceptance_criteria")
    prompt = PromptLibrary.render(
        template,
        issue_number=str(run.issue_number),
        issue_title=issue_title,
        requirements="\n".join(f"- {r}" for r in requirements),
        edge_cases="\n".join(f"- {e}" for e in edge_cases),
        feedback_block=feedback_block,
    )

    scenarios = await llm_extract(
        prompt, frank_model, extract_gherkin_scenarios, "Gherkin scenarios",
    )

    scenarios_text = "\n\n".join(scenarios)
    summary = (
        f"## Acceptance Criteria\n\n"
        f"```gherkin\n{scenarios_text}\n```\n\n"
        f"**Total scenarios:** {len(scenarios)}\n"
    )

    await post_to_issue(owner, repo, run.issue_number, summary, run=run)

    run._criteria = scenarios
    run._analysis = analysis

    return StageResult(
        success=True,
        summary=summary,
        evidence={"scenario_count": len(scenarios), "scenarios": scenarios},
        artifacts={"criteria": scenarios},
    )
