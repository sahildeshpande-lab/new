from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ReportQueryRequest(BaseModel):
    """Free-form natural language query."""
    question: str = Field(..., min_length=3, description="Natural language question about the data.")
    filters: dict[str, Any] = Field(default_factory=dict, description="Optional key-value filters (e.g. date_from, department).")
    limit: int = Field(default=100, ge=1, le=1000, description="Maximum number of rows to return.")
    format: str = Field(default="json", description="Response format: 'json' or 'csv'.")


class ReportRunRequest(BaseModel):
    """Run a specific pre-defined report by ID."""
    question: str | None = Field(default=None, description="Optional override question.")
    filters: dict[str, Any] = Field(default_factory=dict)
    limit: int = Field(default=100, ge=1, le=1000)
    format: str = Field(default="json")


class ReportResponse(BaseModel):
    report_id: str | None = None
    report_name: str | None = None
    sql_preview: str | None = None
    applied_filters: dict[str, Any] = Field(default_factory=dict)
    columns: list[str] = Field(default_factory=list)
    rows: list[dict[str, Any]] = Field(default_factory=list)
    row_count: int = 0
    generated_report: str | None = None
    warnings: list[str] = Field(default_factory=list)
    clarification: str | None = None

    def model_post_init(self, __context: Any) -> None:
        object.__setattr__(self, "row_count", len(self.rows))