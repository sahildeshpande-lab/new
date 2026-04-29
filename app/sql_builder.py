from __future__ import annotations

import re
from typing import Any


# Forbidden SQL keywords that must never appear in a SELECT-only backend
_FORBIDDEN = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|TRUNCATE|CALL|EXECUTE|GRANT|REVOKE|REPLACE|MERGE)\b",
    re.IGNORECASE,
)

# Named parameter pattern  :param_name
_NAMED_PARAM = re.compile(r":([a-zA-Z_][a-zA-Z0-9_]*)")

# table.column references in SELECT/WHERE/JOIN etc.
_TABLE_COL = re.compile(r"\b([a-zA-Z_][a-zA-Z0-9_]*)\.([a-zA-Z_][a-zA-Z0-9_]*)\b")

# Stacked queries
_STATEMENT_TERMINATOR = re.compile(r";\s*\S")


def validate_llm_sql(sql: str, params: dict[str, Any]) -> list[str]:
    """
    Perform lightweight safety and consistency checks on LLM-generated SQL.

    Returns a list of non-fatal warning strings.
    Raises ValueError for hard failures.
    """
    if not sql or not sql.strip():
        raise ValueError("LLM returned an empty SQL string.")

    sql_upper = sql.upper().lstrip()

    # Must be a SELECT
    if not sql_upper.startswith("SELECT"):
        raise ValueError(f"SQL must start with SELECT; got: {sql[:80]!r}")

    # No forbidden DML/DDL
    match = _FORBIDDEN.search(sql)
    if match:
        raise ValueError(f"Forbidden SQL keyword '{match.group()}' found in generated SQL.")

    # No stacked statements
    if _STATEMENT_TERMINATOR.search(sql):
        raise ValueError("Generated SQL contains multiple statements (detected ';' followed by more SQL).")

    # Every :param in SQL must exist in params dict
    sql_params = set(_NAMED_PARAM.findall(sql))
    missing = sql_params - set(params.keys())
    if missing:
        raise ValueError(
            f"SQL references parameters {sorted(missing)} that are not in the params dict."
        )

    # Every params key should appear in SQL (warn only)
    warnings: list[str] = []
    extra = set(params.keys()) - sql_params
    if extra:
        warnings.append(
            f"Params {sorted(extra)} are in params dict but not referenced in SQL — they will be ignored."
        )

    # Must include LIMIT
    if "LIMIT" not in sql_upper:
        warnings.append("Generated SQL does not contain LIMIT; result set size is unbounded.")

    return warnings


def validate_llm_sql_against_live_schema(
    sql: str,
    schema_summary: dict[str, Any] | None,
) -> list[str]:
    """
    Cross-check every table.column reference in the SQL against the live schema.

    Returns warnings for unrecognised references.
    Raises ValueError if a referenced table does not exist at all.
    """
    if not schema_summary:
        return ["Live schema not available; skipping schema validation."]

    tables: dict[str, list[str]] = {
        tbl: [col["name"] for col in info.get("columns", [])]
        for tbl, info in schema_summary.get("tables", {}).items()
    }

    warnings: list[str] = []
    for tbl, col in _TABLE_COL.findall(sql):
        tbl_lower = tbl.lower()
        col_lower = col.lower()

        # Skip SQL keywords that look like table.col (e.g. DATE_FORMAT)
        if tbl_lower in {"date_format", "coalesce", "ifnull", "nullif", "if", "cast", "convert"}:
            continue

        if tbl_lower not in {t.lower() for t in tables}:
            raise ValueError(
                f"SQL references table '{tbl}' which does not exist in the live database schema."
            )

        real_table = next(t for t in tables if t.lower() == tbl_lower)
        real_cols = [c.lower() for c in tables[real_table]]
        if col_lower not in real_cols:
            warnings.append(
                f"Column '{col}' not found in table '{real_table}' in the live schema. "
                "The query may fail at runtime."
            )

    return warnings