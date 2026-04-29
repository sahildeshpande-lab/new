from __future__ import annotations

import time
from typing import Any

from app.config import get_settings
from app.database import get_schema_summary

_metadata_cache: dict[str, Any] | None = None
_metadata_cache_time: float = 0


# ---------------------------------------------------------------------------
# Dynamic Metadata Generation
# ---------------------------------------------------------------------------

def load_reporting_metadata() -> dict[str, Any]:
    """
    Generate reporting metadata dynamically from the live database schema.
    Refreshes according to schema_cache_ttl.
    """
    global _metadata_cache, _metadata_cache_time
    s = get_settings()
    now = time.time()

    if _metadata_cache is not None:
        if (now - _metadata_cache_time) < s.schema_cache_ttl:
            return _metadata_cache

    schema = get_schema_summary()
    reports = {}

    # Generate a report for each table in the schema
    for table_name, table_info in schema.get("tables", {}).items():
        report_id = f"report_{table_name}"
        columns = [col["name"] for col in table_info.get("columns", [])]
        
        reports[report_id] = {
            "name": f"{table_name.replace('_', ' ').title()} Report",
            "description": f"Standard report for the {table_name} table.",
            "allowed_filters": columns,
            "business_logic": [
                f"Query the {table_name} table.",
                f"Available columns: {', '.join(columns)}"
            ],
            "tables": {
                table_name: {
                    "description": f"Base table for {table_name}",
                    "live_columns": columns
                }
            }
        }

    _metadata_cache = {"reports": reports}
    _metadata_cache_time = now
    return _metadata_cache


def reload_metadata() -> dict[str, Any]:
    global _metadata_cache
    _metadata_cache = None
    return load_reporting_metadata()


# ---------------------------------------------------------------------------
# Report lookups
# ---------------------------------------------------------------------------

def list_reports() -> list[dict[str, Any]]:
    metadata = load_reporting_metadata()
    return [
        {
            "report_id": rid,
            "name": r.get("name"),
            "description": r.get("description"),
            "allowed_filters": r.get("allowed_filters", []),
        }
        for rid, r in metadata.get("reports", {}).items()
    ]


def get_report(report_id: str) -> dict[str, Any] | None:
    metadata = load_reporting_metadata()
    return metadata.get("reports", {}).get(report_id)


# ---------------------------------------------------------------------------
# Reconcile metadata with live schema
# ---------------------------------------------------------------------------

def reconcile_metadata_with_live_schema(
    metadata: dict[str, Any],
    schema_summary: dict[str, Any] | None,
) -> dict[str, Any]:
    """
    Since metadata is now generated directly from live schema, 
    reconciliation is technically redundant but kept for API compatibility.
    """
    return metadata