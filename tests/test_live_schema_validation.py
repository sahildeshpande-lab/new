import unittest

from app.sql_builder import validate_llm_sql_against_live_schema


class LiveSchemaValidationTest(unittest.TestCase):
    def test_rejects_missing_live_column(self):
        schema = {
            "tables": {
                "attendances": {"columns": [{"name": "id"}, {"name": "date"}]},
                "users": {"columns": [{"name": "id"}, {"name": "name"}]},
            }
        }
        with self.assertRaises(ValueError):
            validate_llm_sql_against_live_schema(
                "SELECT attendances.date, attendances.check_in FROM attendances LIMIT :limit",
                schema,
            )

    def test_rejects_sqlite_date_function(self):
        schema = {
            "tables": {
                "attendances": {"columns": [{"name": "date"}]},
            }
        }
        with self.assertRaises(ValueError):
            validate_llm_sql_against_live_schema(
                "SELECT attendances.date FROM attendances WHERE STRFTIME('%Y-%m', attendances.date) = '2026-03' LIMIT :limit",
                schema,
            )

    def test_allows_table_aliases(self):
        schema = {
            "tables": {
                "timelog_records": {"columns": [{"name": "id"}, {"name": "date"}]},
            }
        }
        validate_llm_sql_against_live_schema(
            "SELECT tlr.id, tlr.date FROM timelog_records AS tlr LIMIT :limit",
            schema,
        )


if __name__ == "__main__":
    unittest.main()
