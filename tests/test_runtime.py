import sqlite3
import json
import tempfile
import time
import unittest
from contextlib import closing
from pathlib import Path

from memnetai_agent_integration.client import MemNetAIError, SDKClient
from memnetai_agent_integration.config import IntegrationDefaults
from memnetai_agent_integration.database import (
    append_message, connect, due_sessions, get_batch, seal_batch,
)
from memnetai_agent_integration.runtime import MemoryRuntime


class FakeSDK:
    def recall(self, **kwargs):
        return {"response_json": {"data": {"memorySummaryList": [{"content": "remembered"}]}}}

    def memories(self, **kwargs):
        return {"response_json": {"data": {"taskId": "task-1"}}}


class RuntimeTests(unittest.TestCase):
    def test_database_context_manager_releases_windows_file_handle(self):
        with tempfile.TemporaryDirectory() as directory:
            db = Path(directory) / "state.db"
            with connect(db) as connection:
                connection.execute("CREATE TABLE lifecycle(value INTEGER)")
            db.unlink()
            self.assertFalse(db.exists())

    def test_legacy_batch_table_is_migrated(self):
        with tempfile.TemporaryDirectory() as directory:
            db = Path(directory) / "legacy.db"
            with closing(sqlite3.connect(db)) as connection:
                connection.executescript("""
                    CREATE TABLE sessions(
                        session_id TEXT PRIMARY KEY, host TEXT, memory_agent_name TEXT,
                        namespace TEXT, last_activity_at TEXT, next_flush_at TEXT,
                        pending_count INTEGER, in_flight INTEGER, generation INTEGER
                    );
                    CREATE TABLE batches(
                        batch_id TEXT PRIMARY KEY, session_id TEXT, status TEXT,
                        trigger_reason TEXT, idempotency_key TEXT, retry_count INTEGER,
                        last_error TEXT
                    );
                    CREATE TABLE messages(
                        message_id TEXT PRIMARY KEY, session_id TEXT, batch_id TEXT,
                        sequence_number INTEGER, role TEXT, content TEXT, created_at TEXT,
                        memory_status TEXT
                    );
                """)
            from memnetai_agent_integration.database import initialize
            initialize(db)
            with closing(sqlite3.connect(db)) as connection:
                columns = {row[1] for row in connection.execute("PRAGMA table_info(batches)")}
                self.assertTrue({"created_at", "updated_at", "next_retry_at", "remote_task_id"} <= columns)
                self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 1)

    def test_official_memory_prompt_and_task_progress_contract(self):
        class Response:
            def __enter__(self): return self
            def __exit__(self, *args): return None
            def read(self): return json.dumps({"data": {"progress": 100}}).encode()

        captured = {}
        def opener(request, timeout):
            captured["url"] = request.full_url
            captured["auth"] = request.get_header("Authorization")
            captured["timeout"] = timeout
            return Response()

        client = SDKClient("secret", sdk_client=FakeSDK(), http_open=opener)
        result = client.recall(memory_agent_name="personal-agent", namespace="default", query="q")
        # FakeSDK exercises the legacy list response while task progress locks the official REST contract.
        self.assertEqual(result.memories, ("remembered",))
        self.assertEqual(client.task_progress("task/1"), {"data": {"progress": 100}})
        self.assertIn("taskId=task%2F1", captured["url"])
        self.assertEqual(captured["auth"], "Token secret")

    def test_official_memory_prompt_has_priority(self):
        class PromptSDK(FakeSDK):
            def recall(self, **kwargs):
                return {"data": {"memoryPrompt": "official prompt", "memorySummaryList": [{"content": "legacy"}]}}
        result = SDKClient("secret", sdk_client=PromptSDK()).recall(memory_agent_name="personal-agent", namespace="default", query="q")
        self.assertEqual(result.memories, ("official prompt",))

    def test_api_error_code_is_not_treated_as_empty_recall(self):
        class ErrorSDK(FakeSDK):
            def recall(self, **kwargs):
                return {"code": "QUOTA", "msg": "insufficient points"}
        client = SDKClient("secret", sdk_client=ErrorSDK())
        with self.assertRaises(MemNetAIError):
            client.recall(memory_agent_name="personal-agent", namespace="default", query="q")

    def test_sessions_are_isolated_and_message_ids_are_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            db = Path(directory) / "state.db"
            first = append_message(db, session_id="a", host="codex", role="user", content="one", message_id="event-1")
            duplicate = append_message(db, session_id="a", host="codex", role="user", content="one", message_id="event-1")
            other = append_message(db, session_id="b", host="hermes", role="user", content="two")
            self.assertEqual(first.sequence_number, duplicate.sequence_number)
            self.assertEqual(other.sequence_number, 1)
            self.assertEqual(due_sessions(db, max_messages=1), ["a", "b"])

    def test_sealed_batch_is_stable_and_messages_are_retained(self):
        with tempfile.TemporaryDirectory() as directory:
            db = Path(directory) / "state.db"
            append_message(db, session_id="s", host="workbuddy", role="user", content="hello")
            batch = seal_batch(db, session_id="s", trigger_reason="threshold")
            self.assertIsNotNone(batch)
            self.assertIsNone(seal_batch(db, session_id="s", trigger_reason="threshold"))
            with closing(sqlite3.connect(db)) as connection:
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM messages WHERE batch_id=?", (batch.batch_id,)).fetchone()[0], 1)

    def test_runtime_recall_and_submission(self):
        with tempfile.TemporaryDirectory() as directory:
            config = IntegrationDefaults(database_path=Path(directory) / "state.db", max_messages=2)
            runtime = MemoryRuntime(config, SDKClient("secret", sdk_client=FakeSDK()))
            before = runtime.before_reply(session_id="s", host="codex", prompt="hello")
            runtime.after_reply(session_id="s", host="codex", response="hi")
            submitted = runtime.submit_session("s", "threshold")
            self.assertTrue(before.ok)
            self.assertEqual(before.payload.memories, ("remembered",))
            self.assertEqual(submitted.payload["remote_task_id"], "task-1")
            with closing(sqlite3.connect(config.database_path)) as connection:
                self.assertEqual(connection.execute("SELECT status FROM batches").fetchone()[0], "submitted")
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM messages").fetchone()[0], 2)

    def test_async_progress_completes_without_deleting_messages(self):
        class ProgressClient(SDKClient):
            def task_progress(self, task_id, timeout=5.0):
                return {"data": {"progress": 100}}
        with tempfile.TemporaryDirectory() as directory:
            config = IntegrationDefaults(database_path=Path(directory) / "state.db")
            runtime = MemoryRuntime(config, ProgressClient("secret", sdk_client=FakeSDK()))
            runtime.after_reply(session_id="s", host="hermes", response="done")
            submitted = runtime.submit_session("s", "idle")
            checked = runtime.check_submission(submitted.payload["batch_id"], "task-1")
            self.assertEqual(checked.payload["action"], "complete")
            with closing(sqlite3.connect(config.database_path)) as connection:
                self.assertEqual(connection.execute("SELECT status FROM batches").fetchone()[0], "complete")
                self.assertEqual(connection.execute("SELECT memory_status FROM messages").fetchone()[0], "complete")

    def test_missing_task_id_is_retained_for_retry(self):
        class MissingTaskSDK(FakeSDK):
            def memories(self, **kwargs):
                return {"data": {}}
        with tempfile.TemporaryDirectory() as directory:
            config = IntegrationDefaults(database_path=Path(directory) / "state.db")
            runtime = MemoryRuntime(config, SDKClient("secret", sdk_client=MissingTaskSDK()))
            runtime.after_reply(session_id="s", host="codex", response="keep me")
            result = runtime.submit_session("s", "idle")
            self.assertFalse(result.ok)
            with closing(sqlite3.connect(config.database_path)) as connection:
                batch_id = connection.execute("SELECT batch_id FROM batches").fetchone()[0]
                self.assertEqual(get_batch(config.database_path, batch_id).status, "retry")
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM messages").fetchone()[0], 1)

    def test_failed_submission_can_retry_same_sealed_batch(self):
        class FlakySDK(FakeSDK):
            attempts = 0
            def memories(self, **kwargs):
                self.attempts += 1
                if self.attempts == 1:
                    raise RuntimeError("temporary")
                return {"data": {"taskId": "task-retry"}}
        with tempfile.TemporaryDirectory() as directory:
            config = IntegrationDefaults(database_path=Path(directory) / "state.db")
            runtime = MemoryRuntime(config, SDKClient("secret", sdk_client=FlakySDK()))
            runtime.after_reply(session_id="s", host="codex", response="keep me")
            first = runtime.submit_session("s", "idle")
            with closing(sqlite3.connect(config.database_path)) as connection:
                batch_id = connection.execute("SELECT batch_id FROM batches").fetchone()[0]
            second = runtime.retry_submission(batch_id)
            self.assertFalse(first.ok)
            self.assertTrue(second.ok)
            self.assertEqual(second.payload["remote_task_id"], "task-retry")

    def test_recall_timeout_is_nonfatal_to_runtime(self):
        class SlowSDK(FakeSDK):
            def recall(self, **kwargs):
                time.sleep(0.1)
                return {}
        with tempfile.TemporaryDirectory() as directory:
            config = IntegrationDefaults(database_path=Path(directory) / "state.db", recall_timeout_seconds=0.01)
            result = MemoryRuntime(config, SDKClient("secret", sdk_client=SlowSDK())).before_reply(session_id="s", host="codex", prompt="hello")
            self.assertFalse(result.ok)
            self.assertIn("dashboard.memnetai.com", result.dashboard_url)


if __name__ == "__main__":
    unittest.main()
