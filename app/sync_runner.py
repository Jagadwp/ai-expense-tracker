"""Shared sync orchestration.

The manual /sync route, the scheduled job (M3), and the IMAP IDLE listener
(M3) all trigger the exact same pipeline — get the stored token, refresh it
if needed, run GmailSyncer, and record the result to sync_logs. They differ
only in the `trigger` label passed through. Keeping this in one place avoids
three near-identical copies of the same orchestration logic.
"""

import logging

from app import gmail_auth
from app.gmail_sync import GmailSyncer
from app.security import Encryptor
from app.store import NotFoundError, Store

logger = logging.getLogger(__name__)

# Single-user MVP: every stored token belongs to this fixed user id (matches
# the oauth_tokens.user_id DEFAULT 'default' in the migration).
DEFAULT_USER_ID = "default"


class NoGmailConnected(Exception):
    """Raised when a sync is attempted with no Gmail account connected."""


async def run_sync(
    store: Store, encryptor: Encryptor, trigger: str, newer_than: str = "7d"
) -> dict:
    """Run one sync pass and return its summary counts.

    Raises NoGmailConnected if no account is connected, or re-raises the
    underlying error after recording the failed run to sync_logs.
    """
    try:
        token = await store.get_token(DEFAULT_USER_ID)
    except NotFoundError:
        raise NoGmailConnected("no Gmail account connected")

    token_json = encryptor.decrypt(token.encrypted_token)
    credentials = gmail_auth.credentials_from_token_json(token_json)

    if gmail_auth.refresh_if_expired(credentials):
        refreshed_token_json = credentials.to_json().encode("utf-8")
        encrypted_token = encryptor.encrypt(refreshed_token_json)
        await store.save_token(DEFAULT_USER_ID, encrypted_token, token.gmail_email)

    sync_log_id = await store.create_sync_log(trigger)
    syncer = GmailSyncer(store, credentials)

    try:
        emails_fetched, emails_new, emails_skipped = await syncer.sync(newer_than)
    except Exception as exc:
        logger.exception("sync failed (trigger=%s)", trigger)
        await store.finish_sync_log(
            sync_log_id,
            status="failed",
            emails_fetched=0,
            emails_new=0,
            emails_skipped=0,
            error_message=str(exc),
        )
        raise

    await store.finish_sync_log(
        sync_log_id,
        status="success",
        emails_fetched=emails_fetched,
        emails_new=emails_new,
        emails_skipped=emails_skipped,
    )
    await store.touch_last_synced(DEFAULT_USER_ID)

    return {
        "sync_log_id": str(sync_log_id),
        "emails_fetched": emails_fetched,
        "emails_new": emails_new,
        "emails_skipped": emails_skipped,
    }
