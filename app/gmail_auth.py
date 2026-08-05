"""Gmail OAuth2 flow: consent URL, code exchange, and profile lookup.

Read-only access only (see FR-01) — the app never writes to Gmail beyond the
processed-label bookkeeping planned for a later milestone.
"""

import json

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build

from app.config import Settings

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]


def _build_flow(settings: Settings) -> Flow:
    return Flow.from_client_secrets_file(
        settings.google_credentials_path,
        scopes=SCOPES,
        redirect_uri=settings.google_redirect_url,
    )


def get_authorization_url(settings: Settings) -> str:
    """Build the Google consent-screen URL the user is redirected to.

    access_type="offline" is what makes Google issue a refresh token (not
    just a short-lived access token); prompt="consent" forces the consent
    screen every time so a refresh token is reissued even on reconnect.
    """
    flow = _build_flow(settings)
    auth_url, _state = flow.authorization_url(
        access_type="offline",
        prompt="consent",
        include_granted_scopes="true",
    )
    return auth_url


def exchange_code_for_credentials(settings: Settings, code: str) -> Credentials:
    """Exchange the authorization code from the callback for credentials
    (access token + refresh token)."""
    flow = _build_flow(settings)
    flow.fetch_token(code=code)
    return flow.credentials


def credentials_from_token_json(token_json: bytes) -> Credentials:
    """Rebuild Credentials from the JSON blob produced by
    credentials.to_json() (after decrypting it — see app.security)."""
    info = json.loads(token_json)
    return Credentials.from_authorized_user_info(info, scopes=SCOPES)


def refresh_if_expired(credentials: Credentials) -> bool:
    """Refresh the access token in place if it has expired.

    Returns True if a refresh happened (meaning the caller should
    re-encrypt and persist the updated credentials), False otherwise.
    """
    if credentials.expired and credentials.refresh_token:
        credentials.refresh(Request())
        return True
    return False


def get_gmail_email(credentials: Credentials) -> str:
    """Return the Gmail address the credentials belong to.

    Uses the Gmail API's own profile endpoint rather than the separate
    userinfo/OpenID endpoint, so no extra OAuth scope is required beyond
    gmail.readonly.
    """
    service = build("gmail", "v1", credentials=credentials)
    profile = service.users().getProfile(userId="me").execute()
    return profile["emailAddress"]
