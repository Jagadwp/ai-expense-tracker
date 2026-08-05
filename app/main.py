"""FastAPI entry point for the expense-tracker application."""

import asyncio
import logging
from contextlib import asynccontextmanager

from datetime import date

import psycopg
from anthropic import Anthropic
from fastapi import FastAPI, HTTPException, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse

from app import gmail_auth
from app.config import get_settings
from app.extraction import CONFIDENCE_THRESHOLD, extract_transaction
from app.imap_idle import ImapIdleListener
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

    # Scheduled sync (US-02): background fallback, runs every 30 minutes
    # regardless of whether the IMAP IDLE listener is working.
    app.state.scheduler = create_scheduler(app.state.store, app.state.encryptor)
    app.state.scheduler.start()

    # IMAP IDLE listener (US-04): real-time trigger, only started if IMAP
    # credentials are configured (they're optional until the user sets up
    # an app password).
    app.state.imap_listener = None
    if settings.gmail_imap_user and settings.gmail_imap_app_password:
        app.state.imap_listener = ImapIdleListener(
            settings, app.state.store, app.state.encryptor, asyncio.get_running_loop()
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


app = FastAPI(title="expense-tracker-ai", lifespan=lifespan)

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


@app.post("/sync")
async def sync(newer_than: str = "7d"):
    """Manually trigger a Gmail sync: fetch, dedup, and ingest new
    transaction emails for the connected account."""
    try:
        return await run_sync(app.state.store, app.state.encryptor, "manual", newer_than)
    except NoGmailConnected as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"sync failed: {exc}")


@app.post("/extract")
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
    candidates = await app.state.store.get_unextracted_transactions(limit=limit)

    extracted = 0
    skipped_non_transaction = 0
    flagged_low_confidence = 0
    failed = 0

    for tx in candidates:
        try:
            result = extract_transaction(
                app.state.anthropic, tx.raw_subject, tx.raw_from, tx.raw_body
            )

            if not result.is_transaction:
                await app.state.store.delete_non_transaction(tx.message_id)
                skipped_non_transaction += 1
            elif result.confidence < CONFIDENCE_THRESHOLD:
                await app.state.store.set_low_confidence(tx.message_id, result.confidence)
                await app.state.store.flag_email(
                    message_id=tx.message_id,
                    raw_body=tx.raw_body,
                    error_message=f"low confidence: {result.model_dump_json()}",
                    flagged_reason="low_confidence",
                )
                flagged_low_confidence += 1
            else:
                await app.state.store.apply_extraction(
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
            # A failed query leaves the shared connection's transaction
            # aborted until rolled back — without this, every subsequent
            # query on this connection (including the flag_email below,
            # and every later request) would fail too.
            await app.state.db_conn.rollback()
            await app.state.store.flag_email(
                message_id=tx.message_id,
                raw_body=tx.raw_body,
                error_message=str(exc),
                flagged_reason="extraction_error",
            )
            failed += 1

    return {
        "candidates": len(candidates),
        "extracted": extracted,
        "skipped_non_transaction": skipped_non_transaction,
        "flagged_low_confidence": flagged_low_confidence,
        "failed": failed,
    }


@app.get("/api/transactions")
async def api_transactions(
    date_from: date,
    date_to: date,
    category: str | None = None,
    sort_by: str = "date",
    include_transfers: bool = True,
):
    """List extracted transactions within [date_from, date_to] for the
    dashboard (M5)."""
    return await app.state.store.list_transactions(
        date_from=date_from,
        date_to=date_to,
        category=category,
        sort_by=sort_by,
        include_transfers=include_transfers,
    )


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
