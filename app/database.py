from typing import Any

from app.config import Settings, get_settings
from app.sql_builder import assert_select_only


def _create_engine(settings: Settings | None = None):
    try:
        from sqlalchemy import create_engine
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("SQLAlchemy is not installed. Run: pip install -r requirements.txt") from exc

    settings = settings or get_settings()
    connect_args: dict[str, Any] = {}
    if settings.mysql_ssl_disabled:
        connect_args["ssl_disabled"] = True
    return create_engine(settings.sqlalchemy_url, pool_pre_ping=True, connect_args=connect_args)


def fetch_rows(sql: str, params: dict[str, Any], settings: Settings | None = None) -> list[dict[str, Any]]:
    try:
        from sqlalchemy import text
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("SQLAlchemy is not installed. Run: pip install -r requirements.txt") from exc

    assert_select_only(sql)
    engine = _create_engine(settings)
    with engine.connect() as connection:
        result = connection.execute(text(sql), params)
        return [dict(row._mapping) for row in result]


def get_schema_summary(settings: Settings | None = None) -> dict[str, Any]:
    settings = settings or get_settings()
    sql = """
SELECT
  c.TABLE_NAME AS table_name,
  c.COLUMN_NAME AS column_name,
  c.DATA_TYPE AS data_type,
  c.IS_NULLABLE AS is_nullable,
  c.COLUMN_KEY AS column_key,
  c.COLUMN_DEFAULT AS column_default
FROM information_schema.COLUMNS c
WHERE c.TABLE_SCHEMA = :database_name
ORDER BY c.TABLE_NAME, c.ORDINAL_POSITION
"""
    rows = fetch_rows(sql, {"database_name": settings.mysql_database}, settings=settings)
    tables: dict[str, Any] = {}
    for row in rows:
        table = tables.setdefault(row["table_name"], {"columns": []})
        table["columns"].append(
            {
                "name": row["column_name"],
                "type": row["data_type"],
                "nullable": row["is_nullable"] == "YES",
                "key": row["column_key"],
                "default": row["column_default"],
            }
        )
    return {"database": settings.mysql_database, "tables": tables}
