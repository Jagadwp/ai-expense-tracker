"""Gmail fetch, dedup, and raw-transaction ingestion (M2).

This module only pulls the raw email fields (subject, sender, body) into
`transactions` — the LLM extraction step that fills in date/merchant/amount/
category runs separately in M4. A single email's failure never stops the
sync (FR-06): failures are recorded in flagged_emails and the loop continues.
"""

import base64
import logging

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from app.store import RawTransaction, Store

logger = logging.getLogger(__name__)


def _build_query(sender_filters: list[str], newer_than: str) -> str:
    """Build the Gmail search query: any of the configured senders, within
    the given time window (e.g. "7d" or "90d" for the first onboarding sync,
    per FR-03). Sender list comes from GMAIL_SENDER_FILTERS (FR-02:
    configurable, not hardcoded) — see app.config.Settings."""
    sender_clause = " OR ".join(f"from:{addr}" for addr in sender_filters)
    return f"({sender_clause}) newer_than:{newer_than}"


def _decode_part_data(part: dict) -> str | None:
    data = part.get("body", {}).get("data")
    if data:
        return base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")
    return None


def _find_part_by_mime_type(payload: dict, mime_type: str) -> str | None:
    """Recursively search payload.parts for the first part matching
    mime_type. Multipart messages can nest arbitrarily (e.g. Gmail wraps
    multipart/related inside multipart/mixed for messages with inline
    images), so a single-level scan misses real-world emails."""
    if payload.get("mimeType") == mime_type:
        decoded = _decode_part_data(payload)
        if decoded:
            return decoded

    for part in payload.get("parts", []):
        found = _find_part_by_mime_type(part, mime_type)
        if found:
            return found

    return None


def _decode_body(payload: dict) -> str:
    """Extract and decode the plain-text (or HTML, as a fallback) body from
    a Gmail message payload, searching nested multipart parts at any depth.
    Gmail encodes body data as URL-safe base64."""

    # Simple message: body directly on the top-level payload.
    direct = _decode_part_data(payload)
    if direct:
        return direct

    for mime_type in ("text/plain", "text/html"):
        found = _find_part_by_mime_type(payload, mime_type)
        if found:
            return found

    return ""


class GmailSyncer:
    """Fetches transaction emails for one user and ingests new ones."""

    def __init__(self, store: Store, credentials: Credentials):
        self._store = store
        self._service = build("gmail", "v1", credentials=credentials)

    async def sync(self, newer_than: str = "7d") -> tuple[int, int, int]:
        """Fetch matching emails and ingest the ones not already processed.

        Returns (emails_fetched, emails_new, emails_skipped).
        """
        sender_filters = await self._store.get_active_sender_filters()
        if not sender_filters:
            raise ValueError(
                "no active sender_filters configured — insert at least one "
                "row into the sender_filters table before syncing"
            )

        query = _build_query(sender_filters, newer_than)
        message_ids = self._list_message_ids(query)

        emails_new = 0
        emails_skipped = 0

        for message_id in message_ids:
            if await self._store.is_processed(message_id):
                emails_skipped += 1
                continue

            try:
                await self._ingest_one(message_id)
                emails_new += 1
            except Exception as exc:
                # A single email's failure must not stop the pipeline (FR-06).
                logger.exception("failed to ingest message %s", message_id)
                await self._store.flag_email(
                    message_id=message_id,
                    raw_body=None,
                    error_message=str(exc),
                    flagged_reason="ingest_error",
                )
            finally:
                # Mark as processed even on failure, so a broken email isn't
                # retried forever on every sync — it stays visible for
                # manual review in flagged_emails instead.
                await self._store.mark_processed(message_id)

        return len(message_ids), emails_new, emails_skipped

    def _list_message_ids(self, query: str) -> list[str]:
        message_ids: list[str] = []
        request = self._service.users().messages().list(userId="me", q=query)
        while request is not None:
            response = request.execute()
            message_ids.extend(m["id"] for m in response.get("messages", []))
            request = self._service.users().messages().list_next(request, response)
        return message_ids

    async def _ingest_one(self, message_id: str) -> None:
        message = (
            self._service.users()
            .messages()
            .get(userId="me", id=message_id, format="full")
            .execute()
        )

        headers = {
            h["name"]: h["value"]
            for h in message.get("payload", {}).get("headers", [])
        }
        raw_subject = headers.get("Subject", "")
        raw_from = headers.get("From", "")
        raw_body = _decode_body(message.get("payload", {}))

        await self._store.save_raw_transaction(
            RawTransaction(
                message_id=message_id,
                raw_subject=raw_subject,
                raw_from=raw_from,
                raw_body=raw_body,
            )
        )
