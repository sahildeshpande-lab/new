import unittest

from app.metadata import load_reporting_metadata
from app.sql_builder import assert_select_only, build_report_query, validate_llm_sql


class SqlBuilderTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.metadata = load_reporting_metadata()

    def test_builds_attendance_query_with_bound_filters(self):
        report = self.metadata["reports"]["attendance_report"]
        built = build_report_query(
            "attendance_report",
            report,
            filters={"date_from": "2026-03-01", "date_to": "2026-03-31", "employee_name": "Amit"},
            limit=25,
        )
        self.assertTrue(built.sql.strip().lower().startswith("select"))
        self.assertIn("attendances.date >= :date_from", built.sql)
        self.assertIn("users.name LIKE :employee_name", built.sql)
        self.assertEqual(built.params["employee_name"], "%Amit%")
        self.assertEqual(built.params["limit"], 25)

    def test_ignores_unsupported_filters(self):
        report = self.metadata["reports"]["attendance_report"]
        built = build_report_query("attendance_report", report, filters={"client": "DAI"}, limit=10)
        self.assertTrue(any("Ignored unsupported filter" in warning for warning in built.warnings))
        self.assertNotIn(":client", built.sql)

    def test_blocks_write_sql(self):
        with self.assertRaises(ValueError):
            assert_select_only("DELETE FROM users")

    def test_blocks_multiple_sql_statements(self):
        with self.assertRaises(ValueError):
            assert_select_only("SELECT * FROM users; DELETE FROM users")

    def test_llm_sql_must_reference_declared_columns(self):
        with self.assertRaises(ValueError):
            validate_llm_sql("SELECT users.salary FROM users LIMIT :limit", {"limit": 10}, self.metadata)

    def test_builds_only_declared_reports(self):
        for report_id, report in self.metadata["reports"].items():
            with self.subTest(report_id=report_id):
                built = build_report_query(report_id, report, filters={}, limit=10)
                self.assertTrue(built.sql.strip().lower().startswith("select"))
                self.assertEqual(built.params["limit"], 10)


if __name__ == "__main__":
    unittest.main()
