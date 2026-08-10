# Database Schema — AI Expense Tracker

- **Database:** PostgreSQL 15+
- **Authoritative source:** `migrations/001_epic1.sql`
- **Last updated:** 2026-06-22

This document explains the Epic 1 schema column by column, the design rationale
behind each table, and how the tables relate within the ingestion pipeline.

---

## Pipeline overview

The tables make the most sense in the context of the ingestion flow:

```
Sync triggered (manual / scheduled / IMAP IDLE)
   │
   ├─► insert a row into  sync_logs        (record: when it started, what triggered it)
   │
   ├─► fetch emails from Gmail
   │
   └─► for EACH email:
          │
          ├─ already in  processed_emails?  ──► YES: skip (dedup)
          │                                       └─ emails_skipped++
          ├─ NO: mark it in processed_emails
          │
          ├─ extract with the LLM (Epic 2)
          │     ├─ SUCCESS ──► store in  transactions      emails_new++
          │     └─ FAILURE ──► store in  flagged_emails    (for manual review)
          │
   ◄──────┘
   update sync_logs (final status + counts)

oauth_tokens = separate; holds the encrypted Gmail access grant.
```

---

## Design decisions

1. **`amount` uses `NUMERIC(15,2)`**, never `float`. Money must not suffer binary
   rounding errors. `NUMERIC(15,2)` covers values up to hundreds of trillions of
   rupiah with two decimal places.
2. **No foreign keys between tables (MVP).** `transactions.message_id` and
   `flagged_emails.message_id` are not FK-constrained to `processed_emails`. This
   keeps insert ordering flexible and avoids coupling during the MVP.
3. **`TEXT` + `CHECK` constraints instead of `ENUM` types** for `status` / `trigger`.
   Adding a new allowed value is a one-line migration rather than an `ALTER TYPE`.
4. **`confidence` is a numeric score** (`NUMERIC(4,3)`, 0.000–1.000), not a
   `high|medium|low` enum. Storing the raw score allows threshold tuning later.
5. **All timestamps are `TIMESTAMPTZ`** (timezone-aware), defaulting to `now()`.
6. **UUID primary keys via `gen_random_uuid()`** — built into PostgreSQL 13+, no
   extension required.

---

## Tables

### 1. `transactions` — the final, core output
One row = one transaction successfully extracted from an email.

| Column | Type | Notes |
|---|---|---|
| `id` | `UUID PK` | `gen_random_uuid()` |
| `message_id` | `TEXT NOT NULL UNIQUE` | Gmail message ID; unique so one email cannot become two transactions |
| `raw_subject` | `TEXT` | original email subject |
| `raw_from` | `TEXT` | original sender |
| `raw_body` | `TEXT` | original email body, kept for audit/debugging |
| `date` | `TIMESTAMPTZ` | transaction date (extracted) |
| `merchant` | `TEXT` | e.g. "Shopee", "Indomaret" |
| `amount` | `NUMERIC(15,2)` | transaction amount |
| `currency` | `TEXT NOT NULL DEFAULT 'IDR'` | IDR for the MVP |
| `category` | `TEXT` | LLM classification (enum at the LLM layer, free text in DB) |
| `payment_method` | `TEXT` | e.g. "BSI", "OVO" |
| `confidence` | `NUMERIC(4,3)` | extraction confidence, 0.000–1.000 |
| `extracted_at` | `TIMESTAMPTZ` | when the LLM produced the result |
| `created_at` | `TIMESTAMPTZ NOT NULL DEFAULT now()` | row creation time |

**Indexes:** `idx_transactions_date (date DESC)`, `idx_transactions_category (category)`.

---

### 2. `processed_emails` — deduplication ledger
Records that an email has been *handled*, regardless of whether it produced a
transaction. Kept separate from `transactions` because an email may be processed
without becoming a transaction (e.g. a promo email, or a failed extraction). This
prevents reprocessing the same email on every sync.

| Column | Type | Notes |
|---|---|---|
| `message_id` | `TEXT PK` | a primary-key lookup answers "already handled?" quickly |
| `processed_at` | `TIMESTAMPTZ NOT NULL DEFAULT now()` | when it was handled |

---

### 3. `flagged_emails` — error bucket
The concrete realisation of the NFR "a single email failure must not stop the
pipeline". Problematic emails land here and the pipeline continues.

| Column | Type | Notes |
|---|---|---|
| `id` | `UUID PK` | |
| `message_id` | `TEXT NOT NULL` | which email |
| `raw_body` | `TEXT` | body kept for review |
| `error_message` | `TEXT` | technical error, e.g. "LLM timeout" |
| `flagged_reason` | `TEXT` | category, e.g. "low_confidence" / "parse_error" |
| `flagged_at` | `TIMESTAMPTZ NOT NULL DEFAULT now()` | when it was flagged |

**Index:** `idx_flagged_emails_message_id (message_id)`.

> Renamed from `flagged_transactions` (v1.0 PRD) to `flagged_emails`, and added
> `flagged_reason` to distinguish failure categories.

---

### 4. `oauth_tokens` — Gmail credentials, encrypted
Stores the Google OAuth token encrypted with AES-256-GCM. Even if the database is
leaked, the token is unreadable without `ENCRYPTION_KEY`.

| Column | Type | Notes |
|---|---|---|
| `id` | `UUID PK` | |
| `user_id` | `TEXT NOT NULL DEFAULT 'default'` | single-user MVP, but kept for future multi-user |
| `encrypted_token` | `BYTEA NOT NULL` | encrypted OAuth token (raw bytes) |
| `gmail_email` | `TEXT` | the connected email address |
| `connected_at` | `TIMESTAMPTZ NOT NULL DEFAULT now()` | when connected |
| `last_synced_at` | `TIMESTAMPTZ` | last successful sync |

**Constraint:** `UNIQUE (user_id)` — one token per user.

---

### 5. `sync_logs` — history & observability
One row per sync run. Backs the `GET /sync/logs` endpoint.

| Column | Type | Notes |
|---|---|---|
| `id` | `UUID PK` | |
| `trigger` | `TEXT NOT NULL CHECK (trigger IN ('manual','scheduled','imap_idle'))` | what started the sync |
| `status` | `TEXT NOT NULL CHECK (status IN ('running','success','failed'))` | run state |
| `emails_fetched` | `INT NOT NULL DEFAULT 0` | fetched from Gmail |
| `emails_new` | `INT NOT NULL DEFAULT 0` | newly processed |
| `emails_skipped` | `INT NOT NULL DEFAULT 0` | skipped via dedup |
| `error_message` | `TEXT` | set on total failure |
| `started_at` | `TIMESTAMPTZ NOT NULL DEFAULT now()` | run start |
| `finished_at` | `TIMESTAMPTZ` | run end |

**Index:** `idx_sync_logs_started_at (started_at DESC)`.

---

## River (background-job) tables
River creates and owns its own tables (`river_job`, `river_leader`, etc.) via its
own migration step (`river migrate`). They are **not** defined in
`001_epic1.sql` and are added when River is wired up.

---

## Future-epic tables (not yet created)

These come from the v1.0 PRD and will be added in later epics:

- **`spending_limits`** (Epic 4) — per-category monthly limits.
- **`alert_logs`** (Epic 4) — sent-alert log for the 24-hour cooldown.
- **`llm_call_logs`** (Epic 2+) — per-call observability: model, token usage,
  latency, estimated cost.
