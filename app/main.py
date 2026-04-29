from typing import Any

from fastapi import FastAPI, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware

from app.database import fetch_rows, get_schema_summary
from app.config import get_settings
from app.llm import GeminiClient, GroqClient, generate_report_narrative, generate_sql_plan, get_llm_client
from app.metadata import get_report, list_reports, load_reporting_metadata, reconcile_metadata_with_live_schema
from app.models import ReportQueryRequest, ReportResponse, ReportRunRequest
from app.sql_builder import validate_llm_sql, validate_llm_sql_against_live_schema


app = FastAPI(title="Devita Reporting Backend", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allows all origins
    allow_credentials=True,
    allow_methods=["*"],  # Allows all methods
    allow_headers=["*"],  # Allows all headers
)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/schema/summary")
def schema_summary() -> dict[str, Any]:
    try:
        return get_schema_summary()
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.get("/schema/effective-metadata")
def schema_effective_metadata() -> dict[str, Any]:
    schema = _safe_schema_summary()
    metadata = reconcile_metadata_with_live_schema(load_reporting_metadata(), schema)
    return {
        "source": "mysql_information_schema",
        "database": schema.get("database") if schema else None,
        "note": "This is the metadata sent to Gemini after replacing stale documented columns with live database columns.",
        "metadata": metadata,
    }


@app.get("/reports")
def reports() -> list[dict[str, Any]]:
    return list_reports()


@app.get("/llm/health")
def llm_health() -> dict[str, Any]:
    settings = get_settings()
    result = {
        "configured_provider": settings.ai_provider,
        "providers": {},
    }

    # Check Gemini
    try:
        gemini_client = GeminiClient(settings)
        models_payload = gemini_client.list_models()
        model_ids = sorted(
            model.get("name", "").replace("models/", "") for model in models_payload.get("models", []) if model.get("name")
        )
        result["providers"]["gemini"] = {
            "status": "available",
            "base_url": settings.gemini_base_url,
            "configured_model": settings.gemini_model,
            "configured_model_available": settings.gemini_model in model_ids,
            "available_model_count": len(model_ids),
            "available_models_sample": model_ids[:20],
        }
    except Exception as exc:
        result["providers"]["gemini"] = {
            "status": "unavailable",
            "error": str(exc),
        }

    # Check Groq
    try:
        groq_client = GroqClient(settings)
        models_payload = groq_client.list_models()
        model_ids = sorted(
            model.get("id", "") for model in models_payload.get("data", []) if model.get("id")
        )
        result["providers"]["groq"] = {
            "status": "available",
            "base_url": settings.groq_base_url,
            "configured_model": settings.groq_model,
            "configured_model_available": settings.groq_model in model_ids,
            "available_model_count": len(model_ids),
            "available_models_sample": model_ids[:20],
        }
    except Exception as exc:
        result["providers"]["groq"] = {
            "status": "unavailable",
            "error": str(exc),
        }

    # Determine current provider status
    try:
        client = get_llm_client(settings)
        result["current_provider"] = "gemini" if isinstance(client, GeminiClient) else "groq"
        result["database_write_policy"] = "No report or test data is saved to MySQL. The backend only executes validated SELECT statements."
    except Exception as exc:
        result["current_provider"] = "none"
        result["error"] = str(exc)
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    return result


@app.post("/reports/query", response_model=ReportResponse)
def query_report(request: ReportQueryRequest):
    return _run_llm_report(request.question, request.filters, request.limit, request.format)


@app.post("/reports/{report_id}/run", response_model=ReportResponse)
def run_report(report_id: str, request: ReportRunRequest):
    report = get_report(report_id)
    if not report:
        return ReportResponse(
            report_id=None,
            report_name=None,
            sql_preview=None,
            applied_filters=request.filters,
            columns=[],
            rows=[],
            warnings=[f"Unsupported report: {report_id}"],
            clarification="Supported V1 reports are attendance_report, timesheet_report, team_lead_timesheet_report, and hr_timesheet_report.",
        )
    question = request.question or f"Generate {report['name']} using the provided filters."
    return _run_llm_report(f"{question}\nUse report_id: {report_id}.", request.filters, request.limit, request.format)


def _run_llm_report(question: str, filters: dict[str, Any], limit: int, response_format: str):
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
    last_error: ValueError | None = None
    correction = None

    for _ in range(2):
        plan = generate_sql_plan(question, effective_metadata, schema, filters=filters, limit=limit, correction=correction)
        if not plan.report_id or not plan.sql:
            raise ValueError(
                (plan.warnings[0] if plan.warnings else "The LLM could not map this question to an approved V1 report.")
            )
        if plan.report_id not in effective_metadata["reports"]:
            raise ValueError(f"LLM selected unsupported report: {plan.report_id}")

        plan.params["limit"] = max(1, min(int(plan.params.get("limit", limit)), 1000))
        try:
            validation_warnings = validate_llm_sql(plan.sql, plan.params)
            validation_warnings.extend(validate_llm_sql_against_live_schema(plan.sql, schema))
            plan.warnings.extend(validation_warnings)
            return plan
        except ValueError as exc:
            last_error = exc
            correction = {
                "validation_error": str(exc),
                "instruction": "Regenerate SQL using only exact table.column names from live_schema_summary. Do not repeat the invalid column.",
            }

    raise last_error or ValueError("Could not generate a valid SQL plan.")


def _safe_schema_summary() -> dict[str, Any] | None:
    try:
        return get_schema_summary()
    except Exception:
        return None


def _rows_to_csv(rows: list[dict[str, Any]]) -> str:
    import csv
    import io

    if not rows:
        return ""
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=list(rows[0].keys()))
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue()
