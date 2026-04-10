"""Analyze issue stage (Frank/Archie) — reads repo context, produces analysis."""

from __future__ import annotations

from typing import Any


async def run_analyze_issue(
    run: Any,
    *,
    workspace: Any,
    prompt_lib: Any,
    llm_extract: Any,
    fetch_prior_runs: Any,
    post_to_issue: Any,
    extract_files_from_body: Any,
    frank_model: str,
    feedback: str = "",
) -> Any:
    """Frank analyzes the issue. Runtime reads repo context, LLM produces analysis."""
    from stronghold.builders.extractors import extract_json
    from stronghold.builders.pipeline import StageResult

    owner, repo = run.repo.split("/")
    ws = getattr(run, "_workspace_path", "")
    issue_content = getattr(run, "_issue_content", "")
    issue_title = getattr(run, "_issue_title", "")

    file_listing = await workspace.list_files("src/", ws)
    test_listing = await workspace.list_files("tests/", ws)
    dashboard_listing = await workspace.list_files("src/stronghold/dashboard/", ws)
    architecture = await workspace.read_file("ARCHITECTURE.md", ws)
    architecture_excerpt = architecture[:3000] if architecture else "(not found)"

    run._file_listing = file_listing
    run._dashboard_listing = dashboard_listing

    prior_runs = await fetch_prior_runs(
        owner, repo, run.issue_number, exclude_run_id=run.run_id,
    )

    feedback_block = ""
    if feedback:
        feedback_block = f"Previous analysis rejected. Fix:\n{feedback}"

    if prior_runs:
        feedback_block += (
            f"\n\n## Prior Run History\n\n"
            f"This issue has been attempted {len(prior_runs)} time(s) before. "
            f"Learn from prior failures:\n\n"
        )
        for pr in prior_runs[-5:]:
            feedback_block += f"### {pr['run_id']}\n{pr['summary'][:500]}\n\n"

    template = await prompt_lib.get("builders.frank.analyze_issue")
    from stronghold.builders.pipeline.prompts import PromptLibrary
    prompt = PromptLibrary.render(
        template,
        issue_number=str(run.issue_number),
        issue_title=issue_title,
        issue_content=issue_content,
        file_listing=file_listing,
        dashboard_listing=dashboard_listing,
        test_listing=test_listing,
        architecture_excerpt=architecture_excerpt,
        feedback_block=feedback_block,
    )

    analysis = await llm_extract(prompt, frank_model, extract_json, "issue analysis")

    body_files = extract_files_from_body(issue_content)
    if body_files:
        llm_files = analysis.get("affected_files", []) or []
        merged: list[str] = list(body_files)
        for f in llm_files:
            if f and f not in merged:
                merged.append(f)
        analysis["affected_files"] = merged
        analysis["affected_files_source"] = "issue_body" if not llm_files else "issue_body+llm"
    else:
        analysis.setdefault("affected_files_source", "llm")

    summary = (
        f"## Issue Analysis\n\n"
        f"**Problem:** {analysis.get('problem', '')}\n\n"
        f"**Requirements:**\n"
        + "\n".join(f"- {r}" for r in analysis.get("requirements", []))
        + "\n\n**Edge Cases:**\n"
        + "\n".join(f"- {e}" for e in analysis.get("edge_cases", []))
        + f"\n\n**Affected Files** (source: {analysis.get('affected_files_source', 'llm')}):"
        f" {', '.join(analysis.get('affected_files', []))}\n\n"
        f"**Approach:** {analysis.get('approach', '')}\n"
    )

    await post_to_issue(owner, repo, run.issue_number, summary, run=run)

    return StageResult(
        success=True,
        summary=summary,
        evidence={"analysis": analysis},
        artifacts={"analysis": analysis},
    )
