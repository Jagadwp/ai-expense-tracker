# AI Expense Tracker

An application that reads transaction notification emails from Gmail, extracts
expense data with an LLM, stores it in PostgreSQL, and (in later milestones)
surfaces it through a dashboard and a natural-language Q&A agent.

> Full product spec: [`document/PRD.md`](document/PRD.md) and
> [`document/DATABASE_SCHEMA.md`](document/DATABASE_SCHEMA.md) (not tracked in
> git — local planning docs).

## Current status

**Milestones M1 (Gmail OAuth) and M2 (email fetch + dedup) are implemented and
tested end-to-end against a real Gmail account.**

| Milestone | Status |
|---|---|
| M1 — Gmail OAuth (connect, encrypted token storage, disconnect) | ✅ Done |
| M2 — Email fetch, dedup, raw ingestion | ✅ Done |
| M3 — IMAP IDLE + scheduled sync | Not started |
| M4 — LLM extraction | Not started |
| M5 — Dashboard (Streamlit) | Not started |
| M6 — Q&A agent (text-to-SQL) | Not started |
| M7 — Alerts, deploy | Not started |

## What's built so far

### `app/config.py` — configuration
Loads `.env` once at startup via `pydantic-settings`. Required variables
(`DATABASE_URL`, `ENCRYPTION_KEY`, `SESSION_SECRET`) raise a clear error at
startup if missing, instead of failing silently later.

### `app/security.py` — token encryption
`Encryptor`: AES-256-GCM encrypt/decrypt, used to protect the Gmail OAuth
token before it's stored in the database. A random nonce is generated on
every call; a tampered ciphertext or wrong key fails to decrypt rather than
silently returning garbage.

### `app/store.py` — database access
All SQL lives here, grouped by table:
- `oauth_tokens` — `save_token`, `get_token`, `delete_token`, `touch_last_synced`
- `sender_filters` — `get_active_sender_filters`
- `processed_emails` (dedup) — `is_processed`, `mark_processed`
- `transactions` (raw fields) — `save_raw_transaction`
- `flagged_emails` (errors) — `flag_email`
- `sync_logs` — `create_sync_log`, `finish_sync_log`

### `app/gmail_auth.py` — Google OAuth2 flow
Builds the consent URL, exchanges the authorization code for credentials,
rebuilds credentials from a stored (decrypted) token, refreshes an expired
access token, and looks up the connected Gmail address.

### `app/gmail_sync.py` — email fetch and ingestion
`GmailSyncer.sync()`: reads active senders from the `sender_filters` table,
queries Gmail, and for each message checks dedup, decodes the body
(recursively, to handle nested multipart emails), and stores the raw fields.
A single email's failure is recorded in `flagged_emails` — it never stops the
rest of the sync.

### `app/main.py` — API routes

| Method & path | Purpose |
|---|---|
| `GET /health` | Server + database liveness check |
| `GET /auth/google` | Redirect to the Google consent screen |
| `GET /auth/google/callback` | Exchange code, encrypt, store the token |
| `GET /auth/google/status` | Report whether Gmail is connected |
| `DELETE /auth/google` | Disconnect the Gmail account |
| `POST /sync?newer_than=7d` | Manually trigger a sync |

### Database (`migrations/`)
- `001_epic1.sql` — `transactions`, `processed_emails`, `flagged_emails`,
  `oauth_tokens`, `sync_logs`
- `002_sender_filters.sql` — configurable sender allowlist (no CRUD API yet;
  rows are managed by hand via `psql`)

### Tests (`app/tests/`)
Unit tests for `security.py` and `store.py`, run against a real database
(not mocked).

## Setup

### Prerequisites
- Python 3.12+
- PostgreSQL running locally, with a database created (default expected name:
  `expense_tracker`)
- A Google Cloud project with the Gmail API enabled and an OAuth 2.0 Client
  ID (Web application) — see `document/PRD.md` for the full walkthrough

### 1. Create and activate a virtual environment
```bash
python3.12 -m venv venv
source venv/bin/activate
```

### 2. Install dependencies
```bash
pip install -r requirements.txt
```

### 3. Configure environment variables
```bash
cp .env.example .env
```
Fill in `DATABASE_URL`, and generate `ENCRYPTION_KEY` / `SESSION_SECRET` with:
```bash
openssl rand -base64 32
```

### 4. Place your Google OAuth credentials
Download the OAuth client's JSON from Google Cloud Console and save it as
`credentials.json` in the project root (already git-ignored). Its
`redirect_uris` must match `GOOGLE_REDIRECT_URL` in `.env`.

### 5. Apply the database migrations
```bash
psql "$DATABASE_URL" -f migrations/001_epic1.sql
psql "$DATABASE_URL" -f migrations/002_sender_filters.sql
```

### 6. Add at least one sender to `sender_filters`
```bash
psql "$DATABASE_URL" -c "
INSERT INTO sender_filters (email_address, label) VALUES
  ('noreply@ovo.co.id', 'OVO')
ON CONFLICT (email_address) DO NOTHING;
"
```

## Running the app

```bash
source venv/bin/activate
uvicorn app.main:app --reload --port 8080
```

Then:
1. Open `http://localhost:8080/auth/google` in a browser and complete the
   Google consent flow.
2. Trigger a sync: `curl -X POST "http://localhost:8080/sync?newer_than=90d"`
3. Check status: `curl http://localhost:8080/auth/google/status`

## Running tests

```bash
source venv/bin/activate
python -m pytest app/tests/ -v
```
