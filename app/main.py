"""FastAPI entry point for the expense-tracker application."""

import asyncio
import logging
from contextlib import asynccontextmanager

import psycopg
from fastapi import FastAPI, HTTPException, Response, status
from fastapi.responses import RedirectResponse

from app import gmail_auth
from app.config import get_settings
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
