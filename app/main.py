"""FastAPI entry point for the expense-tracker application."""

import asyncio
import logging
from contextlib import asynccontextmanager

from datetime import date
from typing import Literal

import psycopg
from anthropic import Anthropic
from fastapi import FastAPI, HTTPException, Query, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

from app import gmail_auth
from app.config import get_settings
from app.extract_runner import run_extraction
from app.imap_idle import ImapIdleListener
from app.qa_agent import UnsafeSqlError, compose_answer, generate_sql, validate_sql
from app.scheduler import create_scheduler
from app.security import Encryptor
from app.store import NotFoundError, Store
from app.sync_runner import DEFAULT_USER_ID, NoGmailConnected, run_sync

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)
settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Open a single connection for startup checks; request-scoped connections
    # are added once the store layer needs them.
    app.state.db_conn = await psycopg.AsyncConnection.connect(settings.database_url)
    app.state.store = Store(app.state.db_conn)
    app.state.encryptor = Encryptor(settings.encryption_key)
    app.state.anthropic = Anthropic(api_key=settings.anthropic_api_key)

    # Polled by the dashboard's "Sync now" indicator while a manual
    # sync/extract batch is in flight (see /api/sync-progress below).
    app.state.sync_progress = {"processed": 0, "total": 0}

    # Scheduled sync (US-02): background fallback, runs every 30 minutes
    # regardless of whether the IMAP IDLE listener is working.
    app.state.scheduler = create_scheduler(app.state.store, app.state.encryptor, app.state.anthropic)
    app.state.scheduler.start()

    # IMAP IDLE listener (US-04): real-time trigger, only started if IMAP
    # credentials are configured (they're optional until the user sets up
    # an app password).
    app.state.imap_listener = None
    if settings.gmail_imap_user and settings.gmail_imap_app_password:
        app.state.imap_listener = ImapIdleListener(
            settings, app.state.store, app.state.encryptor, app.state.anthropic, asyncio.get_running_loop()
        )
        app.state.imap_listener.start()
    else:
        logger.warning(
            "imap idle: GMAIL_IMAP_USER/GMAIL_IMAP_APP_PASSWORD not set, listener disabled"
        )

    try:
        yield
    finally:
        if app.state.imap_listener is not None:
            app.state.imap_listener.stop()
        app.state.scheduler.shutdown(wait=False)
        await app.state.db_conn.close()


app = FastAPI(title="AI Expense Tracker", lifespan=lifespan)

# Dev-mode Vite server runs on a different origin (localhost:5173) than
# FastAPI (localhost:8080); the browser enforces CORS between them.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["GET"],
    allow_headers=["*"],
)


@app.get("/health")
async def health(response: Response):
    try:
        async with app.state.db_conn.cursor() as cur:
            await cur.execute("SELECT 1")
            await cur.fetchone()
    except Exception:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {"status": "unhealthy", "db": "down"}

    return {"status": "ok", "db": "up"}


@app.get("/auth/google")
async def auth_google():
    """Redirect the user to the Google consent screen."""
    auth_url = gmail_auth.get_authorization_url(settings)
    return RedirectResponse(auth_url)


@app.get("/auth/google/callback")
async def auth_google_callback(code: str):
    """Exchange the authorization code for tokens, encrypt them, and store
    them for the single MVP user."""
    credentials = gmail_auth.exchange_code_for_credentials(settings, code)
    gmail_email = gmail_auth.get_gmail_email(credentials)

    token_json = credentials.to_json().encode("utf-8")
    encrypted_token = app.state.encryptor.encrypt(token_json)

    await app.state.store.save_token(DEFAULT_USER_ID, encrypted_token, gmail_email)

    return {"status": "connected", "gmail_email": gmail_email}


@app.get("/auth/google/status")
async def auth_google_status():
    """Report whether a Gmail account is currently connected."""
    try:
        token = await app.state.store.get_token(DEFAULT_USER_ID)
    except NotFoundError:
        return {"connected": False}

    return {
        "connected": True,
        "gmail_email": token.gmail_email,
        "connected_at": token.connected_at,
        "last_synced_at": token.last_synced_at,
    }


@app.delete("/auth/google")
async def auth_google_disconnect():
    """Disconnect the currently connected Gmail account."""
    try:
        await app.state.store.get_token(DEFAULT_USER_ID)
    except NotFoundError:
        raise HTTPException(status_code=404, detail="no Gmail account connected")

    await app.state.store.delete_token(DEFAULT_USER_ID)
    return {"status": "disconnected"}


@app.post("/api/sync")
async def sync(newer_than: str = "7d"):
    """Manually trigger a Gmail sync: fetch, dedup, and ingest new
    transaction emails for the connected account."""
    try:
        return await run_sync(app.state.store, app.state.encryptor, "manual", newer_than)
    except NoGmailConnected as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"sync failed: {exc}")


@app.post("/api/extract")
async def extract(limit: int | None = 50):
    """Run LLM extraction (M4) over raw transactions not yet extracted.

    Defaults to a limit of 50: this endpoint blocks the HTTP request for the
    whole batch (each email is a sequential LLM call, ~1-2s), so an unbounded
    call risks a client/proxy timeout on a large backlog. Pass a smaller
    limit for faster responses, or a larger one (or None) if you know the
    caller can wait.

    One email's failure is recorded in flagged_emails and does not stop the
    rest of the batch (FR-06).
    """

    def on_progress(processed: int, total: int) -> None:
        app.state.sync_progress = {"processed": processed, "total": total}

    try:
        return await run_extraction(app.state.store, app.state.anthropic, limit, on_progress=on_progress)
    finally:
        app.state.sync_progress = {"processed": 0, "total": 0}


@app.post("/api/sync-and-extract")
async def api_sync_and_extract(newer_than: str = "7d", limit: int = 50):
    """Dashboard "Sync now" action: fetch new transaction emails, then
    immediately run one bounded extraction batch over whatever is
    unextracted. Returns both summaries; `extraction.remaining_unextracted`
    tells the frontend whether to offer an "extract more" follow-up instead
    of looping automatically — every batch is a real LLM-API cost, so this
    endpoint never extracts an unbounded backlog on its own."""
    try:
        sync_result = await run_sync(app.state.store, app.state.encryptor, "manual", newer_than)
    except NoGmailConnected as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"sync failed: {exc}")

    def on_progress(processed: int, total: int) -> None:
        app.state.sync_progress = {"processed": processed, "total": total}

    try:
        extraction_result = await run_extraction(
            app.state.store, app.state.anthropic, limit, on_progress=on_progress
        )
    finally:
        app.state.sync_progress = {"processed": 0, "total": 0}

    return {"sync": sync_result, "extraction": extraction_result}


@app.get("/api/sync-progress")
async def api_sync_progress():
    """Poll target for the dashboard's live "Syncing X of Y" indicator while
    a manual sync/extract batch (above) is in flight. Reports {"processed":
    0, "total": 0} when nothing is running."""
    return app.state.sync_progress


SortColumn = Literal["date", "merchant", "category", "amount", "payment_method", "is_transfer"]
SortDir = Literal["asc", "desc"]


@app.get("/api/transactions")
async def api_transactions(
    date_from: date,
    date_to: date,
    category: str | None = None,
    sort_by: SortColumn = "date",
    sort_dir: SortDir = "desc",
    include_transfers: bool = True,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100_000),
):
    """List one page of extracted transactions within [date_from, date_to]
    for the dashboard (M5). Returns {"items": [...], "total": N}.

    page_size's upper bound is high enough to act as an "all rows" option
    from the frontend (a LIMIT larger than the matching row count is a
    cheap no-op in Postgres) without removing the bound entirely."""
    return await app.state.store.list_transactions(
        date_from=date_from,
        date_to=date_to,
        category=category,
        sort_by=sort_by,
        sort_dir=sort_dir,
        include_transfers=include_transfers,
        page=page,
        page_size=page_size,
    )


@app.get("/api/transactions/{message_id}")
async def api_transaction_detail(message_id: str):
    """Full record (raw email fields + extracted fields) for one
    transaction, for the dashboard's email-preview modal."""
    detail = await app.state.store.get_transaction_detail(message_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="transaction not found")
    return detail


class SetTransferRequest(BaseModel):
    is_transfer: bool


@app.patch("/api/transactions/{message_id}/is-transfer")
async def api_set_is_transfer(message_id: str, body: SetTransferRequest):
    """Manually flag (or unflag) a transaction as a fund transfer, from the
    dashboard's email-preview modal."""
    detail = await app.state.store.get_transaction_detail(message_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="transaction not found")
    await app.state.store.set_is_transfer(message_id, body.is_transfer)
    return {"status": "ok"}


class TransactionInput(BaseModel):
    date: date | None
    merchant: str | None
    amount: float | None
    currency: str = "IDR"
    category: str | None
    payment_method: str | None
    is_transfer: bool = False


@app.post("/api/transactions")
async def api_create_transaction(body: TransactionInput):
    """Add a transaction by hand from the dashboard (no underlying email).
    Immediately included in every aggregate (extracted_at is set right
    away)."""
    message_id = await app.state.store.create_manual_transaction(
        date=body.date,
        merchant=body.merchant,
        amount=body.amount,
        currency=body.currency,
        category=body.category,
        payment_method=body.payment_method,
        is_transfer=body.is_transfer,
    )
    return {"message_id": message_id}


@app.put("/api/transactions/{message_id}")
async def api_update_transaction(message_id: str, body: TransactionInput):
    """Edit a transaction's fields — allowed for both manual and
    email-derived rows, so a wrong LLM guess (merchant/amount/category/...)
    can be corrected by hand. The raw email fields are never editable
    through this route."""
    updated = await app.state.store.update_transaction(
        message_id,
        date=body.date,
        merchant=body.merchant,
        amount=body.amount,
        currency=body.currency,
        category=body.category,
        payment_method=body.payment_method,
        is_transfer=body.is_transfer,
    )
    if not updated:
        raise HTTPException(status_code=404, detail="transaction not found")
    return {"status": "ok"}


@app.delete("/api/transactions/{message_id}")
async def api_delete_transaction(message_id: str):
    """Delete a transaction. For an email-derived row, this does not undo
    the underlying email's dedup record — a future sync will not refetch or
    recreate it, so deleting one by mistake isn't recoverable from a
    re-sync."""
    deleted = await app.state.store.delete_transaction(message_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="transaction not found")
    return {"status": "ok"}


@app.get("/api/categories")
async def api_categories():
    """Distinct categories present in extracted transactions, for the
    dashboard's category filter."""
    return await app.state.store.list_categories()


@app.get("/api/available-months")
async def api_available_months():
    """Months ("YYYY-MM") that have at least one extracted transaction, for
    the dashboard's month picker."""
    return await app.state.store.list_available_months()


@app.get("/api/summary/category-totals")
async def api_category_totals(date_from: date, date_to: date):
    """Total spend per category within [date_from, date_to], excluding
    transfers."""
    return await app.state.store.category_totals(date_from=date_from, date_to=date_to)


@app.get("/api/summary/category-totals-today")
async def api_category_totals_today():
    """Total spend per category for today only, excluding transfers.

    Always today by the server's clock — independent of the dashboard's
    date-range filter, so it doesn't shift when the user picks a different
    range."""
    today = date.today()
    return await app.state.store.category_totals(date_from=today, date_to=today)


@app.get("/api/summary/trend")
async def api_spend_trend(date_from: date, date_to: date):
    """Total spend per day within [date_from, date_to], excluding
    transfers."""
    return await app.state.store.spend_trend(date_from=date_from, date_to=date_to)


@app.get("/api/summary/period-comparison")
async def api_period_comparison(date_from: date, date_to: date):
    """Total spend in [date_from, date_to] vs the immediately preceding
    period of the same length, excluding transfers."""
    return await app.state.store.period_comparison(date_from=date_from, date_to=date_to)


@app.get("/api/summary/category-period-comparison")
async def api_category_period_comparison(date_from: date, date_to: date):
    """Per-category breakdown of period-comparison: total spend in
    [date_from, date_to] vs the immediately preceding period of the same
    length, excluding transfers."""
    return await app.state.store.category_period_comparison(date_from=date_from, date_to=date_to)


@app.get("/api/summary/category-trend")
async def api_category_trend(date_from: date, date_to: date):
    """Total spend per day per category within [date_from, date_to], for a
    multi-line trend chart, excluding transfers."""
    return await app.state.store.category_trend(date_from=date_from, date_to=date_to)


class AskRequest(BaseModel):
    question: str


@app.post("/api/qa/ask")
async def api_qa_ask(body: AskRequest):
    """Ask a natural-language question about expense data (M6): Claude
    Sonnet 5 translates the question into SQL, the query is validated and
    executed read-only, and the result is composed into a plain-language
    answer (FR-11/FR-12/FR-13)."""
    result = generate_sql(app.state.anthropic, body.question)
    if not result.can_answer or not result.sql:
        return {"answer": "I can't answer that from the expense data I have.", "sql": None}

    try:
        sql = validate_sql(result.sql)
    except UnsafeSqlError as exc:
        logger.warning("qa agent generated unsafe SQL: %s (%s)", result.sql, exc)
        return {"answer": "I couldn't safely answer that question.", "sql": None}

    rows = await app.state.store.run_readonly_query(sql)
    answer = compose_answer(app.state.anthropic, body.question, rows)
    return {"answer": answer, "sql": sql}
