import json
import copy
import re
from functools import lru_cache
from pathlib import Path
from typing import Any


ROOT_DIR = Path(__file__).resolve().parents[1]
METADATA_PATH = ROOT_DIR / "reporting_metadata.json"
SQL_COLUMN_REF_PATTERN = re.compile(r"\b([a-zA-Z_][a-zA-Z0-9_]*)\.([a-zA-Z_][a-zA-Z0-9_]*)\b")


@lru_cache(maxsize=1)
def load_reporting_metadata() -> dict[str, Any]:
    return json.loads(METADATA_PATH.read_text(encoding="utf-8"))


def list_reports() -> list[dict[str, Any]]:
    metadata = load_reporting_metadata()
    reports = []
    for report_id, report in metadata["reports"].items():
        reports.append(
            {
                "id": report_id,
                "name": report["name"],
                "description": report["description"],
                "allowed_filters": report["allowed_filters"],
                "required_tables": report["required_tables"],
                "aliases": report.get("natural_language_aliases", []),
            }
        )
    return reports


def get_report(report_id: str) -> dict[str, Any] | None:
    return load_reporting_metadata()["reports"].get(report_id)


def reconcile_metadata_with_live_schema(metadata: dict[str, Any], schema_summary: dict[str, Any] | None) -> dict[str, Any]:
    if not schema_summary:
        return metadata

    reconciled = copy.deepcopy(metadata)
    live_tables = schema_summary.get("tables", {})

    for table_name, live_table in live_tables.items():
        if table_name not in reconciled["tables"]:
            continue

        existing_columns = reconciled["tables"][table_name].get("columns", {})
        live_columns: dict[str, Any] = {}
        for live_column in live_table.get("columns", []):
            column_name = live_column["name"]
            existing = existing_columns.get(column_name, {})
            live_columns[column_name] = {
                "type": live_column.get("type", existing.get("type", "unknown")),
                "description": existing.get("description", f"Live database column {table_name}.{column_name}."),
                "semantic_role": existing.get("semantic_role", "live_schema_column"),
                "nullable": live_column.get("nullable"),
                "key": live_column.get("key"),
            }

        reconciled["tables"][table_name]["columns"] = live_columns
        reconciled["tables"][table_name]["relationships"] = [
            relationship
            for relationship in reconciled["tables"][table_name].get("relationships", [])
            if _relationship_exists_in_live_schema(relationship, table_name, live_tables)
        ]

    for report in reconciled["reports"].values():
        sql_intent = report.get("sql_intent", {})
        sql_intent["select_columns"] = [
            column_ref
            for column_ref in sql_intent.get("select_columns", [])
            if _column_ref_exists_in_live_schema(column_ref, live_tables)
        ]
        sql_intent["joins"] = [
            join
            for join in sql_intent.get("joins", [])
            if join.get("table") in live_tables and _all_expression_columns_exist(join.get("on", ""), live_tables)
        ]
        sql_intent["computed_columns"] = [
            computed
            for computed in sql_intent.get("computed_columns", [])
            if _all_expression_columns_exist(computed.get("expression", ""), live_tables)
        ]
        report["default_sort"] = [
            sort
            for sort in report.get("default_sort", [])
            if _column_ref_exists_in_live_schema(sort.get("column", ""), live_tables)
        ]

    return reconciled


def _relationship_exists_in_live_schema(relationship: dict[str, Any], table_name: str, live_tables: dict[str, Any]) -> bool:
    reference = relationship.get("references", "")
    if "." not in reference:
        return False
    reference_table, reference_column = reference.split(".", 1)
    return _live_table_has_column(live_tables, table_name, relationship.get("column", "")) and _live_table_has_column(
        live_tables, reference_table, reference_column
    )


def _column_ref_exists_in_live_schema(column_ref: str, live_tables: dict[str, Any]) -> bool:
    if "." not in column_ref:
        return False
    table_name, column_name = column_ref.split(".", 1)
    return _live_table_has_column(live_tables, table_name, column_name)


def _all_expression_columns_exist(expression: str, live_tables: dict[str, Any]) -> bool:
    return all(_live_table_has_column(live_tables, table_name, column_name) for table_name, column_name in SQL_COLUMN_REF_PATTERN.findall(expression))


def _live_table_has_column(live_tables: dict[str, Any], table_name: str, column_name: str) -> bool:
    live_table = live_tables.get(table_name)
    if not live_table:
        return False
    return column_name in {column["name"] for column in live_table.get("columns", [])}
