"""Scheduled sync (US-02): runs the same sync pipeline as /sync every 30
minutes, as a fallback in case the IMAP IDLE connection (M3) drops or misses
something. Uses AsyncIOScheduler so the job runs on the same event loop as
the rest of the app — no separate thread or process needed.

Each run also extracts up to EXTRACTION_LIMIT newly-synced emails, so the
dashboard shows finished transactions rather than raw, unextracted ones
between visits. Kept small since it runs unattended: steady-state volume per
30-minute window is normally a handful of emails, so a small cap keeps the
LLM cost per run predictable without needing user confirmation each time.
"""

import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from langchain_core.runnables import Runnable

from app.extract_runner import run_extraction
from app.security import Encryptor
from app.store import Store
from app.sync_runner import NoGmailConnected, run_sync

logger = logging.getLogger(__name__)

SYNC_INTERVAL_MINUTES = 30
EXTRACTION_LIMIT = 10


def create_scheduler(store: Store, encryptor: Encryptor, extraction_llm: Runnable) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler()

    async def scheduled_job():
        try:
            result = await run_sync(store, encryptor, "scheduled", newer_than="1d")
            logger.info("scheduled sync completed: %s", result)
        except NoGmailConnected:
            logger.info("scheduled sync skipped: no Gmail account connected")
            return
        except Exception:
            logger.exception("scheduled sync failed")
            return

        try:
            extraction_result = await run_extraction(store, extraction_llm, limit=EXTRACTION_LIMIT)
            logger.info("scheduled extraction completed: %s", extraction_result)
        except Exception:
            logger.exception("scheduled extraction failed")

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
