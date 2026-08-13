"""Shared LLM-extraction orchestration (M4).

The manual POST /extract route and the combined "Sync now" dashboard action
(POST /api/sync-and-extract) both run the exact same batch-extraction loop.
Keeping it in one place avoids two near-identical copies, mirroring the
app.sync_runner pattern for the sync pipeline.
"""

import logging
from typing import Callable

from anthropic import Anthropic

from app.extraction import CONFIDENCE_THRESHOLD, extract_transaction
from app.store import Store

logger = logging.getLogger(__name__)


async def run_extraction(
    store: Store,
    anthropic: Anthropic,
    limit: int | None,
    on_progress: Callable[[int, int], None] | None = None,
) -> dict:
    """Run LLM extraction over up to `limit` unextracted transactions and
    return summary counts, including how many still remain unextracted
    afterward (so a caller can offer an "extract more" follow-up instead of
    looping automatically — each batch is a real LLM-API cost).

    on_progress(processed, total), if given, is called after each email so a
    caller can expose a live "X of Y" indicator (e.g. for a polling
    endpoint). Background callers (scheduler, IMAP IDLE) omit it since
    nobody's watching.

    One email's failure is recorded in flagged_emails and does not stop the
    rest of the batch (FR-06).
    """
    candidates = await store.get_unextracted_transactions(limit=limit)
    total = len(candidates)
    if on_progress:
        on_progress(0, total)

    extracted = 0
    skipped_non_transaction = 0
    flagged_low_confidence = 0
    failed = 0

    for i, tx in enumerate(candidates, start=1):
        try:
            result = extract_transaction(anthropic, tx.raw_subject, tx.raw_from, tx.raw_body)

            if not result.is_transaction:
                await store.delete_non_transaction(tx.message_id)
                skipped_non_transaction += 1
            elif result.confidence < CONFIDENCE_THRESHOLD:
                await store.set_low_confidence(tx.message_id, result.confidence)
                await store.flag_email(
                    message_id=tx.message_id,
                    raw_body=tx.raw_body,
                    error_message=f"low confidence: {result.model_dump_json()}",
                    flagged_reason="low_confidence",
                )
                flagged_low_confidence += 1
            else:
                await store.apply_extraction(
                    message_id=tx.message_id,
                    date=result.date,
                    merchant=result.merchant,
                    amount=result.amount,
                    currency=result.currency,
                    category=result.category,
                    payment_method=result.payment_method,
                    confidence=result.confidence,
                    is_transfer=result.is_transfer,
                )
                extracted += 1
        except Exception as exc:
            logger.exception("extraction failed for message %s", tx.message_id)
            await store.rollback()
            await store.flag_email(
                message_id=tx.message_id,
                raw_body=tx.raw_body,
                error_message=str(exc),
                flagged_reason="extraction_error",
            )
            failed += 1

        if on_progress:
            on_progress(i, total)

    remaining_unextracted = len(await store.get_unextracted_transactions(limit=None))

    return {
        "candidates": len(candidates),
        "extracted": extracted,
        "skipped_non_transaction": skipped_non_transaction,
        "flagged_low_confidence": flagged_low_confidence,
        "failed": failed,
        "remaining_unextracted": remaining_unextracted,
    }
