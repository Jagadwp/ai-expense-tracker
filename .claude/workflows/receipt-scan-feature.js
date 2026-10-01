export const meta = {
  name: 'receipt-scan-feature',
  description: 'Implement the receipt-scan feature (backend, then frontend, then verify) per the approved plan',
  phases: [
    { title: 'Backend' },
    { title: 'Frontend' },
    { title: 'Verify' },
  ],
}

const REPO = '/Users/jagadpurnomo/playground/ai-expense-tracker'

const BACKEND_PROMPT = `
Repo: ${REPO} (FastAPI + psycopg backend). Backend-only task.

Implement the BACKEND portion of a new "receipt scan" feature. A user uploads/scans
a receipt photo. The backend sends it to Claude (vision) to extract line items and
returns a DRAFT (not persisted) so a bad scan never pollutes the DB. Separately,
items can be persisted either (a) at transaction-creation time (new transaction +
its items in one call) or (b) appended to an already-existing transaction.

1. New migration migrations/008_transaction_items.sql. Follow the exact style of
   existing migrations (001_epic1.sql, 007_email_received_at.sql): a "-- ====" banner
   with filename/purpose/apply command, a prose comment on why, CREATE TABLE IF NOT
   EXISTS for idempotency, id UUID PRIMARY KEY DEFAULT gen_random_uuid().

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

   FK is on transactions.message_id (already UNIQUE) -- this app treats message_id as
   the sole identifier everywhere, not the surrogate id, so don't introduce a second
   identifier just for this table. Add this file to the Makefile's migrate: target the
   same way 001-007 are already listed there. Also add transaction_items to
   document/DATABASE_SCHEMA.md's schema listing. Do NOT apply this migration against
   any live database -- just create the SQL file.

2. New app/receipt.py. Mirror app/extraction.py's structure exactly (read that file
   first -- it has build_extraction_llm(api_key) returning a
   ChatAnthropic(...).with_structured_output(SomeModel, method="json_schema"), and a
   plain function that builds [SystemMessage(...), HumanMessage(...)] and calls
   llm.invoke(messages)). Use the SAME method="json_schema" (not function_calling --
   this codebase's own docstrings explain why: unreliable when thinking is involved).

   Define:
     class ReceiptItem(BaseModel):
         name: str
         quantity: float
         unit_price: float | None = None
         subtotal: float

     class ReceiptScanResult(BaseModel):
         model_config = ConfigDict(extra="forbid")  # same as SqlGenerationResult in qa_agent.py
         merchant: str | None = None
         date: str | None = None  # YYYY-MM-DD if found
         total: float | None = None
         items: list[ReceiptItem] = []

     def build_receipt_llm(api_key: str):
         llm = ChatAnthropic(model="claude-sonnet-5", max_tokens=2048, api_key=api_key)
         return llm.with_structured_output(ReceiptScanResult, method="json_schema")

     def extract_receipt(llm, image_b64: str, mime_type: str) -> ReceiptScanResult: ...

   For extract_receipt, build a HumanMessage whose content is a list mixing a text
   instruction block and an image block:
     HumanMessage(content=[
         {"type": "text", "text": "<instruction>"},
         {"type": "image", "source_type": "base64", "data": image_b64, "mime_type": mime_type},
     ])
   This flat block shape (source_type/data/mime_type keys, not a nested source dict) is
   what the installed langchain-anthropic==1.5.6 expects as INPUT to a HumanMessage
   (its internal _format_data_content_block in chat_models.py translates it to
   Anthropic's native wire format itself -- do not pre-nest it yourself). Write a
   clear instruction telling the model: extract the merchant name, transaction date
   (YYYY-MM-DD) if visible, the grand total, and every line item with its name,
   quantity (default 1 if not itemized), and price/subtotal; if a field isn't
   visible, leave it null/empty rather than guessing.

   IMPORTANT: this combination (image content block + with_structured_output(method=
   "json_schema")) has not been used anywhere else in this codebase. After writing the
   code, verify it actually works end-to-end: write a tiny throwaway script (or use a
   Python REPL via Bash) that calls build_receipt_llm() with a real Anthropic API key
   (check .env / app/config.py's get_settings() for anthropic_api_key) and a real small
   test image (any receipt photo, or a screenshot of a simple itemized list if no
   receipt photo is available) encoded as base64, and confirm you get back a valid
   ReceiptScanResult with items populated, not an error. Report exactly what you
   tested and the result -- don't just assume the shape is correct from reading the
   library source.

3. app/store.py additions. Read the existing create_manual_transaction method as your
   template -- it's a single-row INSERT into transactions, then await self._conn.commit().

   - Extend create_manual_transaction(...) with a new parameter items: list[dict] | None
     = None. After the transaction INSERT, if items is provided, loop and cur.execute()
     an INSERT into transaction_items per item (no bulk-insert helper exists in this
     codebase yet -- don't add one just for this). Move the commit to after this loop
     so both the transaction and its items commit together atomically.
   - New method add_transaction_items(self, message_id: str, items: list[dict]) -> None:
     first check the transaction exists and isn't soft-deleted (SELECT 1 FROM
     transactions WHERE message_id = %s AND deleted_at IS NULL), raise the existing
     NotFoundError if no row (match how other methods already raise/use NotFoundError),
     then loop-insert items, one commit at the end.
   - Find whichever method currently backs GET /api/transactions/{message_id} and
     extend it to also SELECT id, name, quantity, unit_price, subtotal FROM
     transaction_items WHERE transaction_message_id = %s ORDER BY created_at, attaching
     the result as an "items" key in the returned dict.

4. app/main.py wiring.
   - In lifespan() startup, alongside app.state.extraction_llm = build_extraction_llm(...),
     add app.state.receipt_llm = build_receipt_llm(settings.anthropic_api_key).
   - Add UploadFile, File to the existing fastapi import line.
   - New endpoint POST /api/receipts/scan: takes file: UploadFile = File(...), reads
     await file.read(), base64-encodes it, determines mime_type from file.content_type,
     calls extract_receipt(app.state.receipt_llm, b64, mime_type), returns the
     ReceiptScanResult. Does NOT touch the database.
   - New endpoint POST /api/transactions/{message_id}/items: request body model
     AddItemsRequest(BaseModel): items: list[TransactionItemInput], where
     TransactionItemInput(BaseModel): name: str; quantity: float = 1;
     unit_price: float | None = None; subtotal: float. Calls
     app.state.store.add_transaction_items(...), catches NotFoundError -> HTTPException
     404 (match existing pattern), returns {"status": "ok"}.
   - Extend the existing TransactionInput model (used by POST /api/transactions) with
     items: list[TransactionItemInput] | None = None, threaded into
     create_manual_transaction(...). Do NOT extend PUT /api/transactions/{message_id}
     (edit) to handle items -- explicit v1 scope cut.
   - Extend the transaction-detail GET response to include items too.

Verification you must do yourself before reporting done:
1. venv/bin/python -c "import app.main" -- must succeed.
2. make test -- all existing tests must still pass.
3. The empirical vision+structured-output test described in step 2 -- don't skip it.
4. If a local dev Postgres is reachable, you MAY apply the migration to your LOCAL dev
   database only (never production) and manually hit the new endpoints once via curl
   against make dev's running server. If no local DB is reachable, say so clearly and
   rely on code review + the import/test checks.

Do not commit anything to git. Act as an executor: implement exactly what's specified,
reuse existing repo conventions, verify your own work, report back precisely.
`

const FRONTEND_PROMPT = (backend) => `
Repo: ${REPO} (Vue 3 + TypeScript frontend, frontend/). Frontend-only task.

The BACKEND half of the receipt-scan feature is already implemented and verified.
Backend agent's report, for the exact API contract you must integrate against:
---
${JSON.stringify(backend, null, 2)}
---
If anything above is ambiguous or looks incomplete, read the actual current state of
app/main.py, app/store.py, and app/receipt.py yourself before assuming -- don't guess
the API shape.

Implement the FRONTEND portion:

5. frontend/src/types.ts: add TransactionItem (id, name, quantity, unit_price,
   subtotal), TransactionItemInput (same minus id), ReceiptScanResult (merchant, date,
   total, items: TransactionItem[] or a minus-id variant), extend TransactionDetail
   with items: TransactionItem[], extend TransactionInput with
   items?: TransactionItemInput[].

6. frontend/src/api.ts: scanReceipt(file: File): Promise<ReceiptScanResult> using
   FormData + a raw fetch('/api/receipts/scan', { method: 'POST', body: formData })
   (no Content-Type header -- the browser sets the multipart boundary; this repo's
   existing postJson helper only covers no-body POSTs, don't force-fit it here), and
   addTransactionItems(messageId, items) following the existing PUT/PATCH-with-JSON-
   body style (see setIsTransfer, updateTransaction for the pattern).

7. New frontend/src/components/ReceiptScanner.vue: <input type="file" accept="image/*"
   capture="environment"> + thumbnail preview (URL.createObjectURL) + a "Scan receipt"
   button that calls scanReceipt(), with saving/error refs matching
   TransactionFormModal.vue's convention; emits a "scanned" event with the
   ReceiptScanResult on success. Self-contained because it's used from two different
   places -- don't duplicate the upload UI in both modals.

8. frontend/src/components/TransactionFormModal.vue: add an optional, collapsed "Scan
   receipt" section above the existing fields (same toggle-button convention as
   FilterBar.vue's .advanced-toggle, for consistency) containing
   <ReceiptScanner @scanned="onScanned" />. onScanned(result) pre-fills
   form.merchant/form.date/form.amount ONLY where the field is currently empty (never
   silently overwrite something the user already typed), and stashes result.items in
   a local ref; save() includes items in the payload to createTransaction when
   present. Only relevant for NEW transactions (!props.editing).

9. frontend/src/components/TransactionPreviewModal.vue: add an "Items" section below
   the existing <dl class="meta"> (v-if="detail.items?.length", simple list: name x
   quantity -- Rp subtotal), plus a <ReceiptScanner @scanned="onItemsScanned" /> for
   adding items to THIS already-existing transaction. onItemsScanned(result) calls
   addTransactionItems(messageId, result.items) then load() to refresh the detail
   (same refresh pattern already used by onEdited() in this file).

10. Mobile: no new breakpoint needed -- ReceiptScanner.vue's file input/thumbnail/
    button should stack naturally in both modals' existing mobile bottom-sheet styling
    (@media (max-width: 600px) blocks already in both files). This project always
    wants mobile layout considered, not just desktop -- verify it, don't assume it.

Verification you must do yourself before reporting done:
1. npx vue-tsc -b (from frontend/) -- must stay clean.
2. Start the dev server (make dev, or frontend: npm run dev + api: uvicorn per the
   Makefile) and use the Claude Browser MCP tools (if reachable via ToolSearch) to
   actually exercise both entry points -- new-transaction scan flow and existing-
   transaction scan flow -- at both a desktop and a 375px mobile viewport. If you
   don't have a real receipt photo, a screenshot of any itemized list/menu works for
   an end-to-end check.
3. Confirm items appear correctly in both flows.

Do not commit anything to git. Act as an executor: implement exactly what's specified,
reuse existing repo conventions, verify your own work, report back precisely.
`

const VERIFY_PROMPT = (backend, frontend) => `
Repo: ${REPO}. You are doing final verification, not implementation.

Backend agent report:
---
${JSON.stringify(backend, null, 2)}
---
Frontend agent report:
---
${JSON.stringify(frontend, null, 2)}
---

Independently confirm (don't just trust the reports -- re-run things yourself):
1. venv/bin/python -c "import app.main" succeeds.
2. make test passes (all tests, not just new ones).
3. cd frontend && npx vue-tsc -b is clean.
4. git status shows the expected new/changed files (migrations/008_transaction_items.sql,
   app/receipt.py, app/store.py, app/main.py, frontend/src/types.ts, frontend/src/api.ts,
   frontend/src/components/ReceiptScanner.vue, TransactionFormModal.vue,
   TransactionPreviewModal.vue, Makefile, document/DATABASE_SCHEMA.md) and nothing
   unexpected (no committed secrets, no stray files).
5. Read through the actual diff (git diff) for anything that looks like a deviation
   from the plan, a TODO left behind, or a half-finished piece.

Do NOT commit. Report a clear pass/fail summary: what's verified working, what (if
anything) still needs a human decision or fix before this is ready to commit.
`

phase('Backend')
const backend = await agent(BACKEND_PROMPT, { label: 'backend', agentType: 'executor' })

phase('Frontend')
const frontend = await agent(FRONTEND_PROMPT(backend), { label: 'frontend', agentType: 'executor' })

phase('Verify')
const verification = await agent(VERIFY_PROMPT(backend, frontend), { label: 'verify' })

return { backend, frontend, verification }
