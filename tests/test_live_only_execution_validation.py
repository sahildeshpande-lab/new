import unittest

from app.sql_builder import validate_llm_sql, validate_llm_sql_against_live_schema


class LiveOnlyExecutionValidationTest(unittest.TestCase):
    def test_base_validation_does_not_require_static_metadata(self):
        warnings = validate_llm_sql(
            "SELECT attendances.user_id FROM attendances LIMIT :limit",
            {"limit": 10},
        )
        self.assertEqual(warnings, [])

    def test_live_schema_is_the_column_authority(self):
        schema = {
            "tables": {
                "attendances": {
                    "columns": [
                        {"name": "id"},
                        {"name": "user_id"},
                    ]
                }
            }
        }
        warnings = validate_llm_sql_against_live_schema(
            "SELECT attendances.user_id FROM attendances LIMIT :limit",
            schema,
        )
        self.assertEqual(warnings, [])


if __name__ == "__main__":
    unittest.main()
