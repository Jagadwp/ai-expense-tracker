# AI Expense Tracker

Tracking personal spending by hand is tedious — transaction notifications
are scattered across email, manual entry is a chore, and there's no
automated, actionable insight. **AI Expense Tracker** reads those emails
for you: it watches your Gmail inbox, extracts the expense data with an
LLM, and lets you explore your spending on a dashboard — or just ask it in
plain language.

> 📸 Screenshot / 🔗 [Live demo](#) — _TODO_

## Features

- **Zero manual entry** — Gmail is synced automatically (real-time via IMAP
  IDLE, plus a 30-minute scheduled fallback) and each transaction email is
  parsed into structured data by an LLM.
- **Ask your expenses a question** — a text-to-SQL agent (Claude Sonnet 5)
  answers things like *"how much did I spend on food last month?"* in
  natural language.
- **Interactive dashboard** — date-range filters, category breakdown,
  spend trend charts, and a sortable/paginated transaction table.
- **Manual control when you need it** — add, edit, or (soft-)delete any
  transaction by hand; a one-click "Sync now" for on-demand syncing.
- **Built for real inboxes** — one bad or ambiguous email never breaks the
  pipeline (low-confidence extractions are flagged for review, not
  silently trusted).

## Tech stack

| | |
|---|---|
| Backend | FastAPI, PostgreSQL, [LangChain](https://python.langchain.com/) over Claude Haiku 4.5 (extraction) & Sonnet 5 (Q&A) |
| Frontend | Vue 3 + Vite |
| Email sync | Gmail API (OAuth2), IMAP IDLE, APScheduler |
| Security | AES-256-GCM encrypted OAuth tokens |

## Architecture

```
Gmail inbox ──▶ sync (IMAP IDLE / scheduler) ──▶ raw email in Postgres
                                                        │
                                                        ▼
                                          LLM extraction (Claude Haiku)
                                                        │
                                                        ▼
                                        structured transaction in Postgres
                                                        │
                                   ┌────────────────────┴────────────────────┐
                                   ▼                                         ▼
                       Vue dashboard (REST API)               Q&A agent (Claude Sonnet, text-to-SQL)
```

## Quick start

```bash
git clone https://github.com/Jagadwp/ai-expense-tracker.git
cd ai-expense-tracker
make install
cp .env.example .env   # fill in DATABASE_URL, ANTHROPIC_API_KEY, Google OAuth credentials
make migrate
make dev                # runs the API (:8080) and dashboard (:5173) together
```

Full setup details (Google Cloud OAuth setup, IMAP app password, env
variables) are in [`document/PRD.md`](document/PRD.md).

## Documentation

This README is intentionally short. For anyone who wants the deep end:

- [`document/PRD.md`](document/PRD.md) — full product spec, functional
  requirements, and a running design-decision changelog.
- [`README.full.md`](README.full.md) — the previous, exhaustive README:
  every module explained, full API reference, database migrations, and
  setup walkthrough.

## Status

M1–M6 (Gmail ingestion, extraction, dashboard, Q&A agent) are built and
tested end-to-end against a real Gmail account. See the "To do" section in
[`README.full.md`](README.full.md) for what's left.
