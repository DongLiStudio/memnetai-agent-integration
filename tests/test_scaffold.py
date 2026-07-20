import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from memnetai_agent_integration.config import IntegrationDefaults
from memnetai_agent_integration.database import initialize


class ScaffoldTests(unittest.TestCase):
    def test_defaults(self) -> None:
        defaults = IntegrationDefaults()
        self.assertEqual(defaults.memory_agent_name, "personal-agent")
        self.assertEqual(defaults.namespace, "default")
        self.assertEqual(defaults.idle_timeout_minutes, 10)
        self.assertEqual(defaults.max_messages, 32)

    def test_database_schema(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "integration.sqlite3"
            initialize(path)
            with closing(sqlite3.connect(path)) as connection:
                tables = {
                    row[0]
                    for row in connection.execute(
                        "SELECT name FROM sqlite_master WHERE type = 'table'"
                    )
                }
            self.assertTrue({"sessions", "messages", "batches"}.issubset(tables))

    def test_install_skill_has_no_template_placeholders(self) -> None:
        skill = Path("skills/install-memnetai/SKILL.md").read_text(encoding="utf-8")
        self.assertIn("name: install-memnetai", skill)
        self.assertNotIn("TODO", skill)
        self.assertNotIn("PLACEHOLDER", skill)


if __name__ == "__main__":
    unittest.main()
