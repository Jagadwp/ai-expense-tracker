"""FastAPI entry point for the expense-tracker application."""

from contextlib import asynccontextmanager

import psycopg
from fastapi import FastAPI, HTTPException, Response, status
from fastapi.responses import RedirectResponse

from app import gmail_auth
from app.config import get_settings
from app.gmail_sync import GmailSyncer
from app.security import Encryptor
from app.store import NotFoundError, Store

settings = get_settings()

# Single-user MVP: every stored token belongs to this fixed user id (matches
# the oauth_tokens.user_id DEFAULT 'default' in the migration).
DEFAULT_USER_ID = "default"


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Open a single connection for startup checks; request-scoped connections
    # are added once the store layer needs them.
    app.state.db_conn = await psycopg.AsyncConnection.connect(settings.database_url)
    app.state.store = Store(app.state.db_conn)
    app.state.encryptor = Encryptor(settings.encryption_key)
    try:
        yield
    finally:
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
        token = await app.state.store.get_token(DEFAULT_USER_ID)
    except NotFoundError:
        raise HTTPException(status_code=400, detail="no Gmail account connected")

    token_json = app.state.encryptor.decrypt(token.encrypted_token)
    credentials = gmail_auth.credentials_from_token_json(token_json)

    if gmail_auth.refresh_if_expired(credentials):
        refreshed_token_json = credentials.to_json().encode("utf-8")
        encrypted_token = app.state.encryptor.encrypt(refreshed_token_json)
        await app.state.store.save_token(
            DEFAULT_USER_ID, encrypted_token, token.gmail_email
        )

    sync_log_id = await app.state.store.create_sync_log("manual")
    syncer = GmailSyncer(app.state.store, credentials)

    try:
        emails_fetched, emails_new, emails_skipped = await syncer.sync(newer_than)
    except Exception as exc:
        await app.state.store.finish_sync_log(
            sync_log_id,
            status="failed",
            emails_fetched=0,
            emails_new=0,
            emails_skipped=0,
            error_message=str(exc),
        )
        raise HTTPException(status_code=502, detail=f"sync failed: {exc}")

    await app.state.store.finish_sync_log(
        sync_log_id,
        status="success",
        emails_fetched=emails_fetched,
        emails_new=emails_new,
        emails_skipped=emails_skipped,
    )
    await app.state.store.touch_last_synced(DEFAULT_USER_ID)

    return {
        "sync_log_id": str(sync_log_id),
        "emails_fetched": emails_fetched,
        "emails_new": emails_new,
        "emails_skipped": emails_skipped,
    }
