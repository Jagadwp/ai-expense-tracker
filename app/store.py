"""Database access for the application.

Every SQL query lives here so the rest of the code depends on a small, typed
API rather than on the database directly. This layer is pure persistence: it
stores and retrieves whatever bytes it's given (e.g. already-encrypted OAuth
tokens) and has no knowledge of encryption — that's handled by app.security
at the call site.
"""

import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta

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
    # LLM extraction (M4) — fills in the extraction columns left NULL by
    # save_raw_transaction, or removes/flags the row when extraction
    # determines it isn't a usable transaction.
    # ------------------------------------------------------------------

    async def get_unextracted_transactions(
        self, limit: int | None = None
    ) -> list[RawTransaction]:
        """Return raw transactions not yet extracted, excluding any already
        flagged for review (so a flagged email isn't retried every run)."""
        query = """
            SELECT message_id, raw_subject, raw_from, raw_body
            FROM transactions
            WHERE extracted_at IS NULL
              AND message_id NOT IN (SELECT message_id FROM flagged_emails)
        """
        params: tuple = ()
        if limit is not None:
            query += " LIMIT %s"
            params = (limit,)

        async with self._conn.cursor() as cur:
            await cur.execute(query, params)
            rows = await cur.fetchall()
        return [
            RawTransaction(
                message_id=row[0], raw_subject=row[1], raw_from=row[2], raw_body=row[3]
            )
            for row in rows
        ]

    async def apply_extraction(
        self,
        message_id: str,
        date: str | None,
        merchant: str | None,
        amount: float | None,
        currency: str,
        category: str | None,
        payment_method: str | None,
        confidence: float,
        is_transfer: bool = False,
    ) -> None:
        """Write a confident extraction result into transactions and mark it
        as extracted (excludes it from future get_unextracted_transactions
        calls)."""
        async with self._conn.cursor() as cur:
            await cur.execute(
                """
                UPDATE transactions
                SET date = %s, merchant = %s, amount = %s, currency = %s,
                    category = %s, payment_method = %s, confidence = %s,
                    is_transfer = %s, extracted_at = now()
                WHERE message_id = %s
                """,
                (date, merchant, amount, currency, category, payment_method, confidence, is_transfer, message_id),
            )
        await self._conn.commit()

    async def set_low_confidence(self, message_id: str, confidence: float) -> None:
        """Record only the confidence score for a low-confidence extraction.

        The other extraction columns and extracted_at are left NULL — the
        guessed values are never written into transactions until a human
        reviews flagged_emails and applies them manually.
        """
        async with self._conn.cursor() as cur:
            await cur.execute(
                "UPDATE transactions SET confidence = %s WHERE message_id = %s",
                (confidence, message_id),
            )
        await self._conn.commit()

    async def delete_non_transaction(self, message_id: str) -> None:
        """Remove a transactions row that extraction determined isn't a real
        transaction (FR-09). Dedup is unaffected — processed_emails already
        prevents this email from being fetched again."""
        async with self._conn.cursor() as cur:
            await cur.execute(
                "DELETE FROM transactions WHERE message_id = %s", (message_id,)
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

    # ------------------------------------------------------------------
    # Dashboard read queries (M5) — filters and aggregates for the Vue SPA,
    # served over the /api/* routes in app.main.
    # ------------------------------------------------------------------

    async def list_transactions(
        self,
        date_from: date,
        date_to: date,
        category: str | None = None,
        sort_by: str = "date",
        include_transfers: bool = True,
    ) -> list[dict]:
        """Return extracted transactions within [date_from, date_to]
        (inclusive), optionally filtered by category, sorted by date or
        amount (descending).

        Transfers (is_transfer=true) are included by default so they stay
        visible for audit — they're excluded from spend totals elsewhere in
        this module, not hidden from the list."""
        order_column = "amount" if sort_by == "amount" else "date"

        conditions = ["extracted_at IS NOT NULL", "date >= %s", "date < %s"]
        params: list = [date_from, date_to + timedelta(days=1)]
        if category:
            conditions.append("category = %s")
            params.append(category)
        if not include_transfers:
            conditions.append("is_transfer = false")

        query = f"""
            SELECT date, merchant, category, amount, payment_method, is_transfer
            FROM transactions
            WHERE {" AND ".join(conditions)}
            ORDER BY {order_column} DESC
        """
        async with self._conn.cursor() as cur:
            await cur.execute(query, params)
            rows = await cur.fetchall()

        return [
            {
                "date": row[0].isoformat() if row[0] else None,
                "merchant": row[1],
                "category": row[2],
                "amount": float(row[3]) if row[3] is not None else None,
                "payment_method": row[4],
                "is_transfer": row[5],
            }
            for row in rows
        ]

    async def list_categories(self) -> list[str]:
        """Return the distinct categories present in extracted transactions,
        for populating a filter dropdown. Not scoped to a date range — the
        category set is small and effectively fixed, so showing all of them
        regardless of the selected window is more useful than an empty or
        shifting list."""
        async with self._conn.cursor() as cur:
            await cur.execute(
                """
                SELECT DISTINCT category FROM transactions
                WHERE extracted_at IS NOT NULL AND category IS NOT NULL
                ORDER BY category
                """
            )
            rows = await cur.fetchall()
        return [row[0] for row in rows]

    async def list_available_months(self) -> list[str]:
        """Return the distinct months ("YYYY-MM", most recent first) that
        have at least one extracted transaction — bounds the dashboard's
        month picker to months that actually have data."""
        async with self._conn.cursor() as cur:
            await cur.execute(
                """
                SELECT DISTINCT to_char(date, 'YYYY-MM') AS month
                FROM transactions
                WHERE extracted_at IS NOT NULL AND date IS NOT NULL
                ORDER BY month DESC
                """
            )
            rows = await cur.fetchall()
        return [row[0] for row in rows]

    async def category_totals(self, date_from: date, date_to: date) -> list[dict]:
        """Return total spend per category within [date_from, date_to]
        (inclusive).

        Excludes is_transfer=true rows — fund movements aren't real spend."""
        query = """
            SELECT category, SUM(amount) AS total
            FROM transactions
            WHERE extracted_at IS NOT NULL AND is_transfer = false
              AND date >= %s AND date < %s
            GROUP BY category
            ORDER BY total DESC
        """
        async with self._conn.cursor() as cur:
            await cur.execute(query, (date_from, date_to + timedelta(days=1)))
            rows = await cur.fetchall()

        return [{"category": row[0], "total": float(row[1])} for row in rows]

    async def spend_trend(self, date_from: date, date_to: date) -> list[dict]:
        """Return total spend per day within [date_from, date_to]
        (inclusive), for the trend chart.

        Excludes is_transfer=true rows — fund movements aren't real spend."""
        async with self._conn.cursor() as cur:
            await cur.execute(
                """
                SELECT date_trunc('day', date) AS day, SUM(amount) AS total
                FROM transactions
                WHERE extracted_at IS NOT NULL AND is_transfer = false
                  AND date >= %s AND date < %s
                GROUP BY day
                ORDER BY day
                """,
                (date_from, date_to + timedelta(days=1)),
            )
            rows = await cur.fetchall()

        return [{"date": row[0].date().isoformat(), "total": float(row[1])} for row in rows]

    async def period_comparison(self, date_from: date, date_to: date) -> dict:
        """Return the total spend in [date_from, date_to] (inclusive) and in
        the immediately preceding period of the same length, for a
        period-over-period comparison.

        Excludes is_transfer=true rows — fund movements aren't real spend."""
        duration = (date_to - date_from) + timedelta(days=1)
        previous_to_exclusive = date_from
        previous_from = date_from - duration

        async with self._conn.cursor() as cur:
            await cur.execute(
                """
                SELECT
                    SUM(amount) FILTER (WHERE date >= %(from)s AND date < %(to)s) AS current_total,
                    SUM(amount) FILTER (WHERE date >= %(prev_from)s AND date < %(prev_to)s) AS previous_total
                FROM transactions
                WHERE extracted_at IS NOT NULL AND is_transfer = false
                """,
                {
                    "from": date_from,
                    "to": date_to + timedelta(days=1),
                    "prev_from": previous_from,
                    "prev_to": previous_to_exclusive,
                },
            )
            row = await cur.fetchone()

        return {
            "current_total": float(row[0]) if row[0] is not None else 0.0,
            "previous_total": float(row[1]) if row[1] is not None else 0.0,
        }
