from __future__ import annotations

import csv
import io
from typing import Any

from fastapi import FastAPI, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.database import fetch_rows, get_schema_summary, invalidate_schema_cache
from app.llm import MistralClient, generate_report_narrative, generate_sql_plan, get_llm_client
from app.metadata import get_report, list_reports, load_reporting_metadata, reconcile_metadata_with_live_schema
from app.models import ReportQueryRequest, ReportResponse, ReportRunRequest
from app.sql_builder import validate_llm_sql, validate_llm_sql_against_live_schema


app = FastAPI(
    title="Devita Reporting Backend",
    version="1.0.0",
    description="Natural-language → SQL reporting system for the Devita Project Management database.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Health & diagnostics
# ---------------------------------------------------------------------------

@app.get("/health", tags=["Health"])
def health() -> dict[str, str]:
    """Simple liveness check."""
    return {"status": "ok"}


@app.get("/schema/summary", tags=["Schema"])
def schema_summary() -> dict[str, Any]:
    """Return the live database schema introspected from information_schema."""
    try:
        return get_schema_summary()
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.post("/schema/refresh", tags=["Schema"])
def schema_refresh() -> dict[str, str]:
    """Force-refresh the schema cache (useful after migrations)."""
    invalidate_schema_cache()
    get_schema_summary()
    return {"status": "schema cache refreshed"}


@app.get("/schema/effective-metadata", tags=["Schema"])
def schema_effective_metadata() -> dict[str, Any]:
    """
    Return the merged metadata that is actually sent to the LLM —
    documented business logic + live column names from MySQL.
    """
    schema = _safe_schema_summary()
    metadata = reconcile_metadata_with_live_schema(load_reporting_metadata(), schema)
    return {
        "source": "mysql_information_schema",
        "database": schema.get("database") if schema else None,
        "note": (
            "This is the metadata sent to the LLM after replacing stale "
            "documented columns with live database columns."
        ),
        "metadata": metadata,
    }


@app.get("/llm/health", tags=["LLM"])
def llm_health() -> dict[str, Any]:
    """Check connectivity and model availability for configured LLM providers."""
    settings = get_settings()
    result: dict[str, Any] = {
        "configured_provider": settings.ai_provider,
        "providers": {},
    }

    # Mistral
    try:
        client = MistralClient(settings)
        payload = client.list_models()
        model_ids = sorted(
            m.get("id", "") for m in payload.get("data", []) if m.get("id")
        )
        result["providers"]["mistral"] = {
            "status": "available",
            "configured_model": settings.mistral_model,
            "configured_model_available": any(settings.mistral_model in m for m in model_ids),
            "available_model_count": len(model_ids),
            "sample_models": model_ids[:10],
        }
    except Exception as exc:
        result["providers"]["mistral"] = {"status": "unavailable", "error": str(exc)}

    try:
        active = get_llm_client(settings)
        result["active_provider"] = "mistral" if isinstance(active, MistralClient) else "none"
    except Exception as exc:
        result["active_provider"] = "none"
        result["error"] = str(exc)
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    return result


# ---------------------------------------------------------------------------
# Report catalogue
# ---------------------------------------------------------------------------

@app.get("/reports", tags=["Reports"])
def reports() -> list[dict[str, Any]]:
    """List all available pre-defined reports."""
    return list_reports()


# ---------------------------------------------------------------------------
# Query endpoints
# ---------------------------------------------------------------------------

@app.post("/reports/query", response_model=ReportResponse, tags=["Reports"])
def query_report(request: ReportQueryRequest):
    """
    Convert a free-form natural language question into SQL, execute it,
    and return structured results with an AI-generated narrative.

    Example questions:
    - "Show me all employees who were absent this month"
    - "Give me timesheet summary for project X last week"
    - "List all open bugs with high severity"
    """
    return _run_llm_report(
        question=request.question,
        filters=request.filters,
        limit=request.limit,
        response_format=request.format,
    )


@app.post("/reports/{report_id}/run", response_model=ReportResponse, tags=["Reports"])
def run_report(report_id: str, request: ReportRunRequest):
    """Run a specific pre-defined report by its ID with optional filters."""
    report = get_report(report_id)
    if not report:
        return ReportResponse(
            report_id=None,
            report_name=None,
            sql_preview=None,
            applied_filters=request.filters,
            columns=[],
            rows=[],
            warnings=[f"Unsupported report_id: '{report_id}'"],
            clarification=(
                "Use GET /reports to list all valid report IDs."
            ),
        )
    question = request.question or f"Generate the {report['name']} using the provided filters."
    return _run_llm_report(
        question=f"{question}\nUse report_id: {report_id}.",
        filters=request.filters,
        limit=request.limit,
        response_format=request.format,
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _run_llm_report(
    question: str,
    filters: dict[str, Any],
    limit: int,
    response_format: str,
) -> ReportResponse | Response:
    metadata = load_reporting_metadata()
    schema = _safe_schema_summary()
    effective_metadata = reconcile_metadata_with_live_schema(metadata, schema)

    try:
        plan = _generate_validated_sql_plan(question, effective_metadata, schema, filters, limit)
        rows = fetch_rows(plan.sql, plan.params)
        generated_report = generate_report_narrative(question, plan, rows)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    if response_format == "csv":
        return Response(
            content=_rows_to_csv(rows),
            media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="{plan.report_id}.csv"'},
        )

    columns = list(rows[0].keys()) if rows else plan.expected_columns
    return ReportResponse(
        report_id=plan.report_id,
        report_name=plan.report_name,
        sql_preview=plan.sql,
        applied_filters=plan.params,
        columns=columns,
        rows=rows,
        generated_report=generated_report or plan.report_summary,
        warnings=plan.warnings,
    )


def _generate_validated_sql_plan(
    question: str,
    effective_metadata: dict[str, Any],
    schema: dict[str, Any] | None,
    filters: dict[str, Any],
    limit: int,
):
    """Generate SQL from LLM with up to 2 self-correction attempts."""
    last_error: ValueError | None = None
    correction = None

    for attempt in range(2):
        plan = generate_sql_plan(
            question=question,
            metadata=effective_metadata,
            schema_summary=schema,
            filters=filters,
            limit=limit,
            correction=correction,
        )

        if not plan.report_id or not plan.sql:
            raise ValueError(
                plan.warnings[0]
                if plan.warnings
                else "The LLM could not map this question to an approved report."
            )

        if plan.report_id not in effective_metadata.get("reports", {}):
            raise ValueError(f"LLM selected unsupported report_id: '{plan.report_id}'")

        # Clamp limit
        clamped_limit = max(1, min(int(plan.params.get("limit", limit)), 1000))
        # params is a dict from a frozen dataclass — rebuild the plan with corrected limit
        corrected_params = {**plan.params, "limit": clamped_limit}
        from app.llm import LlmSqlPlan
        plan = LlmSqlPlan(
            report_id=plan.report_id,
            report_name=plan.report_name,
            sql=plan.sql,
            params=corrected_params,
            expected_columns=plan.expected_columns,
            report_title=plan.report_title,
            report_summary=plan.report_summary,
            warnings=list(plan.warnings),
        )

        try:
            warns = validate_llm_sql(plan.sql, plan.params)
            warns += validate_llm_sql_against_live_schema(plan.sql, schema)
            # Re-attach warnings (plan is frozen; rebuild once more)
            plan = LlmSqlPlan(
                report_id=plan.report_id,
                report_name=plan.report_name,
                sql=plan.sql,
                params=plan.params,
                expected_columns=plan.expected_columns,
                report_title=plan.report_title,
                report_summary=plan.report_summary,
                warnings=list(plan.warnings) + warns,
            )
            return plan
        except ValueError as exc:
            last_error = exc
            correction = {
                "validation_error": str(exc),
                "instruction": (
                    "Regenerate SQL using ONLY exact table.column names from live_schema_summary. "
                    "Do not repeat the invalid column or table. "
                    f"Attempt {attempt + 1} failed with: {exc}"
                ),
            }

    raise last_error or ValueError("Could not generate a valid SQL plan after 2 attempts.")


def _safe_schema_summary() -> dict[str, Any] | None:
    try:
        return get_schema_summary()
    except Exception:
        return None


def _rows_to_csv(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return ""
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=list(rows[0].keys()))
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue()