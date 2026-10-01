"""Receipt scan: turn a photographed receipt into structured line items
using Claude Sonnet 5 vision with structured output.

Design notes (mirrors app/extraction.py):
- `method="json_schema"` (not the default `function_calling`) — LangChain's
  own docs warn `function_calling` is unreliable when `thinking` is
  involved, and this is the established convention in this codebase
  regardless of whether thinking is used here.
- A scan result returned by this module is a DRAFT only — nothing here
  touches the database. The caller (app.main's /api/receipts/scan) returns
  the ReceiptScanResult straight to the frontend so a bad/garbled scan can
  be reviewed and corrected before anything is persisted (see app.store's
  create_manual_transaction/replace_transaction_items for the actual writes).
"""

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, ConfigDict

SYSTEM_PROMPT = """You extract structured line-item data from a photo of a \
receipt for an Indonesian expense tracker.

Given the receipt image, extract:
- merchant: the store/merchant name, if visible.
- date: the transaction date, in YYYY-MM-DD format, if visible.
- total: the grand total amount on the receipt, as a plain number, if \
visible.
- items: every line item on the receipt. For each item, extract its name, \
quantity (default to 1 if the receipt does not itemize quantity), \
unit_price if shown, and subtotal (that item's line total).

If a field is not visible or not stated on the receipt, leave it null (or \
omit the item detail) rather than guessing a value."""


class ReceiptItem(BaseModel):
    name: str
    quantity: float
    unit_price: float | None = None
    subtotal: float


class ReceiptScanResult(BaseModel):
    # Required for the json_schema structured-output method — same as
    # SqlGenerationResult in app/qa_agent.py.
    model_config = ConfigDict(extra="forbid")

    merchant: str | None = None
    date: str | None = None  # YYYY-MM-DD if found
    total: float | None = None
    items: list[ReceiptItem] = []


def build_receipt_llm(api_key: str):
    """Build the LangChain Runnable used by extract_receipt(), bound to
    ReceiptScanResult via the native JSON-schema output path (see module
    docstring)."""
    llm = ChatAnthropic(model="claude-sonnet-5", max_tokens=2048, api_key=api_key)
    return llm.with_structured_output(ReceiptScanResult, method="json_schema")


def extract_receipt(llm, image_b64: str, mime_type: str) -> ReceiptScanResult:
    """Call Claude Sonnet 5 (via the Runnable from build_receipt_llm) to
    extract structured line items from one receipt image.

    image_b64 is the raw image bytes, base64-encoded; mime_type is the
    image's content type (e.g. "image/jpeg")."""
    messages = [
        SystemMessage(content=SYSTEM_PROMPT),
        HumanMessage(
            content=[
                {
                    "type": "text",
                    "text": "Extract the merchant, date, total, and line items from this receipt.",
                },
                {
                    "type": "image",
                    "source_type": "base64",
                    "data": image_b64,
                    "mime_type": mime_type,
                },
            ]
        ),
    ]
    return llm.invoke(messages)
