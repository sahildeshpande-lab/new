import unittest
from datetime import date

from app.metadata import load_reporting_metadata
from app.nl_router import extract_filters, match_report


class NaturalLanguageRouterTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.metadata = load_reporting_metadata()

    def test_matches_attendance_report(self):
        report_id, warnings = match_report("show attendance report for March", self.metadata)
        self.assertEqual(report_id, "attendance_report")
        self.assertEqual(warnings, [])

    def test_matches_timesheet_report(self):
        report_id, warnings = match_report("employee timesheet for project 12", self.metadata)
        self.assertEqual(report_id, "timesheet_report")
        self.assertEqual(warnings, [])

    def test_rejects_unsupported_report(self):
        report_id, warnings = match_report("show dai week five report", self.metadata)
        self.assertIsNone(report_id)
        self.assertTrue(warnings)

    def test_extracts_month_filter(self):
        filters = extract_filters(
            "show attendance report for March 2026",
            self.metadata["reports"]["attendance_report"]["allowed_filters"],
            today=date(2026, 4, 29),
        )
        self.assertEqual(filters["date_from"], "2026-03-01")
        self.assertEqual(filters["date_to"], "2026-03-31")

    def test_extracts_ids_and_project_filters(self):
        filters = extract_filters(
            "timesheet report from 2026-03-01 to 2026-03-31 project 42 work type Modeling role type Developer",
            self.metadata["reports"]["timesheet_report"]["allowed_filters"],
            today=date(2026, 4, 29),
        )
        self.assertEqual(filters["date_from"], "2026-03-01")
        self.assertEqual(filters["date_to"], "2026-03-31")
        self.assertEqual(filters["project_id"], 42)
        self.assertEqual(filters["work_type"], "Modeling")
        self.assertEqual(filters["role_type"], "Developer")


if __name__ == "__main__":
    unittest.main()
