"""Quartermaster: issue decomposition into atomic work orders."""

from __future__ import annotations

import logging
import re
from typing import Any

from stronghold.builders.extractors import ExtractionError, extract_json

logger = logging.getLogger("stronghold.builders.pipeline")


# ── Quartermaster: Issue Decomposition ────────────────────────────

def _triage_issue(title: str, body: str) -> str:
    """Classify an issue into a decomposition strategy.

    Returns one of:
    - "atomic"          — single file, no decomposition needed
    - "enumerable:ruff" — work is enumerable from ruff output
    - "enumerable:mypy" — work is enumerable from mypy output
    - "agentic"         — needs LLM-driven planning
    """
    import re as _re

    text = f"{title}\n{body}".lower()

    # Enumerable: tool-driven cleanup
    if "ruff check" in text or "ruff errors" in text or "ruff lint" in text:
        return "enumerable:ruff"
    if "mypy --strict" in text or "mypy errors" in text or "type errors" in text:
        return "enumerable:mypy"

    # Atomic: single file mention with few criteria, no multi-file markers
    path_matches = _re.findall(r"src/stronghold/[\w/]+\.(?:py|html)", text)
    unique_paths = set(path_matches)
    criteria_count = body.count("- [ ]") + body.count("- [x]")

    # Strong multi-file signals — anything with these is NOT atomic
    multi_file_markers = (
        "files to create",
        "files to modify",
        "files to add",
        "## files",
        "new files",
        ".github/workflows/",
    )
    has_multi_file_marker = any(m in text for m in multi_file_markers)

    if (
        len(unique_paths) <= 1
        and criteria_count <= 3
        and not has_multi_file_marker
    ):
        return "atomic"

    # Otherwise, agentic LLM decomposition
    return "agentic"

async def _enumerable_ruff(
    run: Any, ws: str,
) -> list[dict[str, Any]]:
    """Run ruff and produce one step per file with errors.

    Writes ruff JSON to a temp file (shell tool truncates stdout at
    3000 chars; ruff output for many errors is much bigger). Then
    reads the file and parses.
    """
    import json as _json
    from collections import defaultdict

    # Write ruff JSON to a temp file in the worktree
    await pipeline._td.execute(
        "shell",
        {
            "command": (
                "ruff check src/stronghold/ "
                "--output-format=json --no-fix > .ruff_errors.json 2>&1 || true"
            ),
            "workspace": ws,
        },
    )

    stdout = await pipeline._read_file(".ruff_errors.json", ws)
    if not stdout:
        return []

    # Find the JSON array in stdout (ruff outputs an array of objects)
    try:
        json_start = stdout.find("[")
        json_end = stdout.rfind("]") + 1
        if json_start == -1 or json_end == 0:
            return []
        ruff_errors = _json.loads(stdout[json_start:json_end])
    except Exception:
        return []

    if not ruff_errors:
        return []

    # Group by file
    by_file: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for err in ruff_errors:
        fname = err.get("filename", "")
        if fname.startswith("/"):
            # Make path relative to workspace
            fname = fname.split("/src/stronghold/", 1)[-1]
            fname = "src/stronghold/" + fname
        by_file[fname].append(err)

    # Build steps — one per file
    steps = []
    for fname, errors in sorted(by_file.items()):
        rules = sorted({e.get("code", "?") for e in errors})
        error_lines = []
        for e in errors[:20]:
            code = e.get("code", "?")
            msg = e.get("message", "")
            loc = e.get("location", {})
            line = loc.get("row", 0)
            col = loc.get("column", 0)
            fix_avail = "✓" if e.get("fix") else " "
            error_lines.append(f"  {fix_avail} {code} {fname}:{line}:{col}  {msg}")
        if len(errors) > 20:
            error_lines.append(f"  ... and {len(errors) - 20} more")

        body = (
            f"## Description\n"
            f"Fix all ruff violations in `{fname}`.\n\n"
            f"## Errors ({len(errors)} total)\n"
            f"Rules: {', '.join(rules)}\n\n"
            f"```\n{chr(10).join(error_lines)}\n```\n\n"
            f"## Acceptance Criteria\n"
            f"- [ ] `ruff check {fname}` returns zero errors\n"
            f"- [ ] `ruff format --check {fname}` passes\n"
            f"- [ ] No functional changes (lint/format only)\n\n"
            f"## Implementation Notes\n"
            f"Run `ruff check --fix {fname}` and `ruff format {fname}` "
            f"first to handle auto-fixable items, then manually fix the rest.\n\n"
            f"## Files\n- {fname}"
        )
        steps.append({
            "title": (
                f"fix: ruff cleanup in "
                f"{fname.replace('src/stronghold/', '')}"
            ),
            "body": body,
            "depends_on": [],
            "file": fname,
        })

    return steps

async def _enumerable_mypy(
    run: Any, ws: str,
) -> list[dict[str, Any]]:
    """Run mypy and produce one step per file with errors."""
    from collections import defaultdict
    import re as _re

    await pipeline._td.execute(
        "shell",
        {
            "command": (
                "mypy src/stronghold/ --strict --no-error-summary "
                "> .mypy_errors.txt 2>&1 || true"
            ),
            "workspace": ws,
        },
    )

    stdout = await pipeline._read_file(".mypy_errors.txt", ws)
    if not stdout:
        return []

    # Parse mypy lines: path:line: error: message  [code]
    line_pat = _re.compile(
        r"^(src/stronghold/[^:]+):(\d+):(?:\d+:)?\s*(error|warning):\s*(.+?)(?:\s+\[([^\]]+)\])?$",
        _re.MULTILINE,
    )
    by_file: dict[str, list[dict[str, str]]] = defaultdict(list)
    for m in line_pat.finditer(stdout):
        fname, line, _sev, msg, code = m.groups()
        by_file[fname].append({
            "line": line,
            "message": msg.strip(),
            "code": code or "",
        })

    if not by_file:
        return []

    steps = []
    for fname, errors in sorted(by_file.items()):
        error_lines = "\n".join(
            f"  {e['line']}: {e['message']}"
            + (f"  [{e['code']}]" if e["code"] else "")
            for e in errors[:30]
        )
        if len(errors) > 30:
            error_lines += f"\n  ... and {len(errors) - 30} more"

        body = (
            f"## Description\n"
            f"Fix mypy --strict errors in `{fname}`.\n\n"
            f"## Errors ({len(errors)} total)\n"
            f"```\n{error_lines}\n```\n\n"
            f"## Acceptance Criteria\n"
            f"- [ ] `mypy {fname} --strict` passes with zero errors\n"
            f"- [ ] No type-ignore comments added unless absolutely necessary\n"
            f"- [ ] Existing behavior preserved\n\n"
            f"## Files\n- {fname}"
        )
        steps.append({
            "title": (
                f"fix: mypy strict in "
                f"{fname.replace('src/stronghold/', '')}"
            ),
            "body": body,
            "depends_on": [],
            "file": fname,
        })

    return steps

def _needs_further_decomposition(title: str, body: str) -> bool:
    """Heuristic: is this sub-issue still too broad for Mason to solve?

    Signals:
    - Mentions multiple distinct directories under src/stronghold/
    - Mentions "across repo", "whole repo", "all files"
    - Has more than 3 acceptance criteria touching different files
    - Title prefixed with "cleanup", "refactor all", "fix all"
    """
    import re as _re

    text = f"{title}\n{body}".lower()

    # Broad-scope keywords
    broad_keywords = [
        "across repo", "across the repo", "whole repo",
        "all files", "every file", "entire codebase",
    ]
    if any(kw in text for kw in broad_keywords):
        return True

    # Title prefixes indicating wide scope
    broad_prefixes = ("cleanup", "refactor all", "fix all", "migrate all")
    if any(title.lower().strip().startswith(p) for p in broad_prefixes):
        return True

    # Count distinct directories mentioned
    paths = _re.findall(r"src/stronghold/([\w]+(?:/[\w]+)*)", text)
    directories: set[str] = set()
    for p in paths:
        # Take first 2 path segments as "directory"
        parts = p.split("/")
        directories.add("/".join(parts[:2]))
    if len(directories) > 2:
        return True

    return False

async def decompose_issue(
    run: Any,
    *,
    pipeline: Any = None,
    feedback: str = "",
    max_sub_issues: int = 25,
    parent_issue_number: int | None = None,
    depth: int = 0,
    max_depth: int = 3,
) -> Any:
    """Quartermaster: decompose a parent issue into sub-issues with dependencies.

    If depth < max_depth, children that are still too broad will be
    recursively decomposed. Parent issues get an 'epic' label so the
    scheduler skips them and works the leaves instead.

    1. Read parent issue + repo context
    2. LLM produces JSON with steps + depends_on (local indices)
    3. For each step: create_issue, then create_sub_issue(parent, child)
    4. After all created: add_blocked_by edges per the depends_on map
    5. For each child still too broad: recurse (up to max_depth)
    6. Label parent as 'epic' so the scheduler skips it
    7. Post a summary comment on the parent issue
    """
    from stronghold.builders.pipeline import StageResult
    import json as _json

    owner, repo = run.repo.split("/")
    ws = getattr(run, "_workspace_path", "")
    issue_content = getattr(run, "_issue_content", "")
    issue_title = getattr(run, "_issue_title", "")

    # ── Triage: pick the right strategy ──
    strategy = pipeline._triage_issue(issue_title, issue_content)
    logger.info(
        "Quartermaster triage on #%s → %s",
        run.issue_number, strategy,
    )

    plan_summary = ""
    steps: list[dict[str, Any]] = []

    if strategy == "atomic":
        # No decomposition needed — leave the issue for Mason to work directly
        return StageResult(
            success=True,
            summary=(
                f"Triage: atomic — single-file work order, "
                f"no decomposition needed."
            ),
            evidence={
                "parent": run.issue_number,
                "strategy": "atomic",
                "depth": depth,
                "created": [],
            },
        )

    elif strategy == "enumerable:ruff":
        steps = await pipeline._enumerable_ruff(run, ws)
        plan_summary = (
            f"Enumerable ruff decomposition: {len(steps)} files with errors. "
            f"One sub-issue per file."
        )

    elif strategy == "enumerable:mypy":
        steps = await pipeline._enumerable_mypy(run, ws)
        plan_summary = (
            f"Enumerable mypy decomposition: {len(steps)} files with errors. "
            f"One sub-issue per file."
        )

    else:  # agentic
        file_listing = await pipeline._list_files("src/", ws)

        relevant_files = ""
        import re as _re
        mentioned_paths = _re.findall(
            r"(src/stronghold/[\w/]+\.py)", issue_content,
        )
        for path in mentioned_paths[:5]:
            content = await pipeline._read_file(path, ws)
            if content:
                relevant_files += f"\n# --- {path} ---\n{content[:2000]}\n"

        template = await pipeline._get_prompt("builders.quartermaster.decompose")
        if not template:
            from stronghold.builders.prompts import QUARTERMASTER_DECOMPOSE
            template = QUARTERMASTER_DECOMPOSE

        prompt = pipeline._render(
            template,
            issue_number=str(run.issue_number),
            issue_title=issue_title,
            issue_content=issue_content,
            file_listing=file_listing[:4000],
            relevant_files=relevant_files[:6000],
        )

        plan = await pipeline._llm_extract(
            prompt, pipeline._frank_model, extract_json, "decomposition plan",
        )
        steps = plan.get("steps", [])
        plan_summary = plan.get("summary", "")

    if not steps:
        return StageResult(
            success=False,
            summary=f"Triage: {strategy} produced no steps",
        )

    # Enumerable strategies are uncapped; agentic capped at 25.
    # The cap exists because LLM decompositions tend to either over-split
    # (50 trivial steps) or under-split (3 huge steps); the cap is a
    # heuristic ceiling that says "if you produced more than this, your
    # parent epic is genuinely too broad and a human should split it
    # first." 25 fits real-world v0.9 epics like 'populate priority_tier
    # in 15+ agent.yaml files'; the prior 10 was rejecting them as
    # 'too broad' when they were actually correctly enumerated.
    AGENTIC_CAP = 25
    if strategy == "agentic" and len(steps) > AGENTIC_CAP:
        return StageResult(
            success=False,
            summary=(
                f"Too many steps ({len(steps)} > {AGENTIC_CAP}) — "
                f"parent is too broad. Split it into narrower epics first."
            ),
        )

    # Hard safety cap to prevent runaway issue creation
    if len(steps) > 100:
        steps = steps[:100]
        plan_summary += f" (capped at 100 from larger set)"

    # Create all child issues first, recording step index → issue number
    created: list[dict[str, Any]] = []
    for i, step in enumerate(steps):
        title = step.get("title", f"sub-issue {i + 1}")
        body = step.get("body", "")
        body += f"\n\n---\n_Sub-issue of #{run.issue_number}, step {i + 1} of {len(steps)}_"

        result = await pipeline._td.execute(
            "github",
            {
                "action": "create_issue",
                "owner": owner, "repo": repo,
                "title": title, "body": body,
                "labels": ["builders", "quartermaster"],
            },
        )
        if result.startswith("Error:"):
            logger.error("Failed to create sub-issue %d: %s", i, result)
            return StageResult(
                success=False,
                summary=f"Failed to create sub-issue {i + 1}: {result[:200]}",
            )
        try:
            data = _json.loads(result)
        except Exception:
            return StageResult(
                success=False, summary=f"Bad create_issue response: {result[:200]}",
            )
        created.append({
            "index": i,
            "number": data["number"],
            "title": title,
            "depends_on": step.get("depends_on", []),
        })

    # Link each child as a sub-issue of the parent
    for c in created:
        await pipeline._td.execute(
            "github",
            {
                "action": "create_sub_issue",
                "owner": owner, "repo": repo,
                "issue_number": run.issue_number,
                "sub_issue_number": c["number"],
            },
        )

    # Add blocked_by edges per depends_on (local index → issue number)
    for c in created:
        for dep_idx in c["depends_on"]:
            if not isinstance(dep_idx, int) or dep_idx >= len(created):
                continue
            blocker = created[dep_idx]
            await pipeline._td.execute(
                "github",
                {
                    "action": "add_blocked_by",
                    "owner": owner, "repo": repo,
                    "issue_number": c["number"],
                    "blocker_issue_number": blocker["number"],
                },
            )

    # Recurse on children that are still too broad
    recursive_depth = depth + 1
    recurse_counts: list[dict[str, Any]] = []
    if recursive_depth <= max_depth:
        from types import SimpleNamespace

        for c in created:
            # Get the step body that was used to create this child
            step_body = ""
            for i, step in enumerate(steps):
                if i == c["index"]:
                    step_body = step.get("body", "")
                    break

            if not pipeline._needs_further_decomposition(c["title"], step_body):
                continue

            logger.info(
                "Quartermaster recursing on #%d (depth %d)",
                c["number"], recursive_depth,
            )
            child_run = SimpleNamespace(
                run_id=f"qm-{recursive_depth}-{c['number']}",
                issue_number=c["number"],
                repo=run.repo,
                _issue_title=c["title"],
                _issue_content=step_body,
                _workspace_path=ws,
            )
            child_result = await decompose_issue(
                child_run, depth=recursive_depth, max_depth=max_depth,
            )
            recurse_counts.append({
                "parent": c["number"],
                "success": child_result.success,
                "sub_created": (
                    child_result.evidence.get("created", [])
                    if child_result.success
                    else []
                ),
            })

    # Label this parent as 'epic' so the scheduler skips it
    await pipeline._td.execute(
        "github",
        {
            "action": "add_labels",
            "owner": owner, "repo": repo,
            "issue_number": run.issue_number,
            "labels": ["epic"],
        },
    )

    # Post summary comment to the parent
    lines = [
        f"## Quartermaster Decomposition (depth {depth}, strategy: {strategy})\n"
    ]
    lines.append(f"{plan_summary}\n")
    lines.append(f"**{len(created)} sub-issues created:**\n")
    for c in created:
        deps = c["depends_on"]
        dep_str = ""
        if deps:
            dep_numbers = [f"#{created[d]['number']}" for d in deps if d < len(created)]
            dep_str = f" _(blocked by {', '.join(dep_numbers)})_"
        # Mark recursed children
        recursed = any(r["parent"] == c["number"] for r in recurse_counts)
        marker = " 🔻 _(further decomposed)_" if recursed else ""
        lines.append(f"- #{c['number']} {c['title']}{dep_str}{marker}")

    if recurse_counts:
        total_leaves = sum(len(r["sub_created"]) for r in recurse_counts)
        lines.append(
            f"\n_Recursed on {len(recurse_counts)} children, "
            f"created {total_leaves} leaf sub-issues._"
        )

    summary_text = "\n".join(lines)

    await pipeline._td.execute(
        "github",
        {
            "action": "post_pr_comment",
            "owner": owner, "repo": repo,
            "issue_number": run.issue_number,
            "body": summary_text,
        },
    )

    return StageResult(
        success=True,
        summary=summary_text,
        evidence={
            "parent": run.issue_number,
            "depth": depth,
            "strategy": strategy,
            "created": [{"number": c["number"], "title": c["title"]} for c in created],
            "dependency_count": sum(len(c["depends_on"]) for c in created),
            "recursed": recurse_counts,
        },
    )
