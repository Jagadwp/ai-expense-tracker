"""Q&A agent (M6): natural-language questions over expense data via
text-to-SQL, using Claude Sonnet 5 (FR-11/FR-12/FR-13/FR-18).

Design notes:
- Two separate LLM calls: generate_sql() produces a validated SQL SELECT (or
  declines), Store executes it, then compose_answer() turns the raw rows
  into a natural-language reply. Splitting generation from composition keeps
  each call focused, and means the model never both writes and executes a
  query in one step.
- validate_sql() is defense-in-depth: even though the prompt instructs
  Claude to emit read-only SQL against `transactions` only, the code
  re-validates before execution rather than trusting model output for
  something that runs against the real database.
- Adaptive thinking + effort="medium" per FR-18 — Sonnet 5's default
  reasoning depth for this task.

experiment/langchain branch: ported from the raw `anthropic` SDK to
`langchain-anthropic`. Verified empirically (not just assumed) that
`thinking`, `output_config.effort`, and `cache_control` prompt caching all
still work correctly through ChatAnthropic — see the branch notes. Two
separate ChatAnthropic instances are built (one per function) since they
use different `max_tokens`; generate_sql()'s is additionally bound to
SqlGenerationResult via `with_structured_output(..., method="json_schema")`
— not the default `method="function_calling"`, which the library itself
warns is unreliable when `thinking` is enabled (forced tool calling can
conflict with extended reasoning).
"""

import re

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, ConfigDict

MODEL = "claude-sonnet-5"

SCHEMA_DESCRIPTION = """\
Table: transactions (the only table available for querying)
- message_id (text): unique identifier for the transaction/email. Select \
this when the user asks for an "id", "transaction id", or similar.
- date (timestamptz): transaction date
- merchant (text): merchant or recipient name
- amount (numeric): amount in IDR
- category (text): one of food, transport, shopping, bills, entertainment, other
- payment_method (text): one of Cash, QRIS, Debit Card, Credit Card, Bank \
Transfer, Virtual Account, GoPay, OVO, Dana, ShopeePay, LinkAja, Other — for \
transactions added since this became a fixed set. Older rows may still hold \
free-text values (e.g. "BI Fast", "blu") since this wasn't backfilled.
- is_transfer (boolean): true means a fund transfer/movement, NOT a real
  expense. Exclude is_transfer = true from spend totals unless the question
  specifically asks about transfers.
- confidence (numeric), extracted_at (timestamptz): a row is a valid,
  extracted transaction only when extracted_at IS NOT NULL.
- deleted_at (timestamptz): non-NULL means the user deleted this transaction
  from the dashboard. Always exclude these.

Always filter WHERE extracted_at IS NOT NULL AND deleted_at IS NULL. Exclude
is_transfer = true unless the question explicitly asks about transfers."""

SQL_SYSTEM_PROMPT = f"""You translate natural-language questions about a \
personal expense tracker into a single read-only PostgreSQL query.

{SCHEMA_DESCRIPTION}

Rules:
- Only SELECT statements against the transactions table. Never write, \
modify, or reference any other table.
- If the question cannot be answered from this schema (unrelated to \
expenses, or asks for data that doesn't exist here), set can_answer to \
false and leave sql unset — do not guess.
- Prefer aggregates (SUM, COUNT, AVG) when the question asks for a total or \
summary rather than a row listing."""

ANSWER_SYSTEM_PROMPT = """You answer a user's question about their \
personal expenses in one or two short sentences, given the question and \
the raw SQL query result (JSON rows). Amounts are in Indonesian Rupiah \
(IDR) — format them like "Rp 450.000". If the rows are empty or all-null, \
say plainly that there's no data for that, rather than guessing."""


class SqlGenerationResult(BaseModel):
    # extra="forbid" makes Pydantic emit "additionalProperties": false in the
    # JSON schema, which output_config.format requires for object types.
    model_config = ConfigDict(extra="forbid")

    can_answer: bool
    sql: str | None = None


class UnsafeSqlError(Exception):
    """Raised when generated SQL fails the read-only/single-table guardrail."""


_FORBIDDEN_KEYWORDS = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|TRUNCATE|GRANT|REVOKE|CREATE|EXEC|CALL)\b",
    re.IGNORECASE,
)
_OTHER_TABLES = ("oauth_tokens", "flagged_emails", "sync_logs", "processed_emails")
_ALLOWED_TABLE = "transactions"


def validate_sql(sql: str) -> str:
    """Re-validate the model's SQL before execution — defense-in-depth, not
    a substitute for the prompt instructions.

    Raises UnsafeSqlError if the query isn't a single SELECT against
    `transactions` only. Returns the query with a LIMIT appended if the
    model didn't include one."""
    stripped = sql.strip().rstrip(";")
    if ";" in stripped:
        raise UnsafeSqlError("multiple statements are not allowed")
    if not re.match(r"^\s*SELECT\b", stripped, re.IGNORECASE):
        raise UnsafeSqlError("only SELECT statements are allowed")
    if _FORBIDDEN_KEYWORDS.search(stripped):
        raise UnsafeSqlError("query contains a forbidden keyword")
    if _ALLOWED_TABLE not in stripped.lower():
        raise UnsafeSqlError(f"query must reference the {_ALLOWED_TABLE} table")
    for other_table in _OTHER_TABLES:
        if other_table in stripped.lower():
            raise UnsafeSqlError(f"query must not reference {other_table}")

    if not re.search(r"\bLIMIT\b", stripped, re.IGNORECASE):
        stripped += " LIMIT 200"
    return stripped


def build_sql_llm(api_key: str):
    """Build the LangChain Runnable used by generate_sql(), bound to
    SqlGenerationResult via the native JSON-schema output path (see module
    docstring for why not the default tool-calling method)."""
    llm = ChatAnthropic(
        model=MODEL,
        max_tokens=1024,
        thinking={"type": "adaptive"},
        output_config={"effort": "medium"},
        api_key=api_key,
    )
    return llm.with_structured_output(SqlGenerationResult, method="json_schema")


def build_answer_llm(api_key: str) -> ChatAnthropic:
    """Build the plain (non-structured) LangChain chat model used by
    compose_answer()."""
    return ChatAnthropic(
        model=MODEL,
        max_tokens=512,
        thinking={"type": "adaptive"},
        output_config={"effort": "medium"},
        api_key=api_key,
    )


def generate_sql(llm, question: str) -> SqlGenerationResult:
    """Call Claude Sonnet 5 (via the Runnable from build_sql_llm) to
    translate a question into SQL, or decline."""
    messages = [
        SystemMessage(
            content=[{"type": "text", "text": SQL_SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}]
        ),
        HumanMessage(content=question),
    ]
    return llm.invoke(messages)


def compose_answer(llm: ChatAnthropic, question: str, rows: list[dict]) -> str:
    """Call Claude Sonnet 5 (via build_answer_llm) to turn raw query rows
    into a natural-language answer to the original question."""
    messages = [
        SystemMessage(
            content=[{"type": "text", "text": ANSWER_SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}]
        ),
        HumanMessage(content=f"Question: {question}\n\nQuery result (JSON rows):\n{rows}"),
    ]
    response = llm.invoke(messages)

    # response.content is a plain str only when adaptive thinking decided not
    # to think (the common case). When it does think, content becomes a list
    # of blocks — a "thinking" block (its reasoning, discarded) plus a "text"
    # block (the real answer) — verified empirically on this branch; returning
    # the raw list here would silently hand the frontend a list instead of a
    # string whenever a harder question happens to engage real reasoning.
    if isinstance(response.content, str):
        return response.content
    return "".join(block["text"] for block in response.content if block.get("type") == "text")
