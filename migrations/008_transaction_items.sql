-- ============================================================
-- 008_transaction_items.sql — line items for a transaction (receipt scan)
-- Apply with: psql "$DATABASE_URL" -f migrations/008_transaction_items.sql
--
-- The receipt-scan feature lets a user photograph a receipt and have Claude
-- (vision) extract its line items. A scan is only ever returned as a DRAFT
-- to the frontend first — it is never written to the database on its own —
-- so a bad/garbled scan can never pollute a transaction's data. Items are
-- only persisted once a human confirms them, either alongside a brand-new
-- transaction (one call creates the transaction row and its items
-- together) or appended to an already-existing transaction afterwards.
--
-- The FK points at transactions.message_id (already UNIQUE), not
-- transactions.id — this app treats message_id as the sole identifier for
-- a transaction everywhere (dashboard routes, the Q&A agent, manual
-- transactions' synthesized `manual:<uuid>` ids, ...), so items follow the
-- same convention rather than introducing a second identifier just for
-- this table. ON DELETE CASCADE means deleting a transaction's items is
-- never a separate step to remember.
-- ============================================================

CREATE TABLE IF NOT EXISTS transaction_items (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    transaction_message_id TEXT NOT NULL REFERENCES transactions(message_id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    quantity NUMERIC(10,2) NOT NULL DEFAULT 1,
    unit_price NUMERIC(15,2),
    subtotal NUMERIC(15,2) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_transaction_items_message_id ON transaction_items(transaction_message_id);
