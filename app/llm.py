import json
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any

from app.config import Settings, get_settings


JSON_OBJECT_PATTERN = re.compile(r"\{.*\}", re.DOTALL)


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


class GeminiClient:
    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()

    def chat_json(self, messages: list[dict[str, str]]) -> dict[str, Any]:
        if not self.settings.gemini_api_key:
            raise RuntimeError("GEMINI_API_KEY is missing. Add it to .env before using LLM SQL generation.")

        prompt = "\n\n".join(f"{message['role'].upper()}:\n{message['content']}" for message in messages)
        payload = {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": self.settings.llm_temperature,
                "maxOutputTokens": self.settings.llm_max_tokens,
                "responseMimeType": "application/json",
            },
        }
        url = self._url(f"/models/{self.settings.gemini_model}:generateContent")
        request = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                body = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(format_gemini_http_error(exc.code, detail, self.settings.gemini_model)) from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Could not reach Gemini API: {exc.reason}") from exc

        content = extract_gemini_text(body)
        return parse_json_object(content)

    def list_models(self) -> dict[str, Any]:
        if not self.settings.gemini_api_key:
            raise RuntimeError("GEMINI_API_KEY is missing. Add it to .env before checking Gemini model access.")

        request = urllib.request.Request(self._url("/models"), method="GET")
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(format_gemini_http_error(exc.code, detail, self.settings.gemini_model)) from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Could not reach Gemini API: {exc.reason}") from exc

    def _url(self, path: str) -> str:
        query = urllib.parse.urlencode({"key": self.settings.gemini_api_key})
        return f"{self.settings.gemini_base_url}{path}?{query}"


class GroqClient:
    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()

    def chat_json(self, messages: list[dict[str, str]]) -> dict[str, Any]:
        if not self.settings.groq_api_key:
            raise RuntimeError("GROQ_API_KEY is missing. Add it to .env before using LLM SQL generation.")

        payload = {
            "model": self.settings.groq_model,
            "messages": messages,
            "temperature": self.settings.llm_temperature,
            "max_tokens": self.settings.llm_max_tokens,
            "response_format": {"type": "json_object"},
        }
        url = f"{self.settings.groq_base_url}/openai/v1/chat/completions"
        request = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.settings.groq_api_key}",
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                body = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(format_groq_http_error(exc.code, detail, self.settings.groq_model)) from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Could not reach Groq API: {exc.reason}") from exc

        content = extract_groq_text(body)
        return parse_json_object(content)

    def list_models(self) -> dict[str, Any]:
        if not self.settings.groq_api_key:
            raise RuntimeError("GROQ_API_KEY is missing. Add it to .env before checking Groq model access.")

        url = f"{self.settings.groq_base_url}/openai/v1/models"
        request = urllib.request.Request(
            url,
            headers={"Authorization": f"Bearer {self.settings.groq_api_key}"},
            method="GET",
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(format_groq_http_error(exc.code, detail, self.settings.groq_model)) from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Could not reach Groq API: {exc.reason}") from exc


def get_llm_client(settings: Settings | None = None) -> GeminiClient | GroqClient:
    """Get the appropriate LLM client based on settings, with fallback logic."""
    settings = settings or get_settings()

    if settings.ai_provider == "groq":
        return GroqClient(settings)
    elif settings.ai_provider == "gemini":
        return GeminiClient(settings)
    else:
        # Default to Gemini with Groq fallback
        try:
            return GeminiClient(settings)
        except RuntimeError as e:
            error_msg = str(e).lower()
            if ("gemini_api_key" in error_msg or
                "quota" in error_msg or
                "rate limit" in error_msg or
                "429" in error_msg or
                "403" in error_msg):
                # Try Groq as fallback
                try:
                    return GroqClient(settings)
                except RuntimeError:
                    # If both fail, raise the original Gemini error
                    raise e
            else:
                raise e


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
        {"role": "system", "content": build_system_prompt()},
        {
            "role": "user",
            "content": json.dumps(
                {
                    "task": "Generate a safe MySQL SELECT report query from natural language.",
                    "question": question,
                    "user_filters": filters,
                    "row_limit": max(1, min(int(limit), 1000)),
                    "reporting_metadata": build_compact_report_metadata(metadata),
                    "live_schema_summary": build_compact_live_schema(schema_summary),
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
    raw_plan = client.chat_json(messages)
    return LlmSqlPlan(
        report_id=str(raw_plan.get("report_id") or ""),
        report_name=str(raw_plan.get("report_name") or ""),
        sql=str(raw_plan.get("sql") or ""),
        params=dict(raw_plan.get("params") or {}),
        expected_columns=list(raw_plan.get("expected_columns") or []),
        report_title=str(raw_plan.get("report_title") or ""),
        report_summary=str(raw_plan.get("report_summary") or ""),
        warnings=list(raw_plan.get("warnings") or []),
    )


def generate_report_narrative(
    question: str,
    plan: LlmSqlPlan,
    rows: list[dict[str, Any]],
    client: GeminiClient | GroqClient | None = None,
) -> str:
    client = client or get_llm_client()
    preview_rows = rows[:50]
    messages = [
        {
            "role": "system",
            "content": (
                "You generate concise business report summaries from SQL result rows. "
                "Do not invent facts. If rows are empty, say no rows matched. "
                "Return JSON only: {\"generated_report\": \"...\"}."
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
                    "rows_preview": preview_rows,
                },
                default=str,
                ensure_ascii=True,
            ),
        },
    ]
    raw = client.chat_json(messages)
    return str(raw.get("generated_report") or "")


def build_system_prompt() -> str:
    return (
        "You are the SQL generation engine for a read-only MySQL reporting backend. "
        "You must understand the provided database schema, table descriptions, column meanings, relationships, "
        "and business logic before writing SQL. "
        "Only generate reports from reporting_metadata.reports. "
        "Use reporting_metadata only for business meaning and report intent. "
        "Use live_schema_summary from MySQL information_schema as the only source of truth for table and column names. "
        "CRITICAL: Before selecting ANY column, verify that it appears in live_schema_summary. "
        "Never use a table.column pair unless that exact column is listed under that exact table in live_schema_summary. "
        "For attendance reports, prefer columns directly on attendances such as attendances.name, attendances.employee_id, attendances.total_hours, attendances.status, attendances.date, attendances.department, attendances.designation, and attendances.for_month when present. "
        "For timesheet reports, only use columns that appear in live_schema_summary for timelog_records and related tables. "
        "Do not join attendances to users unless live_schema_summary shows a real join column such as attendances.user_id. "
        "Do not use table aliases; always reference columns as table.column so the backend can validate them. "
        "Generate MySQL SQL only. Never use SQLite functions such as STRFTIME. Use MySQL DATE_FORMAT(date_column, '%Y-%m') for month filtering. "
        "When filtering by date range or month, ALWAYS use named parameters. For example: WHERE DATE_FORMAT(column, '%Y-%m') = :date_month or WHERE column BETWEEN :date_from AND :date_to. "
        "All parameters in the SQL must exactly match the keys in the params object you return. Do not use Python string formatting like '%s' in SQL - use named parameters only. "
        "Only select columns that are explicitly listed in live_schema_summary. If a column is not listed, do not use it. "
        "If a useful field is missing from the live schema, omit that field and explain it in warnings instead of inventing the column. "
        "Generate exactly one SELECT query. Never generate INSERT, UPDATE, DELETE, DROP, ALTER, CREATE, TRUNCATE, CALL, or multiple statements. "
        "Use named parameters for every user value. Include a :limit parameter and LIMIT :limit. "
        "For unsupported or ambiguous requests, return the closest allowed report_id only when it is clearly one of the approved V1 reports; otherwise return report_id as empty, sql as empty, and explain in warnings. "
        "Return one JSON object only. No markdown."
    )


def build_compact_live_schema(schema_summary: dict[str, Any] | None) -> dict[str, Any]:
    if not schema_summary:
        return {}
    return {
        "database": schema_summary.get("database"),
        "tables": {
            table_name: [column["name"] for column in table.get("columns", [])]
            for table_name, table in schema_summary.get("tables", {}).items()
        },
    }


def build_compact_report_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    return {
        "reports": {
            report_id: {
                "name": report.get("name"),
                "description": report.get("description"),
                "allowed_filters": report.get("allowed_filters", []),
                "business_logic": report.get("business_logic", []),
            }
            for report_id, report in metadata.get("reports", {}).items()
        }
    }


def extract_gemini_text(body: dict[str, Any]) -> str:
    candidates = body.get("candidates") or []
    if not candidates:
        raise ValueError(f"Gemini response did not include candidates: {body}")

    parts = candidates[0].get("content", {}).get("parts", [])
    text_parts = [part.get("text", "") for part in parts if part.get("text")]
    if not text_parts:
        raise ValueError(f"Gemini response did not include text content: {body}")
    return "\n".join(text_parts)


def parse_json_object(content: str) -> dict[str, Any]:
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        match = JSON_OBJECT_PATTERN.search(content)
        if not match:
            raise ValueError("LLM response did not contain a JSON object.")
        return json.loads(match.group(0))


def format_gemini_http_error(status_code: int, detail: str, model: str) -> str:
    base = f"Gemini API error {status_code}: {detail}"
    if status_code in {400, 403, 404}:
        return (
            f"{base}\n"
            "This happened before SQL execution. Check GEMINI_API_KEY, Google AI Studio API access, "
            f"and whether the configured model '{model}' is available to the key/project. "
            "Try GET /llm/health to verify Gemini access without sending database rows."
        )
    return base


def extract_groq_text(body: dict[str, Any]) -> str:
    choices = body.get("choices") or []
    if not choices:
        raise ValueError(f"Groq response did not include choices: {body}")

    message = choices[0].get("message", {})
    content = message.get("content", "")
    if not content:
        raise ValueError(f"Groq response did not include content: {body}")
    return content


def format_groq_http_error(status_code: int, detail: str, model: str) -> str:
    base = f"Groq API error {status_code}: {detail}"
    if status_code in {400, 401, 403}:
        return (
            f"{base}\n"
            "This happened before SQL execution. Check GROQ_API_KEY "
            f"and whether the configured model '{model}' is available. "
            "Try GET /llm/health to verify Groq access without sending database rows."
        )
    return base
