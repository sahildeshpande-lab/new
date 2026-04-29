import unittest

from app.metadata import load_reporting_metadata, reconcile_metadata_with_live_schema


class MetadataReconciliationTest(unittest.TestCase):
    def test_replaces_stale_attendance_columns_with_live_columns(self):
        metadata = load_reporting_metadata()
        live_schema = {
            "tables": {
                "attendances": {
                    "columns": [
                        {"name": "id", "type": "bigint"},
                        {"name": "date", "type": "date"},
                        {"name": "total_hours", "type": "varchar"},
                        {"name": "employee_id", "type": "varchar"},
                        {"name": "name", "type": "varchar"},
                        {"name": "status", "type": "varchar"},
                    ]
                },
                "users": {
                    "columns": [
                        {"name": "id", "type": "bigint"},
                        {"name": "name", "type": "varchar"},
                    ]
                },
            }
        }

        reconciled = reconcile_metadata_with_live_schema(metadata, live_schema)
        attendance_columns = reconciled["tables"]["attendances"]["columns"]
        report_intent = reconciled["reports"]["attendance_report"]["sql_intent"]

        self.assertIn("total_hours", attendance_columns)
        self.assertNotIn("check_in", attendance_columns)
        self.assertNotIn("check_out", attendance_columns)
        self.assertNotIn("attendances.check_in", report_intent["select_columns"])
        self.assertEqual(report_intent["computed_columns"], [])
        self.assertEqual(report_intent["joins"], [])


if __name__ == "__main__":
    unittest.main()
