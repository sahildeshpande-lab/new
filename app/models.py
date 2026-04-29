from typing import Any, Literal

try:
    from pydantic import BaseModel, Field
except ImportError:  # pragma: no cover - helps non-API unit tests explain missing deps cleanly.
    BaseModel = object  # type: ignore

    def Field(default=None, **_: Any):  
        return default


class ReportQueryRequest(BaseModel):
    question: str = Field(..., min_length=1)
    filters: dict[str, Any] = Field(default_factory=dict)
    format: Literal["json", "csv"] = "json"
    limit: int = Field(default=100, ge=1, le=1000)


class ReportRunRequest(BaseModel):
    filters: dict[str, Any] = Field(default_factory=dict)
    format: Literal["json", "csv"] = "json"
    limit: int = Field(default=100, ge=1, le=1000)
    question: str | None = None


class ReportResponse(BaseModel):
    report_id: str | None
    report_name: str | None
    sql_preview: str | None
    applied_filters: dict[str, Any]
    columns: list[str]
    rows: list[dict[str, Any]]
    generated_report: str | None = None
    warnings: list[str] = Field(default_factory=list)
    clarification: str | None = None
