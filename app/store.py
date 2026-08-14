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
from decimal import Decimal

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

    async def rollback(self) -> None:
        """Roll back the shared connection's current transaction. A failed
        query leaves it aborted until this is called — every subsequent
        query (including on later, unrelated requests) would otherwise fail
        too. Called by extraction error handling (app.extract_runner)."""
        await self._conn.rollback()

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
        await self._conn.commit()

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
        await self._conn.commit()
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
        await self._conn.commit()
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
              AND deleted_at IS NULL
              AND message_id NOT IN (SELECT message_id FROM flagged_emails)
        """
        params: tuple = ()
        if limit is not None:
            query += " LIMIT %s"
            params = (limit,)

        async with self._conn.cursor() as cur:
            await cur.execute(query, params)
            rows = await cur.fetchall()
        await self._conn.commit()
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

    # Whitelist mapping — never interpolate a caller-supplied column name
    # directly into SQL. FastAPI's Literal type on the route already
    # restricts sort_by, but this is checked again here as the actual
    # injection guard.
    _SORT_COLUMNS = {
        "date": "date",
        "merchant": "merchant",
        "category": "category",
        "amount": "amount",
        "payment_method": "payment_method",
        "is_transfer": "is_transfer",
    }

    async def list_transactions(
        self,
        date_from: date,
        date_to: date,
        category: str | None = None,
        sort_by: str = "date",
        sort_dir: str = "desc",
        include_transfers: bool = True,
        page: int = 1,
        page_size: int = 20,
    ) -> dict:
        """Return one page of extracted transactions within [date_from,
        date_to] (inclusive), optionally filtered by category, sorted by
        any column. Returns {"items": [...], "total": <matching row count>}
        so the caller can render pagination controls.

        Transfers (is_transfer=true) are included by default so they stay
        visible for audit — they're excluded from spend totals elsewhere in
        this module, not hidden from the list."""
        order_column = self._SORT_COLUMNS.get(sort_by, "date")
        order_dir = "ASC" if sort_dir == "asc" else "DESC"

        conditions = ["extracted_at IS NOT NULL", "deleted_at IS NULL", "date >= %s", "date < %s"]
        params: list = [date_from, date_to + timedelta(days=1)]
        if category:
            conditions.append("category = %s")
            params.append(category)
        if not include_transfers:
            conditions.append("is_transfer = false")
        where_clause = " AND ".join(conditions)

        async with self._conn.cursor() as cur:
            await cur.execute(f"SELECT COUNT(*) FROM transactions WHERE {where_clause}", params)
            total = (await cur.fetchone())[0]

        query = f"""
            SELECT message_id, date, merchant, category, amount, payment_method, is_transfer, is_manual
            FROM transactions
            WHERE {where_clause}
            ORDER BY {order_column} {order_dir} NULLS LAST
            LIMIT %s OFFSET %s
        """
        async with self._conn.cursor() as cur:
            await cur.execute(query, [*params, page_size, (page - 1) * page_size])
            rows = await cur.fetchall()
        await self._conn.commit()

        items = [
            {
                "message_id": row[0],
                "date": row[1].isoformat() if row[1] else None,
                "merchant": row[2],
                "category": row[3],
                "amount": float(row[4]) if row[4] is not None else None,
                "payment_method": row[5],
                "is_transfer": row[6],
                "is_manual": row[7],
            }
            for row in rows
        ]
        return {"items": items, "total": total}

    async def get_transaction_detail(self, message_id: str) -> dict | None:
        """Return the full record (raw email fields + extracted fields) for
        one transaction, for the dashboard's email-preview modal. Returns
        None if no transaction has this message_id, or if it's been
        (soft-)deleted."""
        async with self._conn.cursor() as cur:
            await cur.execute(
                """
                SELECT message_id, raw_subject, raw_from, raw_body, date, merchant,
                       category, amount, payment_method, is_transfer, is_manual
                FROM transactions
                WHERE message_id = %s AND deleted_at IS NULL
                """,
                (message_id,),
            )
            row = await cur.fetchone()
        await self._conn.commit()

        if row is None:
            return None

        return {
            "message_id": row[0],
            "raw_subject": row[1],
            "raw_from": row[2],
            "raw_body": row[3],
            "date": row[4].isoformat() if row[4] else None,
            "merchant": row[5],
            "category": row[6],
            "amount": float(row[7]) if row[7] is not None else None,
            "payment_method": row[8],
            "is_transfer": row[9],
            "is_manual": row[10],
        }

    async def set_is_transfer(self, message_id: str, is_transfer: bool) -> None:
        """Manually flag (or unflag) a transaction as a fund transfer, from
        the dashboard's email-preview modal."""
        async with self._conn.cursor() as cur:
            await cur.execute(
                "UPDATE transactions SET is_transfer = %s WHERE message_id = %s",
                (is_transfer, message_id),
            )
        await self._conn.commit()

    # ------------------------------------------------------------------
    # Manual transaction CRUD — dashboard "Add transaction" / edit / delete.
    # Editing is allowed on any transaction (manual or email-derived): a
    # human correcting a wrong LLM guess is a real, recurring need. The raw
    # email fields (subject/from/body) are never editable — they're the
    # historical record of what Gmail actually sent.
    # ------------------------------------------------------------------

    async def create_manual_transaction(
        self,
        date: date | None,
        merchant: str | None,
        amount: float | None,
        currency: str,
        category: str | None,
        payment_method: str | None,
        is_transfer: bool,
    ) -> str:
        """Insert a manually-entered transaction and return its synthesized
        message_id. There's no real Gmail message behind it, so a synthetic
        id (manual:<uuid>) fills the NOT NULL UNIQUE message_id column
        without risking a collision with a real one. extracted_at is set to
        now() so it's included in the dashboard's aggregates immediately, and
        confidence stays NULL — it isn't an LLM guess."""
        message_id = f"manual:{uuid.uuid4()}"
        async with self._conn.cursor() as cur:
            await cur.execute(
                """
                INSERT INTO transactions
                    (message_id, date, merchant, amount, currency, category,
                     payment_method, is_transfer, is_manual, extracted_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, true, now())
                """,
                (message_id, date, merchant, amount, currency, category, payment_method, is_transfer),
            )
        await self._conn.commit()
        return message_id

    async def update_transaction(
        self,
        message_id: str,
        date: date | None,
        merchant: str | None,
        amount: float | None,
        currency: str,
        category: str | None,
        payment_method: str | None,
        is_transfer: bool,
    ) -> bool:
        """Overwrite a transaction's editable fields. Returns False if no
        (non-deleted) transaction has this message_id (caller should 404)."""
        async with self._conn.cursor() as cur:
            await cur.execute(
                """
                UPDATE transactions
                SET date = %s, merchant = %s, amount = %s, currency = %s,
                    category = %s, payment_method = %s, is_transfer = %s
                WHERE message_id = %s AND deleted_at IS NULL
                """,
                (date, merchant, amount, currency, category, payment_method, is_transfer, message_id),
            )
            updated = cur.rowcount > 0
        await self._conn.commit()
        return updated

    async def delete_transaction(self, message_id: str) -> bool:
        """Soft-delete a transaction by setting deleted_at, rather than
        removing the row. Returns False if no (already non-deleted)
        transaction has this message_id (caller should 404).

        A hard DELETE on an email-derived row would be unrecoverable —
        processed_emails still marks the underlying email as processed, so a
        future sync would never refetch or recreate it. Soft-deleting means
        an accidental delete could still be undone by hand (UPDATE
        transactions SET deleted_at = NULL ...) instead of being gone for
        good."""
        async with self._conn.cursor() as cur:
            await cur.execute(
                "UPDATE transactions SET deleted_at = now() WHERE message_id = %s AND deleted_at IS NULL",
                (message_id,),
            )
            deleted = cur.rowcount > 0
        await self._conn.commit()
        return deleted

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
                WHERE extracted_at IS NOT NULL AND deleted_at IS NULL AND category IS NOT NULL
                ORDER BY category
                """
            )
            rows = await cur.fetchall()
        await self._conn.commit()
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
                WHERE extracted_at IS NOT NULL AND deleted_at IS NULL AND date IS NOT NULL
                ORDER BY month DESC
                """
            )
            rows = await cur.fetchall()
        await self._conn.commit()
        return [row[0] for row in rows]

    async def category_totals(self, date_from: date, date_to: date) -> list[dict]:
        """Return total spend per category within [date_from, date_to]
        (inclusive).

        Excludes is_transfer=true rows — fund movements aren't real spend."""
        query = """
            SELECT category, SUM(amount) AS total
            FROM transactions
            WHERE extracted_at IS NOT NULL AND deleted_at IS NULL AND is_transfer = false
              AND date >= %s AND date < %s
            GROUP BY category
            ORDER BY total DESC
        """
        async with self._conn.cursor() as cur:
            await cur.execute(query, (date_from, date_to + timedelta(days=1)))
            rows = await cur.fetchall()
        await self._conn.commit()

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
                WHERE extracted_at IS NOT NULL AND deleted_at IS NULL AND is_transfer = false
                  AND date >= %s AND date < %s
                GROUP BY day
                ORDER BY day
                """,
                (date_from, date_to + timedelta(days=1)),
            )
            rows = await cur.fetchall()
        await self._conn.commit()

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
                WHERE extracted_at IS NOT NULL AND deleted_at IS NULL AND is_transfer = false
                """,
                {
                    "from": date_from,
                    "to": date_to + timedelta(days=1),
                    "prev_from": previous_from,
                    "prev_to": previous_to_exclusive,
                },
            )
            row = await cur.fetchone()
        await self._conn.commit()

        return {
            "current_total": float(row[0]) if row[0] is not None else 0.0,
            "previous_total": float(row[1]) if row[1] is not None else 0.0,
        }

    async def category_period_comparison(self, date_from: date, date_to: date) -> list[dict]:
        """Return, per category, the total spend in [date_from, date_to]
        (inclusive) and in the immediately preceding period of the same
        length — the per-category breakdown of period_comparison().

        Includes a category if it has spend in either period (a category
        with only previous-period spend still needs to show a drop to
        zero). Excludes is_transfer=true rows."""
        duration = (date_to - date_from) + timedelta(days=1)
        previous_to_exclusive = date_from
        previous_from = date_from - duration

        async with self._conn.cursor() as cur:
            await cur.execute(
                """
                SELECT
                    category,
                    SUM(amount) FILTER (WHERE date >= %(from)s AND date < %(to)s) AS current_total,
                    SUM(amount) FILTER (WHERE date >= %(prev_from)s AND date < %(prev_to)s) AS previous_total
                FROM transactions
                WHERE extracted_at IS NOT NULL AND deleted_at IS NULL AND is_transfer = false AND category IS NOT NULL
                  AND date >= %(prev_from)s AND date < %(to)s
                GROUP BY category
                ORDER BY current_total DESC NULLS LAST
                """,
                {
                    "from": date_from,
                    "to": date_to + timedelta(days=1),
                    "prev_from": previous_from,
                    "prev_to": previous_to_exclusive,
                },
            )
            rows = await cur.fetchall()
        await self._conn.commit()

        return [
            {
                "category": row[0],
                "current_total": float(row[1]) if row[1] is not None else 0.0,
                "previous_total": float(row[2]) if row[2] is not None else 0.0,
            }
            for row in rows
        ]

    async def category_trend(self, date_from: date, date_to: date) -> list[dict]:
        """Return total spend per day per category within [date_from,
        date_to] (inclusive), for a multi-line trend chart (one line per
        category).

        Excludes is_transfer=true rows — fund movements aren't real spend."""
        async with self._conn.cursor() as cur:
            await cur.execute(
                """
                SELECT date_trunc('day', date) AS day, category, SUM(amount) AS total
                FROM transactions
                WHERE extracted_at IS NOT NULL AND deleted_at IS NULL AND is_transfer = false AND category IS NOT NULL
                  AND date >= %s AND date < %s
                GROUP BY day, category
                ORDER BY day
                """,
                (date_from, date_to + timedelta(days=1)),
            )
            rows = await cur.fetchall()
        await self._conn.commit()

        return [
            {"date": row[0].date().isoformat(), "category": row[1], "total": float(row[2])}
            for row in rows
        ]

    # ------------------------------------------------------------------
    # Q&A agent (M6) — executes SQL already checked by qa_agent.validate_sql
    # ------------------------------------------------------------------

    async def run_readonly_query(self, sql: str) -> list[dict]:
        """Execute a pre-validated read-only query and return rows as
        JSON-safe dicts. The caller (app.main) must have already run
        qa_agent.validate_sql() — this method trusts its input and does not
        re-check it."""

        def to_jsonable(value):
            if isinstance(value, (datetime, date)):
                return value.isoformat()
            if isinstance(value, Decimal):
                return float(value)
            return value

        async with self._conn.cursor() as cur:
            await cur.execute(sql)
            rows = await cur.fetchall()
            columns = [desc.name for desc in cur.description]
        await self._conn.commit()

        return [{col: to_jsonable(val) for col, val in zip(columns, row)} for row in rows]
