# PRD — AI Expense Tracker

- **Version:** 4.7
- **Author:** Jagad Wijaya Purnomo
- **Status:** Active — living document
- **Last updated:** 2026-08-21

> Changelog from v4.6: deployed to production on **Railway** (M7, partial —
> alerts still not built). Single service: a multi-stage `Dockerfile` builds
> the Vue dashboard and copies it into the FastAPI image, which serves it as
> static files (mounted after all API routes, so nothing shadows `/api/*` or
> `/auth/*`) — one deploy, one domain, no production CORS config needed since
> frontend and API share an origin. Google OAuth credentials can now also
> come from a `GOOGLE_CREDENTIALS_JSON` env var (written to
> `credentials.json` at startup) since Railway has no file-upload mechanism;
> local dev is unaffected. The Google OAuth client itself was published to
> "In production" (no refresh-token expiry) but not submitted for Google's
> verification review — acceptable for a single-user tool using only the
> sensitive (not restricted) `gmail.readonly` scope; the cost is a one-time
> "unverified app" warning during consent, not a functional block.

> Changelog from v4.5: extraction (`app/extraction.py`) and the Q&A agent
> (`app/qa_agent.py`) ported from the raw `anthropic` SDK to
> `langchain-anthropic`, as a provider-abstraction learning exercise (see
> `experiment/langchain` branch history). Verified empirically rather than
> assumed: structured output survives the port only via
> `with_structured_output(..., method="json_schema")` — LangChain's default
> `method="function_calling"` is documented as unreliable when `thinking` is
> enabled; `thinking`, `output_config.effort`, and prompt caching
> (`cache_control`) all still work. Fixed a real bug surfaced by this
> migration: when adaptive thinking actually engages, `ChatAnthropic`'s
> response content becomes a list of blocks (reasoning + text) instead of a
> plain string — `compose_answer()` now handles both shapes.

> Changelog from v4.4: added a "Today's spend by category" dashboard card,
> pinned above the rest of the dashboard and computed from the server's
> current date (`GET /api/summary/category-totals-today`) — independent of
> the date-range filter, so it never shifts when the user changes the range.
> Also reworked the transaction table/preview UI: the message ID and its
> copy button moved from the table into the preview modal, the table's ID
> column became a sequential "No." column, and the preview modal skips the
> raw-email `<iframe>` (and shrinks to a single column) when there's no
> email body to show — manual transactions or emails with no captured body.

> Changelog from v4.3: `payment_method` is now a fixed enum (Cash, QRIS,
> Debit Card, Credit Card, Bank Transfer, Virtual Account, GoPay, OVO, Dana,
> ShopeePay, LinkAja, Other) instead of free text, both for LLM extraction
> (FR-08) and the dashboard's manual add/edit form — same fixed vocabulary on
> both paths instead of near-duplicate free-text values ("QRIS" vs "Bank
> Transfer" vs "BI Fast" vs "BI-FAST"). Applies going forward only; existing
> free-text values in the database are left as-is, not backfilled.

> Changelog from v4.2: added manual transaction CRUD to the dashboard — an
> "Add transaction" modal, an edit icon directly in the transaction table row
> (no need to open the preview modal first), and delete from the
> preview modal. Editing is allowed on any transaction (manual or
> email-derived), so a wrong LLM guess can be corrected by hand; the raw
> email fields stay read-only always. Delete is a **soft delete**
> (`transactions.deleted_at`) rather than a hard `DELETE` — a hard delete on
> an email-derived row would be unrecoverable, since `processed_emails`
> already marks the underlying email as processed and a re-sync would never
> bring it back. Every read path (dashboard queries, the Q&A agent) excludes
> soft-deleted rows.

> Changelog from v4.1: added a manual **"Sync now"** dashboard action
> (`POST /api/sync-and-extract`) that runs a sync then one bounded
> extraction batch in a single request, with a live "Syncing X of Y" polling
> indicator. The scheduled sync (FR-04) and IMAP IDLE trigger (FR-05) now
> also run a small, capped extraction batch (limit 10) right after syncing,
> so the dashboard reflects finished transactions between visits instead of
> raw, unextracted ones — capped low since background runs are unattended
> and every extraction call is a real LLM-API cost.

> Changelog from v3.0: stack pivoted from Go to **Python (FastAPI + Streamlit)** —
> target market is entry-level AI/remote work (Upwork), where Python dominates
> and Go is a poor keyword/skill match. Milestone order changed to **de-risk
> Gmail ingestion first** (OAuth + IMAP IDLE + scheduler are the highest-
> uncertainty parts and unlock real email data for extraction design and
> marketing) before building AI extraction, dashboard, and Q&A. LLM model
> choices pinned to specific model IDs with cost/effort settings.

> Changelog from v4.0: dashboard frontend swapped from **Streamlit to Vue 3 +
> Vite**, calling FastAPI over a new REST API instead of querying the database
> directly from the dashboard process. Trigger: a Streamlit/pyarrow native
> crash (`SIGSEGV` in `mimalloc`, exit code 139) on filter interaction proved
> hard to fully de-risk. A real SPA also better demonstrates full-stack
> capability for freelance clients than a data-app-style dashboard, and Vue is
> a stack the author is already proficient in (backend is Go + Vue
> professionally).

---

## 1. Overview

### 1.1 Problem statement
Tracking personal spending by hand is tedious — receipts and transaction
notifications are scattered across email, manual entry is a chore, and there is
no automated, actionable insight.

### 1.2 Solution
An application that automatically reads transaction notification emails from
Gmail, extracts the expense data using an LLM, stores it in a database, and
surfaces insights that can be queried in natural language via chat.

### 1.3 Project goals
This is a portfolio project built to win freelance work (Upwork and similar
platforms), demonstrating:
- End-to-end AI pipeline (email ingestion → LLM extraction → structured storage)
- Agentic AI (conversational Q&A via a text-to-SQL agent)
- Production-grade backend (Python, PostgreSQL, OAuth2, financial-data security)
- A real, working integration with real email data (not just a synthetic demo)

### 1.4 Target user
An individual who wants automated expense tracking from their Gmail inbox with no
manual entry. For demos: a dedicated account with real (or anonymised real)
transaction email data, to support marketing/portfolio use.

---

## 2. Scope

### 2.1 In scope (MVP)
- Gmail authentication via OAuth2 (read-only)
- Real-time new-email detection via IMAP IDLE
- Scheduled synchronization of transaction emails (every 30 minutes)
- Transaction extraction from email bodies using an LLM
- Storage in PostgreSQL with deduplication
- Interactive dashboard (Vue SPA over a REST API): transaction list, summary charts, filters
- Conversational Q&A over expense data via a text-to-SQL agent
- Email alerts when spending approaches/exceeds a limit
- A small eval set to measure extraction accuracy

### 2.2 Out of scope (MVP)
- Multi-user / SaaS (single personal account only)
- Bank statement / CSV import (possible later)
- Direct bank / open-banking API integration
- Native mobile app
- Model fine-tuning
- Email providers other than Gmail
- Multi-currency (IDR only for the MVP)

---

## 3. User stories

### Epic 1 — Email ingestion (built first — de-risks the hardest integration)
- **US-01 (P0)** Connect a Gmail account via OAuth2 so the app can read transaction
  emails. *Acceptance:* consent flow works, token stored encrypted, user can disconnect.
- **US-02 (P0)** Automatically pull transaction emails on a schedule. *Acceptance:*
  sync runs every 30 minutes, success/failure logged, non-transaction emails ignored.
- **US-03 (P0)** Do not reprocess already-handled emails. *Acceptance:* dedup by
  `message_id`, idempotent across repeated syncs.
- **US-04 (P0)** Detect new transaction emails in real time. *Acceptance:* an IMAP
  IDLE listener triggers processing on arrival, complementing the scheduled sync.

### Epic 2 — AI extraction (built second — designed against real email data from Epic 1)
- **US-05 (P0)** Extract transaction data automatically from the email body.
  *Acceptance:* extracted fields = date, merchant, amount, currency, category,
  payment method; ≥ 85% accuracy on the eval set.
- **US-06 (P1)** Record emails that fail extraction for investigation. *Acceptance:*
  failed extractions stored in a separate table with the email body and error message.

### Epic 3 — Dashboard & insight
- **US-07 (P0)** View transactions with date-range and category filters. *Acceptance:*
  transaction table, filter by an arbitrary date range (quick presets — 7D/1M/3M/6M/1Y
  — plus a "by month" shortcut scoped to months with data) and/or category, sort by
  date/amount. Each row shows its message ID (with a copy button) and opens an
  email-preview modal (original raw email + extracted fields) on click.
- **US-07b (P1)** Correct a mis-classified transfer without editing the database
  by hand. *Acceptance:* the email-preview modal has a "mark/unmark as transfer"
  action; toggling it updates `transactions.is_transfer` and refreshes every
  spend aggregate on the dashboard.
- **US-08 (P0)** See spending summaries as charts that follow the selected date
  range. *Acceptance:* total per category (donut), daily spend trend (line),
  selected period vs the immediately preceding period of equal length — both
  overall and broken out per category, plus a per-category daily trend
  (multi-line) — all recomputed when the range changes; default range is the
  last month.
- **US-09 (P0)** Ask questions about expenses in natural language. *Acceptance:*
  text-to-SQL agent answers questions like "how much did I spend on food last
  month?"; answers "I don't know" when data is absent.

### Epic 4 — Alert
- **US-10 (P1)** Set spending limits per category. *Acceptance:* per-category limit
  (e.g. food Rp 2M/month); email notification at 80% and 100% of the limit.
- **US-11 (P1)** Alert emails include a current spending summary. *Acceptance:* email
  contains category, total spent, limit, remaining; sent via Resend; not re-sent
  within 24 hours for the same alert.

---

## 4. Functional requirements

### 4.1 Email ingestion
- **FR-01** Use the `gmail.readonly` scope — no write actions except adding an
  `expense-processed` label.
- **FR-02** Query emails using a configurable (not hardcoded) sender filter plus a
  `newer_than:7d` filter. **Priority senders: BSI, OVO, Shopee.**
- **FR-03** The first (onboarding) sync pulls 90 days of history.
- **FR-04** Routine sync runs every 30 minutes via a background job (APScheduler),
  followed by a small capped extraction batch (limit 10) over anything newly
  synced.
- **FR-05** An IMAP IDLE listener detects new emails in real time and triggers
  the same sync-then-capped-extraction pipeline as the scheduled job.
- **FR-19** A manual "Sync now" dashboard action runs a sync then one bounded
  extraction batch (default limit 50) in a single request, with a live
  progress indicator; a bounded "extract more" follow-up is offered instead
  of looping automatically when a backlog remains, since extraction cost is
  real and user-tracked.
- **FR-20** The dashboard supports manual transaction CRUD: add a transaction
  by hand, edit any transaction's fields (manual or email-derived — never
  the raw email fields), and delete. Delete is a soft delete
  (`deleted_at`), not a hard `DELETE` — every read path (including the Q&A
  agent) excludes soft-deleted rows.
- **FR-06** A single email failure must not stop the pipeline.

### 4.2 LLM extraction
- **FR-07** Extraction uses structured output (Pydantic schema via the Anthropic
  API) — the model must return the predefined schema.
- **FR-08** Extraction schema (LLM-level contract):
  ```json
  {
    "date": "YYYY-MM-DD",
    "merchant": "string",
    "amount": "number",
    "currency": "IDR",
    "category": "food|transport|shopping|bills|entertainment|other",
    "payment_method": "Cash|QRIS|Debit Card|Credit Card|Bank Transfer|Virtual Account|GoPay|OVO|Dana|ShopeePay|LinkAja|Other|null",
    "is_transaction": "boolean",
    "confidence": "number (0.0 - 1.0)"
  }
  ```
- **FR-09** Emails with `is_transaction: false` are not stored in `transactions`.
- **FR-10** Emails with low confidence (below threshold) are stored in
  `flagged_emails` for manual review.
- **FR-17** Extraction calls use **Claude Haiku 4.5** (`claude-haiku-4-5`), with
  thinking disabled and no `effort` parameter (unsupported on this model).
  System prompt and schema are prompt-cached to control cost across the
  high email volume.

> Note: `confidence` is returned and stored as a numeric score (`NUMERIC(4,3)`,
> 0.000–1.000), not a `high|medium|low` enum. `category` is constrained to the
> enum above at the LLM layer but stored as free `TEXT` in the database.

### 4.3 Q&A agent
- **FR-11** The agent uses text-to-SQL — no vector RAG.
- **FR-12** Model-generated SQL is validated before execution (read-only, SELECT-only).
- **FR-13** The agent refuses queries that are dangerous or irrelevant to expense data.
- **FR-18** Q&A calls use **Claude Sonnet 5** (`claude-sonnet-5`) with adaptive
  thinking enabled and `effort: "medium"` as the default. Raise to `"high"` only
  if the eval shows incorrect SQL on complex (multi-join/aggregation) questions.

### 4.4 Alert
- **FR-14** Threshold logic is a deterministic backend calculation — not an LLM decision.
- **FR-15** The LLM is used only to compose the alert email body.
- **FR-16** 24-hour cooldown per category per threshold level (80% and 100% sent separately).

---

## 5. Non-functional requirements

| Category      | Requirement |
|---------------|-------------|
| Security      | OAuth tokens stored encrypted (AES-256-GCM) in PostgreSQL |
| Security      | The LLM API key is never exposed to the frontend |
| Security      | All backend endpoints require a session |
| Security      | Raw email HTML (untrusted, sender-controlled) is rendered only inside a sandboxed `<iframe>` with no script execution and no same-origin access |
| Privacy       | Data leaves only to Google (Gmail API) and the LLM provider (Anthropic) |
| Performance   | Dashboard loads in < 2s for 500 transactions |
| Reliability   | A single email's extraction failure never halts the pipeline |
| Reliability   | Automatic retry with exponential backoff for failed API calls |
| Observability | Every LLM call is logged: model, token usage, latency, estimated cost |

---

## 6. Tech stack

| Layer            | Choice                                       | Rationale |
|------------------|-----------------------------------------------|-----------|
| Language         | Python 3.12                                   | Dominant in the target job market (AI/entry-level remote work) |
| Backend / API     | FastAPI                                       | Handles OAuth callbacks, async I/O, standard for AI backends |
| Frontend          | Vue 3 + Vite                                   | Author's existing frontend skill; a real SPA demonstrates full-stack capability better than a data-app-style dashboard |
| Database          | PostgreSQL                                    | Relational data; pgvector available if needed later |
| Background jobs   | APScheduler                                   | In-process scheduler, no extra infrastructure |
| LLM — extraction  | Claude Haiku 4.5 (`claude-haiku-4-5`) via `langchain-anthropic` | Cost-efficient for high-volume structured extraction |
| LLM — Q&A agent   | Claude Sonnet 5 (`claude-sonnet-5`) via `langchain-anthropic`   | Near-Opus coding/agentic quality at Sonnet cost, for text-to-SQL |
| Email (send)      | Resend (not yet integrated — M7 alerts not built) | Good free tier and DX |
| Email (read)      | Gmail API (OAuth2) + IMAP IDLE                 | Scheduled sync + real-time detection |
| Hosting           | Docker → **Railway** (deployed)                | Cheap, single-container-friendly; always-on (no auto-sleep, needed for IMAP IDLE + the 30-min scheduler) |
| Auth              | Session-based (cookie), single user            | Simple for a single-user MVP |

---

## 7. Data model

The authoritative schema lives in `migrations/001_epic1.sql` plus four
follow-on migrations (`002_sender_filters.sql`, `003_add_is_transfer.sql`,
`004_add_is_manual.sql`, `005_soft_delete_transactions.sql`) — the original
Epic 1 design has since grown `transactions.is_transfer`, `is_manual`, and
`deleted_at`. A full, column-by-column explanation is in
[`DATABASE_SCHEMA.md`](./DATABASE_SCHEMA.md).

**Implemented tables:** `transactions`, `processed_emails`, `flagged_emails`,
`oauth_tokens`, `sync_logs`, `sender_filters`.

**Future-epic tables (not yet created):** `spending_limits`, `alert_logs`
(Epic 4), `llm_call_logs` (observability, Epic 2+).

---

## 8. Eval plan (extraction accuracy)
Before shipping extraction, build an eval set:
- At least 30 transaction emails from various senders (prioritising BSI, OVO,
  Shopee) — using real inbox data collected in Epic 1 (anonymised for any
  shared/demo use).
- Ground truth: the correct JSON for each email.
- Metrics: per-field accuracy (date, merchant, amount, category) and overall.
- Target: ≥ 85% overall accuracy before deploy.
- Re-run the eval whenever the prompt changes or the model is swapped.

---

## 9. Milestones

Ingestion is built first to de-risk the highest-uncertainty integration (Gmail
OAuth, IMAP IDLE, scheduling) before investing in AI features, and to produce
real email data that both the extraction design and the eval set can use.

| Milestone            | Deliverable                                                  | Phase |
|-----------------------|---------------------------------------------------------------|-------|
| M1 — Auth foundation  | Python project setup, DB schema applied, Gmail OAuth (connect/disconnect, encrypted token) | Ingestion |
| M2 — Email fetch      | Gmail fetch + parse + dedup, raw emails stored (BSI/OVO/Shopee) | Ingestion |
| M3 — Real-time sync   | IMAP IDLE listener + scheduled sync (APScheduler, every 30 min) | Ingestion |
| M4 — Extraction       | LLM extraction (Haiku 4.5) designed against real email data, manual-input fallback | AI |
| M5 — Dashboard        | Vue SPA over a REST API: transaction list, filters, charts    | AI |
| M6 — Q&A agent        | Text-to-SQL agent (Sonnet 5) + eval set (≥85% accuracy)        | AI |
| M7 — Alert & polish   | Threshold logic + email alert via Resend; deploy, observability, case study, demo video | Polish — **deploy done (Railway)**; alerts/eval set/case study/demo video still open |

---

## 10. Open questions — resolved

| #     | Question                                              | Decision |
|-------|-------------------------------------------------------|----------|
| OQ-01 | Which email senders are the first priority?           | **BSI, OVO, Shopee** |
| OQ-02 | IDR-only or multi-currency from the start?            | **IDR only for the MVP** |
| OQ-03 | Simple session auth or a separate login?              | **Session-based, single user** |
| OQ-04 | IMAP IDLE in the MVP or a stretch goal?               | **In the MVP (Epic 1)** |
| OQ-05 | Anthropic only or OpenAI fallback?                    | **Anthropic only** |
| OQ-06 | Go or Python backend?                                 | **Python** — see v4.0 changelog |
| OQ-07 | Build ingestion or AI extraction first?               | **Ingestion first** — de-risks OAuth/IMAP and yields real data for extraction design |
| OQ-08 | Streamlit or a real SPA for the dashboard?            | **Vue 3 SPA over a REST API** — see v4.1 changelog |
