"""Inspect CLI: read-only queries over a turing SQLite database.

Subcommands:

    summarize          counts by tier/source + recent durable entries
    dispatch-log       recent dispatch decisions
    daydream-sessions  recent daydream session markers + their I_IMAGINED outputs
    lineage <id>       walk supersedes/superseded_by chains both directions
    pressure           current pressure vector (requires --metrics-url)

Usage:

    python -m turing.runtime.inspect summarize --db /tmp/turing.db
    python -m turing.runtime.inspect lineage <memory_id> --db /tmp/turing.db
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any


def _connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def cmd_summarize(args: argparse.Namespace) -> int:
    conn = _connect(args.db)
    print(f"== turing summary (db={args.db}) ==")
    _print_section(conn, "episodic_memory", "tier, source")
    _print_section(conn, "durable_memory", "tier, source")

    row = conn.execute(
        "SELECT self_id, created_at FROM self_identity WHERE archived_at IS NULL"
    ).fetchone()
    if row:
        print(f"\nself_id = {row['self_id']} (created {row['created_at']})")

    print("\nrecent REGRETs:")
    for r in conn.execute(
        "SELECT content, affect, created_at FROM durable_memory "
        "WHERE tier = 'regret' ORDER BY created_at DESC LIMIT 5"
    ):
        print(f"  {r['created_at']}  affect={r['affect']:+.2f}  {r['content'][:80]}")

    print("\nrecent ACCOMPLISHMENTs:")
    for r in conn.execute(
        "SELECT content, affect, created_at FROM durable_memory "
        "WHERE tier = 'accomplishment' ORDER BY created_at DESC LIMIT 5"
    ):
        print(f"  {r['created_at']}  affect={r['affect']:+.2f}  {r['content'][:80]}")

    print("\nrecent coefficient commitments:")
    for r in conn.execute(
        "SELECT content, created_at FROM durable_memory "
        "WHERE tier = 'affirmation' AND content LIKE 'coefficient_commitment:%' "
        "AND superseded_by IS NULL "
        "ORDER BY created_at DESC LIMIT 10"
    ):
        print(f"  {r['created_at']}  {r['content']}")

    conn.close()
    return 0


def cmd_dispatch_log(args: argparse.Namespace) -> int:
    """Reads dispatch traces stored in episodic_memory session markers and
    anything tagged as such. Chunk 4 prints what the in-memory observation
    list writes to disk via session markers; a richer dispatch log store
    can be added in a future chunk."""
    conn = _connect(args.db)
    print(f"== dispatch-adjacent markers (db={args.db}) ==")
    limit = args.limit
    for r in conn.execute(
        "SELECT created_at, content FROM episodic_memory "
        "WHERE tier = 'observation' AND source = 'i_did' "
        "ORDER BY created_at DESC LIMIT ?",
        (limit,),
    ):
        print(f"  {r['created_at']}  {r['content'][:100]}")
    conn.close()
    return 0


def cmd_daydream_sessions(args: argparse.Namespace) -> int:
    conn = _connect(args.db)
    print(f"== daydream sessions (db={args.db}) ==")
    rows = list(
        conn.execute(
            "SELECT created_at, content, origin_episode_id FROM episodic_memory "
            "WHERE tier = 'observation' AND source = 'i_did' "
            "AND content LIKE 'daydream session%' "
            "ORDER BY created_at DESC LIMIT ?",
            (args.limit,),
        )
    )
    for r in rows:
        print(f"\n  {r['created_at']}  {r['content'][:120]}")
        session_id = r["origin_episode_id"]
        if session_id is None:
            continue
        for c in conn.execute(
            "SELECT tier, source, content FROM episodic_memory "
            "WHERE origin_episode_id = ? AND source = 'i_imagined' "
            "ORDER BY created_at ASC LIMIT 10",
            (session_id,),
        ):
            print(f"    [{c['tier']}/{c['source']}] {c['content'][:100]}")
    conn.close()
    return 0


def cmd_lineage(args: argparse.Namespace) -> int:
    conn = _connect(args.db)
    memory_id = args.memory_id

    row = _fetch_memory(conn, memory_id)
    if row is None:
        print(f"no memory with id {memory_id}", file=sys.stderr)
        return 1

    print(f"== lineage for {memory_id} ==")
    print("\nbackward (supersedes chain):")
    chain: list[dict[str, Any]] = []
    current = row
    while current is not None:
        chain.append(dict(current))
        if current["supersedes"] is None:
            break
        current = _fetch_memory(conn, current["supersedes"])
    chain.reverse()
    for m in chain:
        _print_lineage_row(m)

    print("\nforward (superseded_by chain from start):")
    current = chain[0] if chain else row
    while current is not None:
        _print_lineage_row(current)
        next_id = current["superseded_by"]
        if next_id is None:
            break
        current = _fetch_memory(conn, next_id)

    conn.close()
    return 0


def cmd_pressure(args: argparse.Namespace) -> int:
    """Queries a running metrics endpoint for the current pressure vector.

    Requires `--metrics-url`. Format: `http://localhost:9100/metrics`.
    """
    import urllib.request

    try:
        with urllib.request.urlopen(args.metrics_url, timeout=2.0) as resp:
            body = resp.read().decode("utf-8")
    except OSError as exc:
        print(f"could not reach {args.metrics_url}: {exc}", file=sys.stderr)
        return 1

    print(f"== pressure ({args.metrics_url}) ==")
    for line in body.splitlines():
        if line.startswith("turing_pressure"):
            print(f"  {line}")
    return 0


# ------------------------------------------------------------------ helpers


def _print_section(conn: sqlite3.Connection, table: str, group_by: str) -> None:
    print(f"\n{table}:")
    try:
        rows = list(
            conn.execute(
                f"SELECT {group_by}, COUNT(*) AS n FROM {table} "
                f"GROUP BY {group_by} ORDER BY n DESC"
            )
        )
    except sqlite3.OperationalError:
        print(f"  (table missing or empty)")
        return
    if not rows:
        print("  (empty)")
        return
    for r in rows:
        tier = r["tier"]
        source = r["source"]
        n = r["n"]
        print(f"  {tier:<20}  {source:<12}  n={n}")


def _fetch_memory(conn: sqlite3.Connection, memory_id: str) -> sqlite3.Row | None:
    for table in ("durable_memory", "episodic_memory"):
        row = conn.execute(
            f"SELECT * FROM {table} WHERE memory_id = ?", (memory_id,)
        ).fetchone()
        if row is not None:
            return row
    return None


def _print_lineage_row(m: sqlite3.Row | dict) -> None:
    mid = m["memory_id"] if isinstance(m, sqlite3.Row) else m["memory_id"]
    tier = m["tier"]
    source = m["source"]
    created = m["created_at"]
    content = str(m["content"])
    print(f"  {created}  [{tier}/{source}]  {mid[:8]}…  {content[:80]}")


# ------------------------------------------------------------------- main


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="turing-inspect")
    p.add_argument("--db", required=True, help="path to the turing SQLite db")
    sub = p.add_subparsers(dest="command", required=True)

    s = sub.add_parser("summarize")
    s.set_defaults(func=cmd_summarize)

    s = sub.add_parser("dispatch-log")
    s.add_argument("--limit", type=int, default=20)
    s.set_defaults(func=cmd_dispatch_log)

    s = sub.add_parser("daydream-sessions")
    s.add_argument("--limit", type=int, default=10)
    s.set_defaults(func=cmd_daydream_sessions)

    s = sub.add_parser("lineage")
    s.add_argument("memory_id")
    s.set_defaults(func=cmd_lineage)

    s = sub.add_parser("pressure")
    s.add_argument(
        "--metrics-url",
        default="http://localhost:9100/metrics",
    )
    s.set_defaults(func=cmd_pressure)

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
