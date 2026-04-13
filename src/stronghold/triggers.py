"""Core reactor triggers — registered at container startup.

Each trigger is a TriggerSpec + async action handler.
The reactor evaluates conditions at 1000Hz and dispatches matches.
"""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from stronghold.types.reactor import Event, TriggerMode, TriggerSpec

if TYPE_CHECKING:
    from stronghold.container import Container

logger = logging.getLogger("stronghold.triggers")

# Patterns for duplicate detection (Phase B)
_DUPLICATE_PATTERN = re.compile(r"(?:duplicate\s+of|same\s+as)\s+#\d+", re.IGNORECASE)

# Labels that route to Herald instead of builder pipeline (Phase C)
_HERALD_LABELS = {"idea", "feature-request", "enhancement"}

# Staleness threshold (Phase B)
_STALE_THRESHOLD_DAYS = 30


def register_core_triggers(container: Container) -> None:
    """Register all core triggers with the reactor."""
    reactor = container.reactor

    # 1. Learning promotion check (every 60s)
    async def _check_learning_promotions(event: Event) -> dict[str, Any]:
        if hasattr(container, "learning_promoter") and container.learning_promoter:
            promoted = await container.learning_promoter.check_and_promote()
            return {"promoted_count": len(promoted)}
        return {"skipped": True}

    reactor.register(
        TriggerSpec(
            name="learning_promotion_check",
            mode=TriggerMode.INTERVAL,
            interval_secs=60.0,
            jitter=0.1,
        ),
        _check_learning_promotions,
    )

    # 2. Rate limiter stale key eviction (every 5 minutes)
    # H22 fix: use public evict_stale_keys() method instead of private attrs
    async def _evict_stale_rate_keys(event: Event) -> dict[str, Any]:
        evicted = container.rate_limiter.evict_stale_keys()
        if evicted > 0:
            logger.debug("Evicted %d stale rate limit keys", evicted)
        return {"evicted": evicted}

    reactor.register(
        TriggerSpec(
            name="rate_limit_eviction",
            mode=TriggerMode.INTERVAL,
            interval_secs=300.0,
        ),
        _evict_stale_rate_keys,
    )

    # 3. Outcome stats snapshot (every 5 minutes)
    async def _snapshot_outcome_stats(event: Event) -> dict[str, Any]:
        stats = await container.outcome_store.get_task_completion_rate()
        logger.debug(
            "Outcome stats: %d total, %.1f%% success",
            stats.get("total", 0),
            stats.get("rate", 0) * 100,
        )
        return stats

    reactor.register(
        TriggerSpec(
            name="outcome_stats_snapshot",
            mode=TriggerMode.INTERVAL,
            interval_secs=300.0,
            jitter=0.2,
        ),
        _snapshot_outcome_stats,
    )

    # 4. Security rescan on flagged events
    async def _security_rescan(event: Event) -> dict[str, Any]:
        content = event.data.get("content", "")
        boundary = event.data.get("boundary", "tool_result")
        if content:
            verdict = await container.warden.scan(content, boundary)
            if not verdict.clean:
                logger.warning(
                    "Security rescan flagged content: %s",
                    verdict.flags,
                )
            return {"clean": verdict.clean, "flags": list(verdict.flags)}
        return {"skipped": True}

    reactor.register(
        TriggerSpec(
            name="security_rescan",
            mode=TriggerMode.EVENT,
            event_pattern=r"security\.rescan",
        ),
        _security_rescan,
    )

    # 5. Post-tool-loop event handler (emit learning extraction opportunity)
    async def _post_tool_learning(event: Event) -> dict[str, Any]:
        tool_name = event.data.get("tool_name", "")
        success = event.data.get("success", True)
        if not success and tool_name:
            logger.debug("Tool failure on %s — learning extraction opportunity", tool_name)
        return {"tool_name": tool_name, "success": success}

    reactor.register(
        TriggerSpec(
            name="post_tool_learning",
            mode=TriggerMode.EVENT,
            event_pattern=r"post_tool_loop",
        ),
        _post_tool_learning,
    )

    # 6. Tournament check (every 10 minutes — evaluate promotions)
    async def _tournament_check(event: Event) -> dict[str, Any]:
        if hasattr(container, "tournament") and container.tournament:
            stats: dict[str, Any] = container.tournament.get_stats()
            return stats
        return {"skipped": True}

    reactor.register(
        TriggerSpec(
            name="tournament_evaluation",
            mode=TriggerMode.INTERVAL,
            interval_secs=600.0,
            jitter=0.15,
        ),
        _tournament_check,
    )

    # 7. Canary deployment check (every 30 seconds)
    async def _canary_check(event: Event) -> dict[str, Any]:
        if hasattr(container, "canary_manager") and container.canary_manager:
            active = container.canary_manager.list_active()
            for deploy in active:
                result = container.canary_manager.check_promotion_or_rollback(
                    deploy["skill_name"],
                )
                if result in ("rollback", "advance", "complete"):
                    logger.info(
                        "Canary %s: %s → %s",
                        deploy["skill_name"],
                        deploy["stage"],
                        result,
                    )
            return {"active_canaries": len(active)}
        return {"skipped": True}

    reactor.register(
        TriggerSpec(
            name="canary_deployment_check",
            mode=TriggerMode.INTERVAL,
            interval_secs=30.0,
        ),
        _canary_check,
    )

    # 8. RLHF feedback loop — process PR review results into learnings
    async def _rlhf_feedback(event: Event) -> dict[str, Any]:
        """Extract learnings from an Auditor review and store in Mason's memory."""
        from stronghold.agents.feedback.extractor import ReviewFeedbackExtractor
        from stronghold.agents.feedback.loop import FeedbackLoop
        from stronghold.agents.feedback.tracker import InMemoryViolationTracker

        review_result = event.data.get("review_result")
        if not review_result:
            return {"skipped": True}

        # Lazily initialize the feedback loop components
        if not hasattr(container, "_feedback_loop"):
            container._feedback_loop = FeedbackLoop(  # type: ignore[attr-defined]
                extractor=ReviewFeedbackExtractor(),
                learning_store=container.learning_store,
                violation_store=InMemoryViolationTracker(),
            )
        stored = await container._feedback_loop.process_review(review_result)  # type: ignore[attr-defined]
        return {"stored_learnings": stored}

    reactor.register(
        TriggerSpec(
            name="rlhf_feedback",
            mode=TriggerMode.EVENT,
            event_pattern=r"pr\.reviewed",
        ),
        _rlhf_feedback,
    )

    # ── Phase D helper: best-effort label management ─────────────────
    async def _label_issue(
        token: str,
        repo: str,
        issue_number: int,
        add: list[str] | None = None,
        remove: list[str] | None = None,
    ) -> None:
        """Add/remove labels on an issue. Best-effort: never raises."""
        import httpx  # noqa: PLC0415

        base_url = f"https://api.github.com/repos/{repo}/issues/{issue_number}/labels"
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
        }
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                if add:
                    await client.post(base_url, headers=headers, json={"labels": add})
                for label in remove or []:
                    await client.delete(f"{base_url}/{label}", headers=headers)
        except Exception:
            pass  # Best-effort: labeling failures must not crash the pipeline

    # 9. Issue backlog scanner — pick up work through the full pipeline
    async def _scan_issue_backlog(event: Event) -> dict[str, Any]:
        """Scan GitHub for open `builders` issues and dispatch through the
        full pipeline: Gatekeeper triage → Quartermaster → Archie → Mason
        → Auditor → Gatekeeper cleanup.

        Runs every 5 minutes. Picks up issues labeled `builders` that are
        not already `in-progress` or `blocked`. Respects concurrency limit.
        """
        # Try GitHub App token first, fall back to GITHUB_TOKEN env var
        token = ""
        try:
            from stronghold.tools.github import _get_app_installation_token  # noqa: PLC0415

            token = _get_app_installation_token("gatekeeper")
        except ImportError:
            pass
        if not token:
            import os  # noqa: PLC0415

            token = os.environ.get("GITHUB_TOKEN", "")
        if not token:
            return {"skipped": True, "reason": "no github token"}

        try:
            import httpx  # noqa: PLC0415

            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.get(
                    "https://api.github.com/repos/Agent-StrongHold/stronghold/issues",
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Accept": "application/vnd.github+json",
                    },
                    params={
                        "labels": "builders",
                        "state": "open",
                        "per_page": "10",
                        "sort": "created",
                        "direction": "asc",
                    },
                )
                if resp.status_code != 200:
                    return {"error": f"GitHub API returned {resp.status_code}"}

                issues = resp.json()
        except Exception as e:
            logger.warning("Issue backlog scan failed: %s", e)
            return {"error": str(e)}

        if not issues:
            return {"scanned": 0, "dispatched": 0}

        # Filter out issues already in progress or blocked
        skip_labels = {"in-progress", "blocked", "wontfix", "duplicate"}
        actionable = [
            issue
            for issue in issues
            if not skip_labels.intersection(label["name"] for label in issue.get("labels", []))
            and not issue.get("pull_request")  # skip PRs
        ]

        if not actionable:
            return {"scanned": len(issues), "dispatched": 0}

        # Check concurrency — don't overload the pipeline
        max_concurrent = 3
        queue = getattr(container, "mason_queue", None)
        if queue is not None:
            in_progress = len([r for r in queue.list_all() if r.get("status") == "in_progress"])
            slots = max(0, max_concurrent - in_progress)
            actionable = actionable[:slots]
        else:
            actionable = actionable[:max_concurrent]

        if not actionable:
            return {"scanned": len(issues), "dispatched": 0, "reason": "at concurrency limit"}

        dispatched = 0
        flagged = 0
        repo = "Agent-StrongHold/stronghold"
        for issue in actionable:
            issue_number = issue["number"]
            title = issue["title"]
            body = issue.get("body", "") or ""
            issue_labels = {label["name"] for label in issue.get("labels", [])}

            # ── Phase B: Obsolescence detection ──
            created_at_str = issue.get("created_at", "")
            is_stale = False
            is_duplicate = False
            if created_at_str:
                try:
                    created_at = datetime.fromisoformat(created_at_str.replace("Z", "+00:00"))
                    age = datetime.now(UTC) - created_at
                    is_stale = age > timedelta(days=_STALE_THRESHOLD_DAYS)
                except (ValueError, TypeError):
                    pass

            if _DUPLICATE_PATTERN.search(body):
                is_duplicate = True

            if is_stale or is_duplicate:
                reasons = []
                if is_stale:
                    reasons.append(f"issue is older than {_STALE_THRESHOLD_DAYS} days")
                if is_duplicate:
                    reasons.append("body references a duplicate issue")
                comment_body = "This issue has been flagged for human review:\n" + "\n".join(
                    f"- {r}" for r in reasons
                )
                await _label_issue(
                    token,
                    repo,
                    issue_number,
                    add=["needs-human-review"],
                )
                try:
                    async with httpx.AsyncClient(timeout=15.0) as cc:
                        await cc.post(
                            f"https://api.github.com/repos/{repo}/issues/{issue_number}/comments",
                            headers={
                                "Authorization": f"Bearer {token}",
                                "Accept": "application/vnd.github+json",
                            },
                            json={"body": comment_body},
                        )
                except Exception:
                    pass
                flagged += 1
                logger.info(
                    "Backlog scanner: flagged issue #%d -- %s",
                    issue_number,
                    ", ".join(reasons),
                )
                continue  # Skip dispatch for flagged issues

            # ── Phase C: Herald routing ──
            if issue_labels & _HERALD_LABELS:
                reactor.emit(
                    Event(
                        name="pipeline.herald_ready",
                        data={
                            "issue_number": issue_number,
                            "title": title,
                            "repo": repo,
                        },
                    )
                )
                dispatched += 1
                logger.info(
                    "Backlog scanner: routed issue #%d to Herald (labels: %s)",
                    issue_number,
                    issue_labels & _HERALD_LABELS,
                )
                continue

            # ── builders label filter ──
            if "builders" not in issue_labels:
                continue

            # ── Gatekeeper triage: atomic or decomposable? ──
            # Explicit labels override heuristics
            if "atomic" in issue_labels or "size/S" in issue_labels:
                is_atomic = True
            elif "epic" in issue_labels or "decompose" in issue_labels:
                is_atomic = False
            else:
                # Heuristic: issues with sub-tasks (checkboxes), multiple
                # "## " sections, or 500+ chars body likely need decomposition
                has_checkboxes = "- [ ]" in body
                has_sections = body.count("## ") >= 2
                is_long = len(body) > 500
                is_atomic = not (has_checkboxes or has_sections or is_long)

            logger.info(
                "Backlog scanner: triaging issue #%d (%s) -- %s",
                issue_number,
                title[:60],
                "atomic -> Archie+Mason" if is_atomic else "decomposable -> Quartermaster first",
            )

            # ── Phase D: Stage completion labels ──
            triage_label = "atomic" if is_atomic else "needs-decomposition"
            await _label_issue(
                token,
                repo,
                issue_number,
                add=[triage_label, "in-progress"],
                remove=["builders"],
            )

            # ── Dispatch through BuilderPipeline (full chain) ──
            orchestrator = getattr(container, "orchestrator", None)
            if orchestrator is None:
                reactor.emit(
                    Event(
                        name="pipeline.issue_ready",
                        data={
                            "issue_number": issue_number,
                            "title": title,
                            "repo": repo,
                            "atomic": is_atomic,
                        },
                    )
                )
            else:
                from stronghold.orchestrator.pipeline import BuilderPipeline  # noqa: PLC0415

                pipeline = BuilderPipeline(orchestrator)
                try:
                    await pipeline.execute(
                        issue_number=issue_number,
                        title=title,
                        repo=repo,
                        skip_decompose=is_atomic,
                    )
                    await _label_issue(
                        token,
                        repo,
                        issue_number,
                        add=["completed"],
                        remove=["in-progress"],
                    )
                except Exception as e:
                    logger.warning("Pipeline failed for issue #%d: %s", issue_number, e)
                    await _label_issue(
                        token,
                        repo,
                        issue_number,
                        add=["failed"],
                        remove=["in-progress"],
                    )

            dispatched += 1

        result: dict[str, Any] = {"scanned": len(issues), "dispatched": dispatched}
        if flagged:
            result["flagged"] = flagged
        return result

    reactor.register(
        TriggerSpec(
            name="issue_backlog_scanner",
            mode=TriggerMode.INTERVAL,
            interval_secs=300,  # every 5 minutes
        ),
        _scan_issue_backlog,
    )

    # 10. Mason PR review — review and improve an existing PR
    async def _mason_pr_review(event: Event) -> dict[str, Any]:
        """Dispatch PR review-and-improve requests to Mason."""
        pr_number = event.data.get("pr_number", 0)
        owner = event.data.get("owner", "")
        repo = event.data.get("repo", "")

        if not pr_number:
            return {"skipped": True}

        from stronghold.types.auth import SYSTEM_AUTH  # noqa: PLC0415

        try:
            await container.route_request(
                messages=[
                    {
                        "role": "user",
                        "content": (
                            f"Review and improve PR #{pr_number} in {owner}/{repo}.\n\n"
                            f"1. Fetch the PR diff and existing comments\n"
                            f"2. Read your stored learnings for common issues\n"
                            f"3. Identify improvements based on comments and "
                            f"project standards\n"
                            f"4. Apply improvements and push\n"
                            f"5. Run all quality gates before pushing"
                        ),
                    }
                ],
                auth=SYSTEM_AUTH,
                intent_hint="code_gen",
            )
            logger.info("Mason completed PR review #%d", pr_number)
            return {"pr_number": pr_number, "status": "completed"}
        except Exception as e:
            logger.warning("Mason PR review #%d failed: %s", pr_number, e)
            return {"pr_number": pr_number, "status": "failed", "error": str(e)}

    reactor.register(
        TriggerSpec(
            name="mason_pr_review",
            mode=TriggerMode.EVENT,
            event_pattern=r"mason\.pr_review_requested",
        ),
        _mason_pr_review,
    )

    # 11. Retrospective learning analysis (daily)
    async def _retrospective_analysis(event: Event) -> dict[str, Any]:
        """Run daily retrospective analysis across pipeline history."""
        from stronghold.learning.retrospective import (  # noqa: PLC0415
            RetrospectiveLearningManager,
        )

        mgr = RetrospectiveLearningManager()
        orchestrator = getattr(container, "orchestrator", None)
        if orchestrator is None:
            return {"skipped": True, "reason": "no orchestrator"}
        pipeline_history = getattr(orchestrator, "pipeline_history", [])
        if not pipeline_history:
            return {"skipped": True, "reason": "no pipeline history"}
        insights = await mgr.analyze_runs(pipeline_history)
        return {"insights": len(insights), "details": insights}

    reactor.register(
        TriggerSpec(
            name="retrospective_analysis",
            mode=TriggerMode.INTERVAL,
            interval_secs=86400,  # daily
        ),
        _retrospective_analysis,
    )

    logger.info("Registered %d core triggers", len(reactor._triggers))
