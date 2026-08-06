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
  reasoning depth for this task. Uses messages.create() directly (not
  .parse()) since output_config needs both `format` and `effort` set
  together.
"""

import re

from anthropic import Anthropic
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
- payment_method (text)
- is_transfer (boolean): true means a fund transfer/movement, NOT a real
  expense. Exclude is_transfer = true from spend totals unless the question
  specifically asks about transfers.
- confidence (numeric), extracted_at (timestamptz): a row is a valid,
  extracted transaction only when extracted_at IS NOT NULL.

Always filter WHERE extracted_at IS NOT NULL. Exclude is_transfer = true
unless the question explicitly asks about transfers."""

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


def generate_sql(client: Anthropic, question: str) -> SqlGenerationResult:
    """Call Claude Sonnet 5 to translate a question into SQL, or decline."""
    response = client.messages.create(
        model=MODEL,
        max_tokens=1024,
        thinking={"type": "adaptive"},
        output_config={
            "format": {
                "type": "json_schema",
                "schema": SqlGenerationResult.model_json_schema(),
            },
            "effort": "medium",
        },
        system=[
            {
                "type": "text",
                "text": SQL_SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral"},
            }
        ],
        messages=[{"role": "user", "content": question}],
    )
    text = next(block.text for block in response.content if block.type == "text")
    return SqlGenerationResult.model_validate_json(text)


def compose_answer(client: Anthropic, question: str, rows: list[dict]) -> str:
    """Call Claude Sonnet 5 to turn raw query rows into a natural-language
    answer to the original question."""
    response = client.messages.create(
        model=MODEL,
        max_tokens=512,
        thinking={"type": "adaptive"},
        output_config={"effort": "medium"},
        system=[
            {
                "type": "text",
                "text": ANSWER_SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral"},
            }
        ],
        messages=[
            {
                "role": "user",
                "content": f"Question: {question}\n\nQuery result (JSON rows):\n{rows}",
            }
        ],
    )
    return next(block.text for block in response.content if block.type == "text")
