import unittest

from app.llm import extract_gemini_text, generate_sql_plan, parse_json_object
from app.metadata import load_reporting_metadata
from app.sql_builder import validate_llm_sql


class FakeGeminiClient:
    def __init__(self, payload):
        self.payload = payload

    def chat_json(self, messages):
        self.messages = messages
        return self.payload


class LlmReportingTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.metadata = load_reporting_metadata()

    def test_parses_json_from_model_content(self):
        parsed = parse_json_object('Here is JSON:\n{"sql": "SELECT 1", "params": {"limit": 1}}')
        self.assertEqual(parsed["sql"], "SELECT 1")

    def test_generates_sql_plan_from_fake_gemini_response(self):
        client = FakeGeminiClient(
            {
                "report_id": "attendance_report",
                "report_name": "Attendance Report",
                "sql": "SELECT attendances.date, users.name FROM attendances LEFT JOIN users ON attendances.user_id = users.id WHERE attendances.date >= :date_from LIMIT :limit",
                "params": {"date_from": "2026-03-01", "limit": 50},
                "expected_columns": ["date", "name"],
                "report_title": "Attendance Report",
                "report_summary": "Attendance rows for the requested period.",
                "warnings": [],
            }
        )
        plan = generate_sql_plan(
            "show attendance report for March 2026",
            self.metadata,
            schema_summary=None,
            filters={},
            limit=50,
            client=client,
        )
        self.assertEqual(plan.report_id, "attendance_report")
        self.assertIn("SELECT", plan.sql)
        self.assertIn("reporting_metadata", client.messages[1]["content"])

    def test_extracts_gemini_text(self):
        body = {"candidates": [{"content": {"parts": [{"text": "{\"ok\": true}"}]}}]}
        self.assertEqual(extract_gemini_text(body), "{\"ok\": true}")

    def test_validates_llm_sql_against_metadata(self):
        warnings = validate_llm_sql(
            "SELECT attendances.date, users.name FROM attendances LEFT JOIN users ON attendances.user_id = users.id LIMIT :limit",
            {"limit": 10},
            self.metadata,
        )
        self.assertEqual(warnings, [])

    def test_rejects_llm_sql_using_undeclared_table(self):
        with self.assertRaises(ValueError):
            validate_llm_sql("SELECT payroll.salary FROM payroll LIMIT :limit", {"limit": 10}, self.metadata)

    def test_rejects_llm_sql_without_limit_parameter(self):
        with self.assertRaises(ValueError):
            validate_llm_sql("SELECT users.name FROM users", {}, self.metadata)


if __name__ == "__main__":
    unittest.main()
