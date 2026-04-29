import os
import unittest
from unittest.mock import patch

from app.config import get_settings


class ConfigTest(unittest.TestCase):
    def test_supports_db_alias_environment_names(self):
        env = {
            "DB_HOST": "db.example.com",
            "DB_PORT": "3307",
            "DB_NAME": "example_db",
            "DB_USER": "example_user",
            "DB_PASSWORD": "example_password",
            "AI_PROVIDER": "gemini",
            "GEMINI_API_KEY": "test-key",
        }
        with patch.dict(os.environ, env, clear=False):
            settings = get_settings()

        self.assertEqual(settings.mysql_host, "db.example.com")
        self.assertEqual(settings.mysql_port, 3307)
        self.assertEqual(settings.mysql_database, "example_db")
        self.assertEqual(settings.mysql_user, "example_user")
        self.assertEqual(settings.mysql_password, "example_password")
        self.assertEqual(settings.ai_provider, "gemini")
        self.assertEqual(settings.gemini_api_key, "test-key")

    def test_ignores_placeholder_database_url(self):
        env = {
            "DB_HOST": "db.example.com",
            "DB_NAME": "example_db",
            "DB_USER": "example_user",
            "DB_PASSWORD": "example_password",
            "DATABASE_URL": "mysql+pymysql://YOUR_DB_USERNAME:YOUR_DB_PASSWORD@YOUR_MYSQL_HOST:3306/example_db?charset=utf8mb4",
        }
        with patch.dict(os.environ, env, clear=False):
            settings = get_settings()

        self.assertIn("db.example.com", settings.sqlalchemy_url)
        self.assertNotIn("YOUR_DB_USERNAME", settings.sqlalchemy_url)


if __name__ == "__main__":
    unittest.main()
