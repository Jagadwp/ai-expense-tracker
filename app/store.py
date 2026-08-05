"""Database access for the application.

Every SQL query lives here so the rest of the code depends on a small, typed
API rather than on the database directly. This layer is pure persistence: it
stores and retrieves whatever bytes it's given (e.g. already-encrypted OAuth
tokens) and has no knowledge of encryption — that's handled by app.security
at the call site.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime

import psycopg


class NotFoundError(Exception):
    """Raised when a lookup matches no rows."""


@dataclass
class OAuthToken:
    user_id: str
    encrypted_token: bytes
    gmail_email: str
    connected_at: datetime
    last_synced_at: datetime | None  # None until the first successful sync


@dataclass
class RawTransaction:
    """The raw fields captured from an email at ingestion time (M2).

    Extraction fields (date, merchant, amount, category, ...) are filled in
    later by the LLM step (M4) and are NULL until then.
    """

    message_id: str
    raw_subject: str
    raw_from: str
    raw_body: str


class Store:
    """Database access backed by a single psycopg async connection."""

    def __init__(self, conn: psycopg.AsyncConnection) -> None:
        self._conn = conn

    async def save_token(
        self, user_id: str, encrypted_token: bytes, gmail_email: str
    ) -> None:
        """Insert or update the encrypted OAuth token for a user.

        Because oauth_tokens has a UNIQUE(user_id) constraint, re-connecting
        the same user overwrites the previous token (and resets
        last_synced_at).
        """
        async with self._conn.cursor() as cur:
            await cur.execute(
                """
                INSERT INTO oauth_tokens (user_id, encrypted_token, gmail_email)
                VALUES (%s, %s, %s)
                ON CONFLICT (user_id) DO UPDATE
                SET encrypted_token = EXCLUDED.encrypted_token,
                    gmail_email     = EXCLUDED.gmail_email,
                    connected_at    = now(),
                    last_synced_at  = NULL
                """,
                (user_id, encrypted_token, gmail_email),
            )
        await self._conn.commit()

    async def get_token(self, user_id: str) -> OAuthToken:
        """Return the stored token for a user, or raise NotFoundError if the
        user has not connected an account."""
        async with self._conn.cursor() as cur:
            await cur.execute(
                """
                SELECT user_id, encrypted_token, gmail_email, connected_at, last_synced_at
                FROM oauth_tokens
                WHERE user_id = %s
                """,
                (user_id,),
            )
            row = await cur.fetchone()

        if row is None:
            raise NotFoundError(f"no token for user_id={user_id!r}")

        return OAuthToken(
            user_id=row[0],
            encrypted_token=bytes(row[1]),
            gmail_email=row[2],
            connected_at=row[3],
            last_synced_at=row[4],
        )

    async def delete_token(self, user_id: str) -> None:
        """Remove a user's stored token (disconnect). Deleting a
        non-existent token is not an error."""
        async with self._conn.cursor() as cur:
            await cur.execute(
                "DELETE FROM oauth_tokens WHERE user_id = %s", (user_id,)
            )
        await self._conn.commit()

    async def touch_last_synced(self, user_id: str) -> None:
        """Set last_synced_at to now for a user, marking a completed sync."""
        async with self._conn.cursor() as cur:
            await cur.execute(
                "UPDATE oauth_tokens SET last_synced_at = now() WHERE user_id = %s",
                (user_id,),
            )
        await self._conn.commit()

    # ------------------------------------------------------------------
    # Sender allowlist (sender_filters) — FR-02: configurable, not hardcoded.
    # Rows are managed by hand via psql until a settings UI exists.
    # ------------------------------------------------------------------

    async def get_active_sender_filters(self) -> list[str]:
        """Return the email addresses to pull transaction emails from."""
        async with self._conn.cursor() as cur:
            await cur.execute(
                "SELECT email_address FROM sender_filters WHERE active = true"
            )
            rows = await cur.fetchall()
        return [row[0] for row in rows]

    # ------------------------------------------------------------------
    # Dedup ledger (processed_emails) — see US-03 / FR-06
    # ------------------------------------------------------------------

    async def is_processed(self, message_id: str) -> bool:
        """Return True if this email has already been handled (regardless of
        whether it produced a transaction)."""
        async with self._conn.cursor() as cur:
            await cur.execute(
                "SELECT 1 FROM processed_emails WHERE message_id = %s",
                (message_id,),
            )
            row = await cur.fetchone()
        return row is not None

    async def mark_processed(self, message_id: str) -> None:
        """Record that an email has been handled. Idempotent — marking the
        same message_id twice is not an error."""
        async with self._conn.cursor() as cur:
            await cur.execute(
                """
                INSERT INTO processed_emails (message_id)
                VALUES (%s)
                ON CONFLICT (message_id) DO NOTHING
                """,
                (message_id,),
            )
        await self._conn.commit()

    # ------------------------------------------------------------------
    # Raw transaction ingestion (M2) — extraction fields filled in later (M4)
    # ------------------------------------------------------------------

    async def save_raw_transaction(self, tx: RawTransaction) -> None:
        """Store the raw email fields for a new transaction candidate.

        Extraction columns (date, merchant, amount, category, ...) are left
        NULL; the M4 extraction step fills them in with a separate update.
        """
        async with self._conn.cursor() as cur:
            await cur.execute(
                """
                INSERT INTO transactions (message_id, raw_subject, raw_from, raw_body)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (message_id) DO NOTHING
                """,
                (tx.message_id, tx.raw_subject, tx.raw_from, tx.raw_body),
            )
        await self._conn.commit()

    # ------------------------------------------------------------------
    # Error bucket (flagged_emails) — one failed email must not stop the
    # pipeline (FR-06)
    # ------------------------------------------------------------------

    async def flag_email(
        self,
        message_id: str,
        raw_body: str | None,
        error_message: str,
        flagged_reason: str,
    ) -> None:
        async with self._conn.cursor() as cur:
            await cur.execute(
                """
                INSERT INTO flagged_emails (message_id, raw_body, error_message, flagged_reason)
                VALUES (%s, %s, %s, %s)
                """,
                (message_id, raw_body, error_message, flagged_reason),
            )
        await self._conn.commit()

    # ------------------------------------------------------------------
    # Sync run observability (sync_logs)
    # ------------------------------------------------------------------

    async def create_sync_log(self, trigger: str) -> uuid.UUID:
        """Start a new sync_logs row with status='running' and return its id."""
        async with self._conn.cursor() as cur:
            await cur.execute(
                """
                INSERT INTO sync_logs (trigger, status)
                VALUES (%s, 'running')
                RETURNING id
                """,
                (trigger,),
            )
            row = await cur.fetchone()
        await self._conn.commit()
        return row[0]

    async def finish_sync_log(
        self,
        sync_log_id: uuid.UUID,
        status: str,
        emails_fetched: int,
        emails_new: int,
        emails_skipped: int,
        error_message: str | None = None,
    ) -> None:
        async with self._conn.cursor() as cur:
            await cur.execute(
                """
                UPDATE sync_logs
                SET status = %s,
                    emails_fetched = %s,
                    emails_new = %s,
                    emails_skipped = %s,
                    error_message = %s,
                    finished_at = now()
                WHERE id = %s
                """,
                (status, emails_fetched, emails_new, emails_skipped, error_message, sync_log_id),
            )
        await self._conn.commit()
