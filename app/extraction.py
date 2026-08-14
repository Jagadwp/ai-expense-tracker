"""LLM extraction (M4): turn a raw transaction email into structured fields
using Claude Haiku 4.5 with structured output (FR-07/FR-08).

Design notes:
- No thinking, no `effort` — Haiku 4.5 doesn't support `effort`, and this is a
  high-volume, low-complexity classification/extraction task where the extra
  cost of reasoning isn't worth it.
- The system prompt + schema are prompt-cached (`cache_control`) since the
  same prompt is sent for every email in a batch.
- Low-confidence results are NOT written into transactions' extraction
  columns — only `confidence` is set, so a bad guess never silently pollutes
  a spend total before a human reviews it (see flagged_emails handling in
  app.main).
"""

import datetime as dt
from typing import Literal

from anthropic import Anthropic
from pydantic import BaseModel

CONFIDENCE_THRESHOLD = 0.7

Category = Literal["food", "transport", "shopping", "bills", "entertainment", "other"]

# Mirrors the frontend's payment-method dropdown (TransactionFormModal.vue) —
# same fixed vocabulary for LLM-extracted and manually-entered transactions,
# instead of free text that ends up as near-duplicate values ("QRIS" vs
# "Bank Transfer" vs "BI Fast" vs "BI-FAST", "Cash" vs "cash", ...).
PaymentMethod = Literal[
    "Cash",
    "QRIS",
    "Debit Card",
    "Credit Card",
    "Bank Transfer",
    "Virtual Account",
    "GoPay",
    "OVO",
    "Dana",
    "ShopeePay",
    "LinkAja",
    "Other",
]

SYSTEM_PROMPT = """You extract structured transaction data from bank/e-wallet \
notification emails for an Indonesian expense tracker. Senders include BSI \
(bank), OVO (e-wallet), blu by BCA digital (bank), and Shopee (marketplace).

Given the subject, sender, and body of one email, determine whether it \
describes a completed financial transaction (a payment, transfer, or \
purchase), and if so, extract its details.

- is_transaction: false for anything that is not a completed transaction \
(promotions, newsletters, login alerts, pending/failed transactions).
- is_transfer: true when this is a fund movement rather than a real expense \
— a bank transfer (Bank Transfer, BI Fast, etc.) to a personal name, the \
account holder's own name, or another bank account, where the email gives \
no indication it's paying for goods or a service. False for purchases, \
bills, and payments to a merchant or service provider, even if the payment \
method happens to be a bank transfer.
- amount: the transaction amount in the original currency, as a plain number.
- currency: always "IDR" for these senders.
- category: your best guess from the fixed set given the merchant and \
context. If is_transfer is true, this can still be your best guess or "other".
- payment_method: your best guess from the fixed set based on evidence in \
the email (a QRIS code/mention, bank transfer reference, e-wallet name, \
card type, etc.), even if the email uses a different specific product name \
(e.g. "blu", "BYOND by BSI" → "Bank Transfer" or "Debit Card", whichever \
fits the evidence). Use "Other" if nothing in the fixed set fits, or None if \
there's no evidence at all of how it was paid.
- confidence: your genuine confidence (0.0-1.0) that the extracted fields are \
correct. Use a low value when the email is ambiguous or the format is \
unfamiliar — do not default to a high score."""


class ExtractionResult(BaseModel):
    is_transaction: bool
    is_transfer: bool = False
    # A real date type (not str) puts a "format": "date" constraint on the
    # generated JSON schema, so Claude is guided to emit "YYYY-MM-DD" instead
    # of a localized string like "31 Mei 2026" — which Postgres's
    # TIMESTAMPTZ column rejects outright.
    date: dt.date | None = None
    merchant: str | None = None
    amount: float | None = None
    currency: str = "IDR"
    category: Category | None = None
    payment_method: PaymentMethod | None = None
    confidence: float


def extract_transaction(
    client: Anthropic, raw_subject: str, raw_from: str, raw_body: str
) -> ExtractionResult:
    """Call Claude Haiku 4.5 to extract structured fields from one email."""
    response = client.messages.parse(
        model="claude-haiku-4-5",
        max_tokens=1024,
        system=[
            {
                "type": "text",
                "text": SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral"},
            }
        ],
        messages=[
            {
                "role": "user",
                "content": (
                    f"Subject: {raw_subject}\nFrom: {raw_from}\n\nBody:\n{raw_body}"
                ),
            }
        ],
        output_format=ExtractionResult,
    )
    return response.parsed_output
