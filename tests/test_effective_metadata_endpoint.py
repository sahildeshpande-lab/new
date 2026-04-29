import unittest
from unittest.mock import patch

try:
    from app.main import schema_effective_metadata
except ModuleNotFoundError as exc:
    if exc.name != "fastapi":
        raise
    schema_effective_metadata = None


class EffectiveMetadataEndpointTest(unittest.TestCase):
    @unittest.skipIf(schema_effective_metadata is None, "FastAPI is not installed in this test environment.")
    def test_returns_reconciled_metadata_source(self):
        schema = {
            "database": "example_db",
            "tables": {
                "attendances": {
                    "columns": [
                        {"name": "id", "type": "bigint"},
                        {"name": "date", "type": "date"},
                        {"name": "total_hours", "type": "varchar"},
                    ]
                }
            },
        }
        with patch("app.main._safe_schema_summary", return_value=schema):
            response = schema_effective_metadata()

        self.assertEqual(response["source"], "mysql_information_schema")
        self.assertEqual(response["database"], "example_db")
        self.assertIn("metadata", response)


if __name__ == "__main__":
    unittest.main()
