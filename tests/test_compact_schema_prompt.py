import unittest

from app.llm import build_compact_live_schema


class CompactSchemaPromptTest(unittest.TestCase):
    def test_compact_schema_lists_only_live_column_names(self):
        schema = {
            "database": "db",
            "tables": {
                "attendances": {
                    "columns": [
                        {"name": "date", "type": "date"},
                        {"name": "total_hours", "type": "varchar"},
                    ]
                }
            },
        }
        compact = build_compact_live_schema(schema)
        self.assertEqual(compact["tables"]["attendances"], ["date", "total_hours"])


if __name__ == "__main__":
    unittest.main()
