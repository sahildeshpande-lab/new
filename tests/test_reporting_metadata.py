import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
METADATA_PATH = ROOT / "reporting_metadata.json"
EXPECTED_REPORTS = {
    "attendance_report",
    "timesheet_report",
    "team_lead_timesheet_report",
    "hr_timesheet_report",
}


class ReportingMetadataTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.metadata = json.loads(METADATA_PATH.read_text(encoding="utf-8"))

    def test_metadata_loads(self):
        self.assertEqual(self.metadata["database"]["engine"], "mysql")
        self.assertEqual(self.metadata["database"]["access_policy"]["mode"], "read_only")

    def test_v1_report_scope_is_limited_to_four_reports(self):
        self.assertEqual(set(self.metadata["reports"]), EXPECTED_REPORTS)

    def test_reports_have_required_contract_fields(self):
        for report_id, report in self.metadata["reports"].items():
            with self.subTest(report_id=report_id):
                self.assertTrue(report["name"])
                self.assertTrue(report["description"])
                self.assertTrue(report["natural_language_aliases"])
                self.assertTrue(report["required_tables"])
                self.assertTrue(report["allowed_filters"])
                self.assertTrue(report["business_logic"])
                self.assertIn("sql_intent", report)

    def test_report_required_tables_are_declared(self):
        declared_tables = set(self.metadata["tables"])
        for report_id, report in self.metadata["reports"].items():
            with self.subTest(report_id=report_id):
                self.assertTrue(set(report["required_tables"]).issubset(declared_tables))

    def test_sql_intent_references_only_declared_tables_and_columns(self):
        tables = self.metadata["tables"]
        for report_id, report in self.metadata["reports"].items():
            with self.subTest(report_id=report_id):
                sql_intent = report["sql_intent"]
                self.assertIn(sql_intent["base_table"], tables)

                for join in sql_intent.get("joins", []):
                    self.assertIn(join["table"], tables)
                    self.assertTrue(join["on"])

                for column_ref in sql_intent.get("select_columns", []):
                    table_name, column_name = column_ref.split(".", 1)
                    self.assertIn(table_name, tables)
                    self.assertIn(column_name, tables[table_name]["columns"])

                for sort in report.get("default_sort", []):
                    table_name, column_name = sort["column"].split(".", 1)
                    self.assertIn(table_name, tables)
                    self.assertIn(column_name, tables[table_name]["columns"])
                    self.assertIn(sort["direction"], {"asc", "desc"})

    def test_table_relationships_reference_declared_tables_and_columns(self):
        tables = self.metadata["tables"]
        for table_name, table in tables.items():
            for relationship in table.get("relationships", []):
                with self.subTest(table_name=table_name, relationship=relationship):
                    self.assertIn(relationship["column"], table["columns"])
                    reference_table, reference_column = relationship["references"].split(".", 1)
                    self.assertIn(reference_table, tables)
                    self.assertIn(reference_column, tables[reference_table]["columns"])


if __name__ == "__main__":
    unittest.main()
