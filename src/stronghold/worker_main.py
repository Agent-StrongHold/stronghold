"""Worker entry point: runs as a separate pod/process.

Creates a full Container (same wiring as the API), then polls the
task queue and routes each task through container.route_request().

Usage:
    python -m stronghold.worker_main

In production, this runs as a separate K8s Deployment sharing the
same DATABASE_URL / REDIS_URL as the API pods, so the task queue
is backed by PostgreSQL or Redis (not in-memory).
"""

from __future__ import annotations

import asyncio
import logging
import signal

from stronghold.agents.worker import AgentWorker
from stronghold.config.loader import load_config
from stronghold.container import create_container

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("stronghold.worker")


async def main() -> None:
    """Start the worker loop with proper Container wiring and signal handling."""
    config = load_config()
    container = await create_container(config)

    worker = AgentWorker(container=container)

    # Register signal handlers for graceful shutdown
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, worker.request_shutdown)

    logger.info("Worker started. Polling task queue...")
    await worker.run_loop(max_idle_seconds=3600)
    logger.info("Worker stopped.")


if __name__ == "__main__":
    asyncio.run(main())
