from __future__ import annotations

from typing import Any

import pymysql
import pymysql.cursors

from app.config import Settings, get_settings


# ---------------------------------------------------------------------------
# Connection helpers
# ---------------------------------------------------------------------------

def _get_connection(settings: Settings | None = None) -> pymysql.connections.Connection:
    s = settings or get_settings()
    return pymysql.connect(
        host=s.db_host,
        port=s.db_port,
        user=s.db_user,
        password=s.db_password,
        database=s.db_name,
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
        connect_timeout=10,
    )


# ---------------------------------------------------------------------------
# Query execution
# ---------------------------------------------------------------------------

def fetch_rows(sql: str, params: dict[str, Any], settings: Settings | None = None) -> list[dict[str, Any]]:
    """Execute a single SELECT statement with named parameters and return rows."""
    conn = _get_connection(settings)
    try:
        with conn.cursor() as cursor:
            # pymysql uses %(name)s for named parameters
            pymysql_sql = _named_to_pymysql(sql)
            cursor.execute(pymysql_sql, params)
            rows = cursor.fetchall()
            # Convert non-serialisable types (date, Decimal, timedelta …)
            return [_serialize_row(row) for row in rows]
    finally:
        conn.close()


def _named_to_pymysql(sql: str) -> str:
    """Convert :param style to %(param)s style expected by pymysql."""
    import re
    # Escape existing % signs so pymysql doesn't treat them as string formatting parameters
    sql = sql.replace("%", "%%")
    return re.sub(r":([a-zA-Z_][a-zA-Z0-9_]*)", r"%(\1)s", sql)


def _serialize_row(row: dict[str, Any]) -> dict[str, Any]:
    import datetime
    import decimal

    result = {}
    for k, v in row.items():
        if isinstance(v, (datetime.date, datetime.datetime)):
            result[k] = v.isoformat()
        elif isinstance(v, datetime.timedelta):
            total_seconds = int(v.total_seconds())
            h, rem = divmod(total_seconds, 3600)
            m, s = divmod(rem, 60)
            result[k] = f"{h:02d}:{m:02d}:{s:02d}"
        elif isinstance(v, decimal.Decimal):
            result[k] = float(v)
        else:
            result[k] = v
    return result


# ---------------------------------------------------------------------------
# Schema introspection
# ---------------------------------------------------------------------------

import time

_SCHEMA_CACHE: dict[str, Any] | None = None
_SCHEMA_CACHE_TIME: float = 0


def get_schema_summary(settings: Settings | None = None, force_refresh: bool = False) -> dict[str, Any]:
    """
    Introspect the live MySQL database and return a compact schema summary.
    Refreshes automatically if the cache is older than settings.schema_cache_ttl.
    """
    global _SCHEMA_CACHE, _SCHEMA_CACHE_TIME
    s = settings or get_settings()
    now = time.time()

    if not force_refresh and _SCHEMA_CACHE is not None:
        if (now - _SCHEMA_CACHE_TIME) < s.schema_cache_ttl:
            return _SCHEMA_CACHE

    conn = _get_connection(s)
    try:
        with conn.cursor() as cursor:
            # Fetch all columns for all tables in the target database
            cursor.execute(
                """
                SELECT
                    TABLE_NAME        AS table_name,
                    COLUMN_NAME       AS column_name,
                    DATA_TYPE         AS data_type,
                    IS_NULLABLE       AS is_nullable,
                    COLUMN_KEY        AS column_key,
                    COLUMN_DEFAULT    AS column_default,
                    EXTRA             AS extra
                FROM information_schema.COLUMNS
                WHERE TABLE_SCHEMA = %s
                ORDER BY TABLE_NAME, ORDINAL_POSITION
                """,
                (s.db_name,),
            )
            rows = cursor.fetchall()

            if not rows:
                raise ValueError(
                    f"No tables found in database '{s.db_name}'. "
                    "Check DB_NAME in your .env and ensure the schema is migrated."
                )

            tables: dict[str, Any] = {}
            for row in rows:
                tbl = row["table_name"]
                if tbl not in tables:
                    tables[tbl] = {"columns": []}
                tables[tbl]["columns"].append(
                    {
                        "name": row["column_name"],
                        "type": row["data_type"],
                        "nullable": row["is_nullable"] == "YES",
                        "key": row["column_key"] or None,
                        "default": row["column_default"],
                        "extra": row["extra"] or None,
                    }
                )

        _SCHEMA_CACHE = {"database": s.db_name, "tables": tables}
        _SCHEMA_CACHE_TIME = now
        return _SCHEMA_CACHE
    finally:
        conn.close()


def invalidate_schema_cache() -> None:
    global _SCHEMA_CACHE
    _SCHEMA_CACHE = None