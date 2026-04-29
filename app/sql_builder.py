import re
from dataclasses import dataclass
from typing import Any


READ_ONLY_PATTERN = re.compile(r"^\s*select\b", re.IGNORECASE)
BLOCKED_SQL_PATTERN = re.compile(
    r"\b(insert|update|delete|drop|alter|truncate|create|replace|grant|revoke|merge|call|exec)\b",
    re.IGNORECASE,
)
SQL_TABLE_PATTERN = re.compile(r"\b(?:from|join)\s+`?([a-zA-Z_][a-zA-Z0-9_]*)`?", re.IGNORECASE)
SQL_COLUMN_PATTERN = re.compile(r"\b`?([a-zA-Z_][a-zA-Z0-9_]*)`?\.`?([a-zA-Z_][a-zA-Z0-9_]*)`?\b")
SQL_PARAM_PATTERN = re.compile(r":([a-zA-Z_][a-zA-Z0-9_]*)")
MYSQL_BLOCKED_FUNCTION_PATTERN = re.compile(r"\b(strftime|date_trunc|extract)\s*\(", re.IGNORECASE)
SQL_ALIAS_PATTERN = re.compile(r"\b(?:FROM|JOIN)\s+`?([a-zA-Z_][a-zA-Z0-9_]*)`?\s+(?:AS\s+)?`?([a-zA-Z_][a-zA-Z0-9_]*)`?\b", re.IGNORECASE)


def _resolve_table_name(table_name: str, alias_map: dict[str, str]) -> str:
    return alias_map.get(table_name, table_name)


def _extract_table_aliases(sql: str) -> dict[str, str]:
    alias_map: dict[str, str] = {}
    for table_name, alias in SQL_ALIAS_PATTERN.findall(sql):
        alias_map[alias] = table_name
    return alias_map


@dataclass(frozen=True)
class BuiltQuery:
    sql: str
    params: dict[str, Any]
    columns: list[str]
    warnings: list[str]


FILTER_COLUMN_MAP = {
    "date_from": {
        "attendance_report": "attendances.date",
        "timesheet_report": "timelog_records.date",
        "team_lead_timesheet_report": "timelog_records.date",
        "hr_timesheet_report": "attendances.date",
    },
    "date_to": {
        "attendance_report": "attendances.date",
        "timesheet_report": "timelog_records.date",
        "team_lead_timesheet_report": "timelog_records.date",
        "hr_timesheet_report": "attendances.date",
    },
    "user_id": {
        "attendance_report": "users.id",
        "timesheet_report": "users.id",
        "hr_timesheet_report": "users.id",
    },
    "employee_name": {
        "attendance_report": "users.name",
        "hr_timesheet_report": "users.name",
    },
    "status": {
        "attendance_report": "attendances.status",
        "hr_timesheet_report": "attendances.status",
    },
    "project_id": {
        "timesheet_report": "projects.id",
        "team_lead_timesheet_report": "projects.id",
    },
    "client": {
        "timesheet_report": "projects.client",
        "team_lead_timesheet_report": "projects.client",
    },
    "team_leader_id": {
        "team_lead_timesheet_report": "projects.team_leader",
    },
    "project_mfg_type": {
        "team_lead_timesheet_report": "projects.project_mfg_type",
    },
}


def build_report_query(
    report_id: str,
    report: dict[str, Any],
    filters: dict[str, Any] | None = None,
    limit: int = 100,
) -> BuiltQuery:
    filters = filters or {}
    sql_intent = report["sql_intent"]
    warnings: list[str] = []

    select_parts = [f"{column} AS {alias_for(column)}" for column in sql_intent.get("select_columns", [])]
    select_parts.extend(
        f"{computed['expression']} AS {computed['name']}" for computed in sql_intent.get("computed_columns", [])
    )

    sql_parts = [
        "SELECT",
        "  " + ",\n  ".join(select_parts),
        f"FROM {sql_intent['base_table']}",
    ]

    for join in sql_intent.get("joins", []):
        join_type = join.get("type", "left").upper()
        if join_type not in {"LEFT", "INNER"}:
            warnings.append(f"Unsupported join type {join_type}; using LEFT JOIN.")
            join_type = "LEFT"
        sql_parts.append(f"{join_type} JOIN {join['table']} ON {join['on']}")

    where_clauses: list[str] = []
    params: dict[str, Any] = {}
    allowed_filters = set(report["allowed_filters"])

    for filter_name, value in filters.items():
        if value in (None, ""):
            continue
        if filter_name not in allowed_filters:
            warnings.append(f"Ignored unsupported filter: {filter_name}")
            continue

        column = FILTER_COLUMN_MAP.get(filter_name, {}).get(report_id)
        if not column:
            warnings.append(f"Ignored filter without SQL mapping: {filter_name}")
            continue

        if filter_name == "date_from":
            where_clauses.append(f"{column} >= :date_from")
            params["date_from"] = value
        elif filter_name == "date_to":
            where_clauses.append(f"{column} <= :date_to")
            params["date_to"] = value
        elif filter_name in {"employee_name", "client"}:
            where_clauses.append(f"{column} LIKE :{filter_name}")
            params[filter_name] = f"%{value}%"
        elif filter_name == "team_leader_id":
            where_clauses.append(f"JSON_SEARCH(CAST({column} AS JSON), 'one', CAST(:team_leader_id AS CHAR)) IS NOT NULL")
            params[filter_name] = value
        else:
            where_clauses.append(f"{column} = :{filter_name}")
            params[filter_name] = value

    if report_id == "team_lead_timesheet_report":
        where_clauses.append("(product_task.is_deleted IS NULL OR product_task.is_deleted = 0)")

    if where_clauses:
        sql_parts.append("WHERE " + "\n  AND ".join(where_clauses))

    if _requires_group_by(report_id):
        group_columns = _group_by_columns(report_id)
        sql_parts.append("GROUP BY " + ", ".join(group_columns))

    sort_parts = [f"{sort['column']} {sort['direction'].upper()}" for sort in report.get("default_sort", [])]
    if sort_parts:
        sql_parts.append("ORDER BY " + ", ".join(sort_parts))

    safe_limit = max(1, min(int(limit), 1000))
    sql_parts.append("LIMIT :limit")
    params["limit"] = safe_limit

    sql = "\n".join(sql_parts)
    assert_select_only(sql)
    return BuiltQuery(sql=sql, params=params, columns=[alias_for(column) for column in sql_intent.get("select_columns", [])], warnings=warnings)


def assert_select_only(sql: str) -> None:
    if ";" in sql.strip().rstrip(";"):
        raise ValueError("Only one SELECT statement is allowed.")
    if not READ_ONLY_PATTERN.search(sql) or BLOCKED_SQL_PATTERN.search(sql):
        raise ValueError("Only read-only SELECT statements are allowed.")


def validate_llm_sql(sql: str, params: dict[str, Any], metadata: dict[str, Any] | None = None) -> list[str]:
    assert_select_only(sql)
    warnings: list[str] = []

    used_tables = set(SQL_TABLE_PATTERN.findall(sql))
    if not used_tables:
        raise ValueError("Generated SQL does not include a FROM table.")

    if metadata is not None:
        declared_tables = metadata["tables"]
        unknown_tables = used_tables.difference(declared_tables)
        if unknown_tables:
            raise ValueError(f"Generated SQL references undeclared tables: {', '.join(sorted(unknown_tables))}")

        for table_name, column_name in SQL_COLUMN_PATTERN.findall(sql):
            if table_name not in declared_tables:
                raise ValueError(f"Generated SQL references undeclared table: {table_name}")
            if column_name not in declared_tables[table_name]["columns"]:
                raise ValueError(f"Generated SQL references undeclared column: {table_name}.{column_name}")

    used_params = set(SQL_PARAM_PATTERN.findall(sql))
    missing_params = used_params.difference(params)
    if missing_params:
        raise ValueError(f"Generated SQL is missing parameter values: {', '.join(sorted(missing_params))}")

    null_params = [name for name in used_params if params.get(name) is None]
    if null_params:
        raise ValueError(f"Generated SQL contains null values for parameters: {', '.join(sorted(null_params))}")

    extra_params = set(params).difference(used_params)
    if extra_params:
        warnings.append(f"LLM returned unused params: {', '.join(sorted(extra_params))}")

    if "limit" not in used_params:
        raise ValueError("Generated SQL must use a :limit parameter.")

    return warnings


def validate_llm_sql_against_live_schema(sql: str, schema_summary: dict[str, Any] | None) -> list[str]:
    warnings = []
    
    if not schema_summary:
        return ["Live schema validation was skipped because schema summary was unavailable."]

    if MYSQL_BLOCKED_FUNCTION_PATTERN.search(sql):
        raise ValueError("Generated SQL uses a non-MySQL date/function. Use MySQL functions such as DATE_FORMAT, YEAR, MONTH, TIMEDIFF, TIME_TO_SEC, or SEC_TO_TIME.")

    live_tables = schema_summary.get("tables", {})
    used_tables = set(SQL_TABLE_PATTERN.findall(sql))
    missing_tables = used_tables.difference(live_tables)
    if missing_tables:
        raise ValueError(f"Generated SQL references tables missing from live database: {', '.join(sorted(missing_tables))}")

    alias_map = _extract_table_aliases(sql)
    for table_name, column_name in SQL_COLUMN_PATTERN.findall(sql):
        actual_table = _resolve_table_name(table_name, alias_map)
        live_columns = {column["name"] for column in live_tables.get(actual_table, {}).get("columns", [])}
        if column_name not in live_columns:
            raise ValueError(f"Generated SQL references column missing from live database: {actual_table}.{column_name}")

    return warnings


def alias_for(column_ref: str) -> str:
    return column_ref.replace(".", "__")


def _requires_group_by(report_id: str) -> bool:
    return report_id == "hr_timesheet_report"


def _group_by_columns(report_id: str) -> list[str]:
    if report_id == "hr_timesheet_report":
        return ["users.id", "users.name", "users.employee_id", "users.status"]
    return []
