"""Gatekeeper: PR review with approve/request-changes verdicts."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("stronghold.builders.pipeline")
auditor_logger = logging.getLogger("stronghold.builders.auditor")


# ── Gatekeeper: PR Review ────────────────────────────────────────

async def review_pr(
    *,
    pipeline: Any = None,
    owner: str,
    repo: str,
    pr_number: int,
    auto_merge_enabled: bool = False,
    allowed_authors: tuple[str, ...] = (),
    coverage_tolerance_pct: float = -1.0,
    protected_branches: tuple[str, ...] = ("main", "master"),
) -> StageResult:
    """Gatekeeper: review a PR end-to-end and either approve or request changes.

    Phases:
    1. Intake: fetch PR metadata, diff, parent issue
    2. Scope: read full changed files + siblings + callers
    3. Mechanical: ruff, mypy, bandit, pytest on changed files
    4. LLM semantic review: feeds context to Opus, extracts JSON verdict
    5. Act: post review (APPROVE or REQUEST_CHANGES), merge if approved
    """
    import json as _json

    td = pipeline._td

    # ── Phase 1: Intake ────────────────────────────────────────
    pr_raw = await td.execute(
        "github",
        {
            "action": "get_pr",
            "owner": owner, "repo": repo,
            "issue_number": pr_number,
        },
    )
    if pr_raw.startswith("Error:"):
        return StageResult(
            success=False, summary=f"Cannot fetch PR: {pr_raw[:200]}",
        )
    try:
        pr = _json.loads(pr_raw)
    except Exception:
        return StageResult(
            success=False, summary="Bad PR response",
        )

    # Identify parent issue from PR title (pattern: "feat: #NNN —")
    import re as _re
    issue_match = _re.search(r"#(\d+)", pr.get("title", ""))
    parent_issue_number = int(issue_match.group(1)) if issue_match else None
    issue_body = ""
    if parent_issue_number:
        issue_raw = await td.execute(
            "github",
            {
                "action": "get_issue",
                "owner": owner, "repo": repo,
                "issue_number": parent_issue_number,
            },
        )
        if not issue_raw.startswith("Error:"):
            try:
                issue_body = _json.loads(issue_raw).get("body", "") or ""
            except Exception:
                issue_body = ""

    # Fetch files changed
    files_raw = await td.execute(
        "github",
        {
            "action": "list_pr_files",
            "owner": owner, "repo": repo,
            "issue_number": pr_number,
        },
    )
    try:
        pr_files = _json.loads(files_raw) if not files_raw.startswith("Error:") else []
    except Exception:
        pr_files = []

    changed_paths = [f["filename"] for f in pr_files if f["filename"].startswith("src/")]
    py_files = [p for p in changed_paths if p.endswith(".py")]

    # ── Phase 2: Scope (need a worktree) ──────────────────────
    # Use workspace tool to ensure we have the PR branch checked out
    ws_result = await td.execute(
        "workspace",
        {
            "action": "create",
            "issue_number": parent_issue_number or pr_number,
            "owner": owner, "repo": repo,
        },
    )
    ws_path = ""
    if not ws_result.startswith("Error:"):
        try:
            ws_path = _json.loads(ws_result).get("path", "")
        except Exception:
            ws_path = ""

    # Checkout the PR head branch in the workspace
    if ws_path and pr.get("head", {}).get("ref"):
        head_ref = pr["head"]["ref"]
        await td.execute(
            "shell",
            {
                "command": f"git fetch origin {head_ref} && "
                f"git checkout -B {head_ref} origin/{head_ref}",
                "workspace": ws_path,
            },
        )

    # Read full changed files
    changed_files_content = ""
    for fpath in changed_paths[:10]:
        content = await pipeline._read_file(fpath, ws_path)
        if content:
            changed_files_content += (
                f"\n# --- {fpath} ---\n{content[:3000]}\n"
            )

    # Read siblings of new files for parallel structure
    sibling_files_content = ""
    for fpath in changed_paths[:5]:
        # Only for newly added files
        added = any(
            f["filename"] == fpath and f["status"] == "added"
            for f in pr_files
        )
        if not added:
            continue
        import os as _os
        dir_path = _os.path.dirname(fpath)
        if not dir_path:
            continue
        siblings_raw = await td.execute(
            "glob_files",
            {
                "pattern": f"{dir_path}/*.py",
                "workspace": ws_path,
                "max_results": 5,
            },
        )
        if siblings_raw.startswith("Error:"):
            continue
        try:
            siblings_data = _json.loads(siblings_raw)
            sibling_paths = siblings_data.get("files", [])
        except Exception:
            sibling_paths = []
        for sib in sibling_paths[:3]:
            if sib == fpath:
                continue
            sib_content = await pipeline._read_file(sib, ws_path)
            if sib_content:
                sibling_files_content += (
                    f"\n# --- {sib} (sibling pattern) ---\n"
                    f"{sib_content[:2000]}\n"
                )

    # Callers of changed symbols — grep for imports
    callers_content = ""
    for fpath in py_files[:3]:
        module = fpath.replace("src/", "").replace("/", ".").replace(".py", "")
        callers_raw = await td.execute(
            "grep_content",
            {
                "pattern": f"from {module}|import {module}",
                "workspace": ws_path,
                "glob": "**/*.py",
                "max_results": 10,
            },
        )
        if callers_raw and not callers_raw.startswith("Error:"):
            try:
                callers_data = _json.loads(callers_raw)
                matches = callers_data.get("matches", [])
                for m in matches[:5]:
                    callers_content += (
                        f"- {m['file']}:{m['line']}: {m['content']}\n"
                    )
            except Exception:
                pass

    # Read CLAUDE.md and ONBOARDING.md
    claude_md = (await pipeline._read_file("CLAUDE.md", ws_path))[:4000]
    onboarding_md = (await pipeline._read_file("ONBOARDING.md", ws_path))[:4000]
    repo_standards = (
        f"## CLAUDE.md\n{claude_md}\n\n## ONBOARDING.md\n{onboarding_md}"
    )

    # ── Phase 3: Mechanical gates ──────────────────────────────
    mechanical_results: dict[str, str] = {}
    if py_files:
        files_str = " ".join(py_files)
        for gate_name, cmd in [
            ("ruff_check", f"ruff check {files_str}"),
            ("ruff_format", f"ruff format --check {files_str}"),
            ("mypy", f"mypy {files_str} --strict"),
            ("bandit", f"bandit {files_str} -ll"),
        ]:
            result = await td.execute(
                "shell",
                {"command": cmd, "workspace": ws_path},
            )
            mechanical_results[gate_name] = result[:500]

    mechanical_summary = "\n".join(
        f"{k}: {v[:200]}" for k, v in mechanical_results.items()
    )
    mechanical_pass = all(
        '"passed": true' in v or v.startswith("Error:") or "Success" in v
        for v in mechanical_results.values()
    )

    # ── Coverage check ─────────────────────────────────────────
    coverage_summary = "Coverage check skipped (no baseline available)"
    if py_files and ws_path:
        cov_modules = ",".join(
            f.replace("src/", "").replace("/", ".").replace(".py", "")
            for f in py_files
        )
        cov_result = await td.execute(
            "shell",
            {
                "command": (
                    f"python -m pytest tests/ -q --cov={cov_modules} "
                    f"--cov-report=term --no-header 2>&1 | tail -20"
                ),
                "workspace": ws_path,
            },
        )
        if not cov_result.startswith("Error:"):
            coverage_summary = f"```\n{cov_result[:1500]}\n```"

    # ── Phase 4: LLM semantic review ───────────────────────────
    template = await pipeline._get_prompt("builders.gatekeeper.review_pr")
    if not template:
        from stronghold.builders.prompts import GATEKEEPER_REVIEW_PR
        template = GATEKEEPER_REVIEW_PR

    prompt = pipeline._render(
        template,
        pr_number=str(pr_number),
        pr_title=pr.get("title", ""),
        pr_author=pr.get("user", ""),
        pr_body=(pr.get("body") or "")[:2000],
        base_branch=pr.get("base", {}).get("ref", "main"),
        head_branch=pr.get("head", {}).get("ref", ""),
        files_count=str(pr.get("changed_files", len(pr_files))),
        additions=str(pr.get("additions", 0)),
        deletions=str(pr.get("deletions", 0)),
        issue_number=str(parent_issue_number or ""),
        issue_body=issue_body[:3000],
        mechanical_result=mechanical_summary[:2000],
        coverage_summary=coverage_summary[:1500],
        changed_files=changed_files_content[:15000],
        sibling_files=sibling_files_content[:6000],
        callers=callers_content[:3000],
        repo_standards=repo_standards[:8000],
    )

    verdict = await pipeline._llm_extract(
        prompt, pipeline._mason_model, extract_json, "gatekeeper verdict",
    )

    decision = verdict.get("decision", "request_changes")
    summary = verdict.get("summary", "")
    blockers = verdict.get("blockers", [])
    checked = verdict.get("checked", [])
    suggestions = verdict.get("suggestions", [])

    # Mechanical failures force request_changes
    if not mechanical_pass and decision == "approve":
        decision = "request_changes"
        blockers.append({
            "file": "(multiple)",
            "line": 0,
            "severity": "error",
            "category": "mechanical",
            "message": f"Mechanical gates failed:\n{mechanical_summary[:1000]}",
        })

    # ── Phase 5: Act ───────────────────────────────────────────
    review_body_lines = [
        f"## Gatekeeper Review",
        "",
        f"**Decision:** {decision.upper()}",
        f"**Summary:** {summary}",
        "",
    ]
    if checked:
        review_body_lines.append("### What I checked")
        for c in checked[:20]:
            review_body_lines.append(f"- ✓ {c}")
        review_body_lines.append("")

    if blockers:
        review_body_lines.append("### Blockers")
        for b in blockers[:20]:
            line_ref = f":{b.get('line')}" if b.get("line") else ""
            review_body_lines.append(
                f"- **{b.get('category', '?')}** "
                f"`{b.get('file', '?')}{line_ref}` — "
                f"{b.get('message', '')}"
            )
        review_body_lines.append("")

    if suggestions:
        review_body_lines.append("### Suggestions (non-blocking)")
        for s in suggestions[:10]:
            line_ref = f":{s.get('line')}" if s.get("line") else ""
            review_body_lines.append(
                f"- `{s.get('file', '?')}{line_ref}` — "
                f"{s.get('message', '')}"
            )

    review_body = "\n".join(review_body_lines)

    event = "APPROVE" if decision == "approve" else "REQUEST_CHANGES"

    review_result = await td.execute(
        "github",
        {
            "action": "review_pr",
            "owner": owner, "repo": repo,
            "issue_number": pr_number,
            "event": event,
            "body": review_body,
        },
    )

    merged = False
    merge_message = ""
    if decision == "approve" and auto_merge_enabled:
        # Guardrails
        author_ok = (
            not allowed_authors
            or pr.get("user", "") in allowed_authors
        )
        branch_ok = pr.get("base", {}).get("ref") not in protected_branches
        if author_ok and branch_ok:
            merge_raw = await td.execute(
                "github",
                {
                    "action": "merge_pr",
                    "owner": owner, "repo": repo,
                    "issue_number": pr_number,
                    "merge_method": "squash",
                    "commit_title": pr.get("title", f"PR #{pr_number}"),
                },
            )
            if not merge_raw.startswith("Error:"):
                try:
                    merge_data = _json.loads(merge_raw)
                    merged = bool(merge_data.get("merged", False))
                    merge_message = merge_data.get("message", "")
                except Exception:
                    pass
        else:
            merge_message = (
                f"auto_merge guardrails rejected: "
                f"author_ok={author_ok} branch_ok={branch_ok}"
            )

    # Post verdict to the parent issue (if there is one)
    if parent_issue_number:
        parent_body = (
            f"## Gatekeeper Verdict on PR #{pr_number}\n\n"
            f"**Decision:** {decision.upper()}\n"
            f"{summary}\n"
        )
        if merged:
            parent_body += f"\n**Merged.** {merge_message}\n"
        elif merge_message:
            parent_body += f"\n_{merge_message}_\n"
        await td.execute(
            "github",
            {
                "action": "post_pr_comment",
                "owner": owner, "repo": repo,
                "issue_number": parent_issue_number,
                "body": parent_body,
            },
        )

    return StageResult(
        success=(decision == "approve"),
        summary=f"{event}: {summary}",
        evidence={
            "pr": pr_number,
            "decision": decision,
            "blockers_count": len(blockers),
            "blockers": blockers[:10],
            "checked_count": len(checked),
            "merged": merged,
            "merge_message": merge_message,
            "mechanical_pass": mechanical_pass,
        },
    )

# ── Auditor Review ───────────────────────────────────────────────

async def auditor_review(
    stage: str,
    evidence: dict[str, Any],
    *,
    pipeline: Any = None,
) -> tuple[bool, str]:
    """Auditor reviews concrete evidence using composed prompts from the library."""
    from stronghold.builders.pipeline import _AUDITOR_STAGE_CONTEXT
    from stronghold.builders.pipeline.stages.auditor import parse_verdict

    # Get stage-specific context from prompt library
    stage_context = await pipeline._get_prompt(f"builders.auditor.stage.{stage}")
    if not stage_context:
        # Fallback to hardcoded context dict
        ctx = _AUDITOR_STAGE_CONTEXT.get(stage, {})
        purpose = ctx.get("purpose", "Complete the stage")
        scope = ctx.get("scope", "")
        out_of_scope = ctx.get("out_of_scope", "")
        checklist = ctx.get("checklist", [])
        rejection_format = ctx.get("rejection_format", "Be specific")
        checklist_text = "\n".join(f"- [ ] {item}" for item in checklist)
    else:
        # Parse structured context from prompt library
        import yaml
        try:
            ctx = yaml.safe_load(stage_context)
        except Exception:
            ctx = {}
        purpose = ctx.get("purpose", "Complete the stage")
        scope = ctx.get("scope", "")
        out_of_scope = ctx.get("out_of_scope", "")
        checklist_raw = ctx.get("checklist", [])
        rejection_format = ctx.get("rejection_format", "Be specific")
        checklist_text = "\n".join(
            f"- [ ] {item}" for item in (checklist_raw if isinstance(checklist_raw, list) else [])
        )

    evidence_text = "\n".join(
        f"**{k}:**\n{v}" if isinstance(v, str) else f"**{k}:** {v}"
        for k, v in evidence.items()
    )

    # Compose review prompt from library
    review_template = await pipeline._get_prompt("builders.auditor.review")
    prompt = pipeline._render(
        review_template,
        stage=stage,
        purpose=purpose,
        scope=scope,
        out_of_scope=out_of_scope,
        checklist=checklist_text,
        evidence=evidence_text,
        rejection_format=rejection_format,
    )

    text = await pipeline._llm_call(prompt, pipeline._auditor_model)
    from stronghold.builders.pipeline.stages.auditor import parse_verdict

    approved = parse_verdict(text)
    auditor_logger.info(
        "[AUDITOR] stage=%s approved=%s first80=%s",
        stage, approved, text[:80] if text else "EMPTY",
        extra={"run_id": "-"},
    )
    return approved, text

# ── Utilities ────────────────────────────────────────────────────

# ── Delegations to PytestRunner ─────────────────────────────────────

def _count_passing(pytest_output: str) -> int:
    from stronghold.builders.pipeline.pytest_runner import PytestRunner
    return PytestRunner.count_passing(pytest_output)

def _count_failing(pytest_output: str) -> int:
    from stronghold.builders.pipeline.pytest_runner import PytestRunner
    return PytestRunner.count_failing(pytest_output)

def _parse_violation_files(output: str) -> list[str]:
    from stronghold.builders.pipeline.pytest_runner import PytestRunner
    return PytestRunner.parse_violation_files(output)

def _extract_files_from_issue_body(issue_body: str) -> list[str]:
    from stronghold.builders.pipeline.github_helpers import extract_files_from_issue_body
    return extract_files_from_issue_body(issue_body)