"""Scheduled sync (US-02): runs the same sync pipeline as /sync every 30
minutes, as a fallback in case the IMAP IDLE connection (M3) drops or misses
something. Uses AsyncIOScheduler so the job runs on the same event loop as
the rest of the app — no separate thread or process needed.
"""

import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.security import Encryptor
from app.store import Store
from app.sync_runner import NoGmailConnected, run_sync

logger = logging.getLogger(__name__)

SYNC_INTERVAL_MINUTES = 30


def create_scheduler(store: Store, encryptor: Encryptor) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler()

    async def scheduled_job():
        try:
            result = await run_sync(store, encryptor, "scheduled", newer_than="1d")
            logger.info("scheduled sync completed: %s", result)
        except NoGmailConnected:
            logger.info("scheduled sync skipped: no Gmail account connected")
        except Exception:
            logger.exception("scheduled sync failed")

    scheduler.add_job(
        scheduled_job,
        trigger="interval",
        minutes=SYNC_INTERVAL_MINUTES,
        id="scheduled_sync",
        # Prevent overlapping runs piling up if one sync takes unusually long.
        max_instances=1,
        coalesce=True,
    )
    return scheduler
