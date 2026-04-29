import unittest

from app.llm import format_gemini_http_error


class GeminiErrorFormattingTest(unittest.TestCase):
    def test_access_error_explains_before_sql_execution(self):
        message = format_gemini_http_error(403, "permission denied", "gemini-2.5-flash-lite")
        self.assertIn("before SQL execution", message)
        self.assertIn("gemini-2.5-flash-lite", message)
        self.assertIn("/llm/health", message)


if __name__ == "__main__":
    unittest.main()
