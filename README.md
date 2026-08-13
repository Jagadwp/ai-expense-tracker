# AI Expense Tracker

An application that reads transaction notification emails from Gmail, extracts
expense data with an LLM, stores it in PostgreSQL, and (in later milestones)
surfaces it through a dashboard and a natural-language Q&A agent.

> Full product spec: [`document/PRD.md`](document/PRD.md) and
> [`document/DATABASE_SCHEMA.md`](document/DATABASE_SCHEMA.md).

## Current status

**Milestones M1 through M6 are implemented and tested end-to-end against a
real Gmail account.**

| Milestone | Status |
|---|---|
| M1 — Gmail OAuth (connect, encrypted token storage, disconnect) | ✅ Done |
| M2 — Email fetch, dedup, raw ingestion | ✅ Done |
| M3 — IMAP IDLE + scheduled sync | ✅ Done |
| M4 — LLM extraction (Claude Haiku 4.5) | ✅ Done |
| M5 — Dashboard (Vue SPA + REST API) | ✅ Done |
| M6 — Q&A agent (text-to-SQL, Claude Sonnet 5) | Agent working; eval set not built yet |
| M7 — Alerts, deploy | Not started |

**M5 was originally built with Streamlit, then swapped to a Vue 3 SPA** after
a native crash in Streamlit's pyarrow dependency (`SIGSEGV` in `mimalloc`,
exit code 139) on filter interaction — see the v4.1 changelog in
`document/PRD.md`. A real SPA over a REST API also better demonstrates
full-stack capability than a data-app-style dashboard.

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
- `transactions` (extraction, M4) — `get_unextracted_transactions`,
  `apply_extraction`, `set_low_confidence`, `delete_non_transaction`
- `flagged_emails` (errors / review queue) — `flag_email`
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

### `app/sync_runner.py` — shared sync orchestration
`run_sync()`: the common logic behind the manual `/sync` route, the scheduled
job, and the IMAP IDLE trigger — get the stored token, refresh it if expired,
run `GmailSyncer`, and record the result to `sync_logs`.

### `app/scheduler.py` — 30-minute scheduled sync (M3)
`AsyncIOScheduler` job that runs the same sync pipeline every 30 minutes, as a
fallback in case the real-time IMAP listener misses something or its
connection drops.

### `app/imap_idle.py` — real-time new-email detection (M3)
`ImapIdleListener`: runs a blocking IMAP IDLE loop in a background thread
(since it can't run on the app's asyncio event loop), and triggers a sync via
`asyncio.run_coroutine_threadsafe` whenever new mail arrives. Auto-reconnects
on any connection error.

### `app/extraction.py` — LLM extraction (M4)
`extract_transaction()`: sends one email's subject/sender/body to
**Claude Haiku 4.5** via `client.messages.parse()` with a Pydantic schema
(`ExtractionResult`) for structured output — no thinking, no `effort` (a
high-volume, low-complexity task; Haiku 4.5 doesn't support `effort` anyway).
The system prompt is prompt-cached since it's identical across the whole
batch.

### `app/main.py` — API routes

| Method & path | Purpose |
|---|---|
| `GET /health` | Server + database liveness check |
| `GET /auth/google` | Redirect to the Google consent screen |
| `GET /auth/google/callback` | Exchange code, encrypt, store the token |
| `GET /auth/google/status` | Report whether Gmail is connected |
| `DELETE /auth/google` | Disconnect the Gmail account |
| `POST /sync?newer_than=7d` | Manually trigger a sync |
| `POST /extract?limit=N` | Run LLM extraction over unextracted transactions (default `limit=50`) |
| `GET /api/transactions?date_from=&date_to=` | One page of extracted transactions in range — `{"items": [...], "total": N}`. Filters: `category`, `include_transfers`; sortable by any column via `sort_by`/`sort_dir`; paginated via `page`/`page_size` (max 100000, used as an "all rows" sentinel) |
| `GET /api/transactions/{message_id}` | Full record (raw email fields + extracted fields) for one transaction, for the email-preview modal |
| `PATCH /api/transactions/{message_id}/is-transfer` | Manually flag/unflag a transaction as a fund transfer, from the email-preview modal |
| `GET /api/categories` | Distinct categories present in extracted transactions |
| `GET /api/available-months` | Months (`YYYY-MM`) with at least one extracted transaction, for the "by month" shortcut |
| `GET /api/summary/category-totals?date_from=&date_to=` | Total spend per category in range, excluding transfers |
| `GET /api/summary/trend?date_from=&date_to=` | Total spend per day in range, excluding transfers |
| `GET /api/summary/period-comparison?date_from=&date_to=` | Total spend in range vs the immediately preceding period of the same length, excluding transfers |
| `GET /api/summary/category-period-comparison?date_from=&date_to=` | Per-category breakdown of `period-comparison`, excluding transfers |
| `GET /api/summary/category-trend?date_from=&date_to=` | Total spend per day per category in range, for the multi-line trend chart, excluding transfers |
| `POST /api/qa/ask` | Ask a natural-language question about expense data (M6, text-to-SQL) — body `{"question": "..."}`, returns `{"answer": "...", "sql": "..."}` |

The FastAPI `lifespan` also starts the scheduler and the IMAP IDLE listener,
so a single `uvicorn app.main:app` process runs the HTTP server, the
30-minute scheduled sync, and the real-time listener together — no separate
worker process needed.

### Extraction decision logic (M4)
For each unextracted email, Claude returns `is_transaction`, the extracted
fields, and a `confidence` score:
- `is_transaction: false` (e.g. a promo email) → the raw row is deleted
  (FR-09) — it was never a real transaction.
- `confidence` below `0.7` → only the `confidence` column is written; the
  other fields stay `NULL` and the row is recorded in `flagged_emails` for
  manual review. This is deliberately fail-safe: a low-confidence guess never
  reaches a spend total until a human confirms it.
- `confidence` ≥ `0.7` → all extracted fields are written and `extracted_at`
  is set.

To manually approve a flagged, low-confidence transaction after reviewing
`flagged_emails.raw_body`:
```sql
UPDATE transactions
SET date = '...', merchant = '...', amount = ..., category = '...',
    payment_method = '...', confidence = 1.000, extracted_at = now()
WHERE message_id = '...';

DELETE FROM flagged_emails WHERE message_id = '...';
```

**`is_transfer` (added after the initial M4 pass):** bank/e-wallet emails
include fund movements (e.g. transferring salary into savings) that are not
real expenses. `transactions.is_transfer` is a separate boolean from
`category` — Claude sets it during extraction for transfers to personal or
own-account names with no indication of a purchase — and the dashboard
excludes `is_transfer = true` rows from spend totals while still listing
them for audit.

### Dashboard (M5) — Vue SPA + REST API
Read-only queries (`list_transactions`, `list_available_months`,
`category_totals`, `spend_trend`, `period_comparison`,
`category_period_comparison`, `category_trend`, `get_transaction_detail`)
and one write (`set_is_transfer`) live on `Store` alongside the rest of the
app's database access, and are exposed over a REST API (see the routes
table below) instead of being queried directly from the dashboard process.
Every range query takes an explicit `date_from`/`date_to` range — there is
no month-string filter. All spend aggregates exclude `is_transfer = true`
rows.

`frontend/` (Vue 3 + Vite, plain CSS — light/minimalist theme) consumes that
API:
- A date-range picker: native `<input type="date">` from/to fields, quick
  presets (7D/1M/3M/6M/1Y), and a "by month" shortcut scoped to months that
  actually have data — picking a month snaps the range to that full
  calendar month and highlights the 1M preset. Default range on load:
  month-to-date (the 1st of the current month through today).
- A category filter, scoped to the transaction table only.
- A period-over-period metric (selected range vs. the immediately preceding
  range of equal length), broken out overall and per category, a
  category-breakdown donut chart, a daily spend-trend line chart, and a
  daily spend-trend line chart per category (one line per category) — all
  recompute whenever the date range changes.
- The transaction table is paginated and self-fetching (own `page`/
  `page_size`/`sort_by`/`sort_dir` state, independent of the rest of the
  dashboard): click any column header to sort by it (toggling direction on
  a second click), choose rows-per-page (10/20/50/100/All), and page with
  Prev/Next. Each row shows the message ID with a copy-to-clipboard button.
  Clicking a row opens an email-preview modal: the extracted fields on the
  left, the original raw email HTML rendered in a sandboxed `<iframe>` (no
  scripts, no same-origin access — the email body is untrusted content) on
  the right, and a "mark/unmark as transfer" action that PATCHes
  `is_transfer` and refreshes both the table and the rest of the dashboard
  (every spend aggregate depends on that flag).

### `app/qa_agent.py` — Q&A agent (M6, text-to-SQL)
`POST /api/qa/ask` lets the dashboard ask a natural-language question about
expense data. Two separate Claude Sonnet 5 calls, not one agentic loop:
1. `generate_sql()` — given a fixed schema description (only the columns
   relevant to spend analysis: `message_id`, `date`, `merchant`, `amount`,
   `category`, `payment_method`, `is_transfer`, `confidence`,
   `extracted_at` — never the raw email fields or any other table) and the
   question, Claude returns
   structured output: either a SQL `SELECT` or `can_answer: false` if the
   question is out of scope. It never executes anything itself.
2. `validate_sql()` — defense-in-depth re-check of the returned SQL before
   execution, independent of the prompt instructions: must be a single
   `SELECT`, no forbidden keywords (`INSERT`/`UPDATE`/`DELETE`/`DROP`/…), must
   reference `transactions` and no other known table, and gets a `LIMIT 200`
   appended if missing.
3. `Store.run_readonly_query()` executes the validated SQL and returns
   JSON-safe rows (`Decimal` → `float`, dates → ISO strings).
4. `compose_answer()` — a second Claude Sonnet 5 call turns the question +
   raw rows into a one- or two-sentence natural-language reply; told
   explicitly to say there's no data rather than guess when rows are empty.

Both calls use adaptive thinking and `effort: "medium"` (FR-18). The
frontend's `QaChat.vue` is a simple chat card (question in, answer + a
collapsible "SQL used" block out) — the exchange history lives only in
browser memory, nothing is persisted server-side.

### Database (`migrations/`)
- `001_epic1.sql` — `transactions`, `processed_emails`, `flagged_emails`,
  `oauth_tokens`, `sync_logs`
- `002_sender_filters.sql` — configurable sender allowlist (no CRUD API yet;
  rows are managed by hand via `psql`)
- `003_add_is_transfer.sql` — `transactions.is_transfer` boolean flag

### Tests (`app/tests/`)
Unit tests for `security.py` and `store.py`, run against a real database
(not mocked).

## Setup

### Prerequisites
- Python 3.12+
- Node.js 20+ (for the `frontend/` Vue app)
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
Also set `ANTHROPIC_API_KEY` (from [console.anthropic.com](https://console.anthropic.com))
for extraction, and — optionally, for the IMAP IDLE listener —
`GMAIL_IMAP_USER` and `GMAIL_IMAP_APP_PASSWORD` (a Google 2FA
[app password](https://myaccount.google.com/apppasswords), not your normal
password). The listener is skipped with a warning if these are unset.

### 4. Place your Google OAuth credentials
Download the OAuth client's JSON from Google Cloud Console and save it as
`credentials.json` in the project root (already git-ignored). Its
`redirect_uris` must match `GOOGLE_REDIRECT_URL` in `.env`.

### 5. Apply the database migrations
```bash
psql "$DATABASE_URL" -f migrations/001_epic1.sql
psql "$DATABASE_URL" -f migrations/002_sender_filters.sql
psql "$DATABASE_URL" -f migrations/003_add_is_transfer.sql
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

Shortcut: `make dev` runs the API and the frontend together (`Ctrl+C` stops
both). See the `Makefile` for other shortcuts (`make install`, `make api`,
`make frontend`, `make migrate`, `make test`, `make typecheck`,
`make genkey`).

```bash
source venv/bin/activate
uvicorn app.main:app --reload --port 8080
```

Then:
1. Open `http://localhost:8080/auth/google` in a browser and complete the
   Google consent flow.
2. Trigger a sync: `curl -X POST "http://localhost:8080/sync?newer_than=90d"`
3. Check status: `curl http://localhost:8080/auth/google/status`
4. Extract transaction data: `curl -X POST "http://localhost:8080/extract?limit=50"`

## Running the dashboard

The dashboard is a separate process from the API server — run it alongside
`uvicorn`, not instead of it:
```bash
cd frontend
npm install
npm run dev
```
Open the URL Vite prints (default `http://localhost:5173`). The dev server
proxies `/api` requests to the FastAPI backend on `http://localhost:8080`
(see `frontend/vite.config.ts`), so `uvicorn` must be running too.

## Running tests

```bash
source venv/bin/activate
python -m pytest app/tests/ -v
```
