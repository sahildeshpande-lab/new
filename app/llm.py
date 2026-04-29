from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any

from app.config import Settings, get_settings


JSON_OBJECT_PATTERN = re.compile(r"\{.*\}", re.DOTALL)


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class LlmSqlPlan:
    report_id: str
    report_name: str
    sql: str
    params: dict[str, Any]
    expected_columns: list[str]
    report_title: str
    report_summary: str
    warnings: list[str]


# ---------------------------------------------------------------------------
# Mistral client
# ---------------------------------------------------------------------------

class MistralClient:
    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()

    def chat_json(self, messages: list[dict[str, str]]) -> dict[str, Any]:
        if not self.settings.mistral_api_key:
            raise RuntimeError(
                "MISTRAL_API_KEY is missing. Add it to .env before using LLM SQL generation."
            )
        payload = {
            "model": self.settings.mistral_model,
            "messages": messages,
            "temperature": self.settings.llm_temperature,
            "max_tokens": self.settings.llm_max_tokens,
            "response_format": {"type": "json_object"},
        }
        url = f"{self.settings.mistral_base_url}/chat/completions"
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode(),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.settings.mistral_api_key}",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                body = json.loads(resp.read().decode())
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Mistral API error {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Could not reach Mistral API: {exc.reason}") from exc

        return parse_json_object(_extract_mistral_text(body))

    def list_models(self) -> dict[str, Any]:
        if not self.settings.mistral_api_key:
            raise RuntimeError("MISTRAL_API_KEY is missing.")
        url = f"{self.settings.mistral_base_url}/models"
        req = urllib.request.Request(
            url,
            headers={"Authorization": f"Bearer {self.settings.mistral_api_key}"},
            method="GET",
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode())
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Mistral API error {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Could not reach Mistral API: {exc.reason}") from exc


# ---------------------------------------------------------------------------
# Provider selection
# ---------------------------------------------------------------------------

def get_llm_client(settings: Settings | None = None) -> MistralClient:
    s = settings or get_settings()
    return MistralClient(s)


# ---------------------------------------------------------------------------
# SQL plan generation
# ---------------------------------------------------------------------------

def generate_sql_plan(
    question: str,
    metadata: dict[str, Any],
    schema_summary: dict[str, Any] | None,
    filters: dict[str, Any] | None = None,
    limit: int = 100,
    client: GeminiClient | GroqClient | None = None,
    correction: dict[str, Any] | None = None,
) -> LlmSqlPlan:
    client = client or get_llm_client()
    filters = filters or {}

    messages = [
        {"role": "system", "content": _build_system_prompt()},
        {
            "role": "user",
            "content": json.dumps(
                {
                    "task": "Generate a safe MySQL SELECT report query from natural language.",
                    "question": question,
                    "user_filters": filters,
                    "row_limit": max(1, min(int(limit), 1000)),
                    "reporting_metadata": _compact_metadata(metadata),
                    "live_schema_summary": _compact_schema(schema_summary),
                    "previous_error_to_fix": correction or {},
                    "output_contract": {
                        "report_id": "one of the report ids in reporting_metadata.reports",
                        "report_name": "human report name",
                        "sql": "single MySQL SELECT statement using named parameters like :date_from and :limit",
                        "params": "object containing every named parameter used in sql",
                        "expected_columns": "array of output column names",
                        "report_title": "short report title",
                        "report_summary": "short natural-language report description before execution",
                        "warnings": "array of caveats or clarification notes",
                    },
                },
                ensure_ascii=True,
            ),
        },
    ]
    raw = client.chat_json(messages)
    return LlmSqlPlan(
        report_id=str(raw.get("report_id") or ""),
        report_name=str(raw.get("report_name") or ""),
        sql=str(raw.get("sql") or ""),
        params=dict(raw.get("params") or {}),
        expected_columns=list(raw.get("expected_columns") or []),
        report_title=str(raw.get("report_title") or ""),
        report_summary=str(raw.get("report_summary") or ""),
        warnings=list(raw.get("warnings") or []),
    )


# ---------------------------------------------------------------------------
# Report narrative generation
# ---------------------------------------------------------------------------

def generate_report_narrative(
    question: str,
    plan: LlmSqlPlan,
    rows: list[dict[str, Any]],
    client: GeminiClient | GroqClient | None = None,
) -> str:
    client = client or get_llm_client()
    messages = [
        {
            "role": "system",
            "content": (
                "You generate concise business report summaries from SQL result rows. "
                "Do not invent facts. If rows are empty, say no rows matched. "
                'Return JSON only: {"generated_report": "..."}.'
            ),
        },
        {
            "role": "user",
            "content": json.dumps(
                {
                    "question": question,
                    "report_id": plan.report_id,
                    "report_name": plan.report_name,
                    "row_count": len(rows),
                    "rows_preview": rows[:50],
                },
                default=str,
                ensure_ascii=True,
            ),
        },
    ]
    raw = client.chat_json(messages)
    return str(raw.get("generated_report") or "")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_system_prompt() -> str:
    return (
        "You are the SQL generation engine for a read-only MySQL reporting backend. "
        "Deeply understand the provided database schema, table descriptions, column meanings, "
        "relationships, and business logic before writing SQL. "
        "\n\n"
        "SCHEMA RULES:\n"
        "- Use live_schema_summary as the ONLY source of truth for table/column names.\n"
        "- Before selecting ANY column, verify it appears in live_schema_summary.\n"
        "- Never reference a table.column pair unless listed in live_schema_summary.\n"
        "- Do NOT use table aliases; always write table.column.\n"
        "\n"
        "ATTENDANCE TABLE NOTES:\n"
        "- attendances has its own columns: name, employee_id, department, designation, "
        "total_hours, status, date, for_month, day.\n"
        "- Always use the `date` column for month filtering (e.g. DATE_FORMAT(date, '%Y-%m')) as the `for_month` column is usually NULL.\n"
        "- Do NOT join attendances to users unless live_schema_summary shows attendances.user_id.\n"
        "- Do NOT filter by `is_deleted` or `deleted_at` as attendances does not have these columns.\n"
        "\n"
        "TIMESHEET NOTES:\n"
        "- Use timelog_records for detailed time tracking.\n"
        "- Use timesheets for summary-level data.\n"
        "- When querying timesheets or timelog_records, ALWAYS JOIN the `users` table on `user_id = users.id` and select `users.name` to show the employee name.\n"
        "- ALWAYS JOIN the `projects` table on `project_id = projects.id` and select `projects.project_name` to show the project name.\n"
        "- For timelog_records, calculate total hours as a decimal: `ROUND(hours + (minutes / 60.0), 2) AS total_hours`.\n"
        "\n"
        "GENERAL FILTERING RULES (APPLIES TO ALL REPORTS INCLUDING ATTENDANCES AND TIMESHEETS):\n"
        "- If the user asks for a specific date (e.g. '31 March 2026'), use strict equality on the `date` column (e.g. `date = :specific_date`) and parse the date string to 'YYYY-MM-DD' format for the parameter value.\n"
        "- If the user asks for a specific employee by name (e.g. 'AnilkumarMergu'), use a case-insensitive LIKE clause on `users.name` (for timesheets) or `name` (for attendances) and wrap the parameter value in `%` (e.g. `%AnilkumarMergu%`).\n"
        "\n"
        "SQL RULES:\n"
        "- Generate MySQL SQL only. Never use SQLite functions.\n"
        "- Use MySQL DATE_FORMAT(col, '%Y-%m') for month filtering.\n"
        "- Use named parameters for ALL user values: :param_name.\n"
        "- Include :limit parameter with LIMIT :limit.\n"
        "- All :param keys in SQL must exactly match keys in params object.\n"
        "- Generate exactly ONE SELECT statement.\n"
        "- NEVER generate INSERT, UPDATE, DELETE, DROP, ALTER, CREATE, TRUNCATE, CALL.\n"
        "- NEVER generate multiple statements.\n"
        "\n"
        "OUTPUT RULES:\n"
        "- Only select reports from reporting_metadata.reports.\n"
        "- Return exactly one JSON object. No markdown, no code fences.\n"
        "- If a requested column is missing from live schema, omit it and note in warnings.\n"
        "- For unsupported requests: set report_id and sql to empty string and explain in warnings.\n"
    )


def _compact_schema(schema_summary: dict[str, Any] | None) -> dict[str, Any]:
    if not schema_summary:
        return {}
    return {
        "database": schema_summary.get("database"),
        "tables": {
            tbl: [col["name"] for col in info.get("columns", [])]
            for tbl, info in schema_summary.get("tables", {}).items()
        },
    }


def _compact_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    return {
        "reports": {
            rid: {
                "name": r.get("name"),
                "description": r.get("description"),
                "allowed_filters": r.get("allowed_filters", []),
                "business_logic": r.get("business_logic", []),
            }
            for rid, r in metadata.get("reports", {}).items()
        }
    }


def _extract_mistral_text(body: dict[str, Any]) -> str:
    choices = body.get("choices") or []
    if not choices:
        raise ValueError(f"Mistral returned no choices: {body}")
    content = choices[0].get("message", {}).get("content", "")
    if not content:
        raise ValueError(f"Mistral returned empty content: {body}")
    return content


def parse_json_object(content: str) -> dict[str, Any]:
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        match = JSON_OBJECT_PATTERN.search(content)
        if not match:
            raise ValueError("LLM response did not contain a JSON object.")
        return json.loads(match.group(0))

