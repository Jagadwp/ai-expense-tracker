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
| M7 — Alerts, deploy | Deploy done (Railway); email alerts not started |

**M5 was originally built with Streamlit, then swapped to a Vue 3 SPA** after
a native crash in Streamlit's pyarrow dependency (`SIGSEGV` in `mimalloc`,
exit code 139) on filter interaction — see the v4.1 changelog in
`document/PRD.md`. A real SPA over a REST API also better demonstrates
full-stack capability than a data-app-style dashboard.

## To do

- **Retry flagged emails** — small UI/endpoint to unflag a failed
  `flagged_emails` row and re-queue it for sync/extraction, instead of the
  current manual-`psql` workaround. Needed because a failed sync or
  extraction (e.g. a dropped connection) is never retried automatically —
  the affected email is permanently excluded once flagged.
- **Flagged-emails review UI** — surface `flagged_emails` (low-confidence and
  error rows) in the dashboard instead of requiring direct DB access.
- **M6 eval set** — a fixed set of test questions/expected answers for the
  Q&A agent, to catch regressions in `qa_agent.py` prompts.
- **M7 — email alerts** — threshold-based spend alerts via Resend, still not
  built. (Deploy, the other half of M7, is done — see "Deployment" below.)

**Done, no longer tracked here:**
- Manual transaction entry (add/edit/delete, soft delete) — see
  "Dashboard (M5)" below.
- Deployed to production on Railway — see "Deployment (Railway)" below.
- Published the Google OAuth client to "In production" (fixes the ~7-day
  refresh-token expiry `invalid_grant` issue below) — not submitted for
  Google's verification review, which is fine for a single-user tool on the
  `gmail.readonly` sensitive (not restricted) scope; the cost is a one-time
  "unverified app" warning during consent.

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
`run_sync()`: the common logic behind the manual `/api/sync` route, the scheduled
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
**Claude Haiku 4.5** via `langchain-anthropic`'s `ChatAnthropic`, bound to
the `ExtractionResult` Pydantic schema via
`with_structured_output(..., method="json_schema")` — no thinking, no
`effort` (a high-volume, low-complexity task; Haiku 4.5 doesn't support
`effort` anyway). The system prompt is prompt-cached since it's identical
across the whole batch.

Ported from the raw `anthropic` SDK to `langchain-anthropic` as a
provider-abstraction learning exercise. `method="json_schema"` matters:
LangChain's default (`method="function_calling"`, forced tool calling) is
documented as unreliable when `thinking` is enabled — the Q&A agent below
uses `thinking`, so it needs this non-default method; extraction doesn't
use `thinking` at all, but uses the same method for consistency.

Both `category` and `payment_method` are fixed `Literal` enums (not free
text) — Pydantic turns them into an `enum` constraint in the JSON schema, so
Claude structurally cannot return a value outside the set, and the dashboard's
manual add/edit form uses the same fixed lists. This applies going forward
only; older `payment_method` values extracted before the enum existed
(`"BI Fast"`, `"blu"`, ...) are left as free text, not backfilled.

### `app/main.py` — API routes

| Method & path | Purpose |
|---|---|
| `GET /health` | Server + database liveness check |
| `GET /auth/google` | Redirect to the Google consent screen |
| `GET /auth/google/callback` | Exchange code, encrypt, store the token |
| `GET /auth/google/status` | Report whether Gmail is connected |
| `DELETE /auth/google` | Disconnect the Gmail account |
| `POST /api/sync?newer_than=7d` | Manually trigger a sync |
| `POST /api/extract?limit=N` | Run LLM extraction over unextracted transactions (default `limit=50`). Returns `remaining_unextracted` — how many are still unextracted after this batch |
| `POST /api/sync-and-extract?newer_than=7d&limit=50` | Dashboard "Sync now" action: run a sync, then one bounded extraction batch over whatever came in. Returns `{"sync": {...}, "extraction": {...}}` (same shapes as `/api/sync` and `/api/extract`) |
| `GET /api/sync-progress` | Poll target for the dashboard's live "Syncing X of Y" indicator while `/api/extract` or `/api/sync-and-extract` is in flight — `{"processed": N, "total": M}`, both `0` when idle |
| `GET /api/transactions?date_from=&date_to=` | One page of extracted transactions in range — `{"items": [...], "total": N}`. Filters: `category`, `include_transfers`; sortable by any column via `sort_by`/`sort_dir`; paginated via `page`/`page_size` (max 100000, used as an "all rows" sentinel) |
| `GET /api/transactions/{message_id}` | Full record (raw email fields + extracted fields) for one transaction, for the email-preview modal |
| `PATCH /api/transactions/{message_id}/is-transfer` | Manually flag/unflag a transaction as a fund transfer, from the email-preview modal |
| `POST /api/transactions` | Add a transaction by hand (no underlying email) — body: date, merchant, amount, currency, category, payment_method, is_transfer. Returns `{"message_id": "manual:<uuid>"}` |
| `PUT /api/transactions/{message_id}` | Edit a transaction's fields — allowed for both manual and email-derived rows, so a wrong LLM guess can be corrected by hand. Raw email fields are never editable |
| `DELETE /api/transactions/{message_id}` | Soft-delete a transaction (sets `deleted_at`, doesn't remove the row) — every read path excludes `deleted_at IS NOT NULL` rows |
| `GET /api/categories` | Distinct categories present in extracted transactions |
| `GET /api/available-months` | Months (`YYYY-MM`) with at least one extracted transaction, for the "by month" shortcut |
| `GET /api/summary/category-totals?date_from=&date_to=` | Total spend per category in range, excluding transfers |
| `GET /api/summary/category-totals-today` | Total spend per category for today only (server's clock), excluding transfers — independent of the dashboard's date-range filter |
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
and writes (`set_is_transfer`, `create_manual_transaction`,
`update_transaction`, `delete_transaction`) live on `Store` alongside the
rest of the app's database access, and are exposed over a REST API (see the
routes table below) instead of being queried directly from the dashboard
process. Every range query takes an explicit `date_from`/`date_to` range —
there is no month-string filter. All spend aggregates exclude
`is_transfer = true` and (soft-)deleted (`deleted_at IS NOT NULL`) rows.

`frontend/` (Vue 3 + Vite, plain CSS — light/minimalist theme) consumes that
API:
- A "Today's spend by category" card, pinned above everything else and
  computed from the server's current date (`GET
  /api/summary/category-totals-today`) — independent of the date-range
  filter below, so it never shifts when the range changes.
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
- A "Sync now" bar above the transaction table: pick a sync window
  (1d/7d/14d/30d/90d), run a sync + bounded extraction batch in one click,
  see a live "Syncing X of Y" progress indicator (polling
  `GET /api/sync-progress`), and an "Extract N more" follow-up if a backlog
  remains — see `POST /api/sync-and-extract` above.
- An "+ Add transaction" button opens a form modal (date/amount required,
  category and payment method as dropdowns backed by the same fixed lists
  `app/extraction.py` uses for LLM extraction).
- The transaction table is paginated and self-fetching (own `page`/
  `page_size`/`sort_by`/`sort_dir` state, independent of the rest of the
  dashboard): click any column header to sort by it (toggling direction on
  a second click), choose rows-per-page (10/20/50/100/All), and page with
  Prev/Next. A "No." column numbers rows sequentially across pages. Each row
  has an edit icon that opens the add/edit form pre-filled, and clicking the
  row itself opens a preview modal: the extracted fields (plus the message
  ID with a copy-to-clipboard button), the original raw email HTML rendered
  in a sandboxed `<iframe>` (no scripts, no same-origin access — the email
  body is untrusted content, and the iframe is skipped entirely for
  manually-added transactions or emails with no captured body), a
  "mark/unmark as transfer" action, and Edit/Delete actions. Any transaction
  — manual or email-derived — can be edited (correcting a wrong LLM guess)
  or deleted (soft delete; the raw email fields are never editable). All of
  these refresh both the table and the rest of the dashboard.

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

Both calls use adaptive thinking and `effort: "medium"` (FR-18), via
`langchain-anthropic`'s `ChatAnthropic` (ported from the raw `anthropic` SDK
alongside `app/extraction.py` above). One quirk found by this port and
fixed: when adaptive thinking actually engages (not the common no-op case),
`ChatAnthropic`'s response content becomes a list of blocks (a "thinking"
block plus a "text" block) instead of a plain string — `compose_answer()`
checks for this and extracts just the text block, rather than assuming
`response.content` is always a `str`.

The frontend's `QaChat.vue` is a simple chat card (question in, answer + a
collapsible "SQL used" block out) — the exchange history lives only in
browser memory, nothing is persisted server-side.

### Database (`migrations/`)
- `001_epic1.sql` — `transactions`, `processed_emails`, `flagged_emails`,
  `oauth_tokens`, `sync_logs`
- `002_sender_filters.sql` — configurable sender allowlist (no CRUD API yet;
  rows are managed by hand via `psql`)
- `003_add_is_transfer.sql` — `transactions.is_transfer` boolean flag
- `004_add_is_manual.sql` — `transactions.is_manual` boolean flag, for
  transactions added by hand from the dashboard
- `005_soft_delete_transactions.sql` — `transactions.deleted_at`, for
  soft-deleting a transaction from the dashboard

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
psql "$DATABASE_URL" -f migrations/004_add_is_manual.sql
psql "$DATABASE_URL" -f migrations/005_soft_delete_transactions.sql
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
2. Trigger a sync: `curl -X POST "http://localhost:8080/api/sync?newer_than=90d"`
3. Check status: `curl http://localhost:8080/auth/google/status`
4. Extract transaction data: `curl -X POST "http://localhost:8080/api/extract?limit=50"`

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

## Deployment (Railway)

Deployed as a **single Railway service** — one Docker image, backend and
frontend together — plus a Railway-managed PostgreSQL service in the same
project.

- **`Dockerfile`** (multi-stage): a Node stage runs `npm ci && npm run build`
  to produce `frontend/dist`, then a Python stage copies that build into the
  image alongside the FastAPI app.
- **`app/main.py`** mounts `frontend/dist` as static files (`StaticFiles`,
  `html=True`) at `/`, added *after* every API route — so it never shadows
  `/api/*`, `/auth/*`, or `/health`. This means one domain, one process, and
  no production CORS configuration (frontend and API share an origin; the
  CORS middleware in the code is dev-only, for Vite's `localhost:5173`).
- **`railway.json`** pins the build to the Dockerfile explicitly — Railway's
  default auto-detect builder ("Railpack") saw a Python project and picked
  its own start command, ignoring the Dockerfile entirely without this.
- **`GOOGLE_CREDENTIALS_JSON`** env var: Railway has no file-upload
  mechanism, so `credentials.json`'s content can be set as this env var
  instead, and `app/main.py`'s lifespan writes it to
  `GOOGLE_CREDENTIALS_PATH` at startup before anything reads the file.
  Local dev is unaffected — the file is still used directly, and this env
  var should stay unset locally.
- **Environment variables** needed on the app service: `DATABASE_URL`
  (reference the Postgres service's own variable, don't hardcode it),
  `ANTHROPIC_API_KEY`, `ENCRYPTION_KEY`, `SESSION_SECRET` (generate fresh
  values for production, don't reuse local ones), `GOOGLE_REDIRECT_URL`
  (the production domain's `/auth/google/callback`), `GOOGLE_CREDENTIALS_JSON`,
  and optionally `GMAIL_IMAP_USER`/`GMAIL_IMAP_APP_PASSWORD`.
- **Google Cloud Console**: the production callback URL must be added to
  the OAuth client's "Authorized redirect URIs" (in addition to, not instead
  of, the `localhost` one used for dev), or auth fails with
  `Error 400: redirect_uri_mismatch`.
- **Migrations**: not run automatically on deploy. After provisioning the
  Postgres service, run `make migrate` once from a local machine against its
  **public** connection string (enable the service's TCP Proxy under
  Settings → Networking to get one — the default `*.railway.internal`
  hostname only resolves inside Railway's private network, not from a local
  machine).
- **Google OAuth publishing status**: published to "In production" (not
  submitted for Google's verification review) once real usage started,
  since "Testing" status caps refresh tokens at ~7 days
  (`invalid_grant: Token has been expired or revoked.`) — see the "To do"
  section above for why verification itself isn't needed at this scale.
