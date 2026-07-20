import io
import json
import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from memnetai_agent_integration import cli
from memnetai_agent_integration.hooks import extract_last_assistant, normalize
from memnetai_agent_integration.secrets import load_api_key, save_api_key, secret_path


class CliTests(unittest.TestCase):
    def test_restore_paths_recreates_exact_preinstall_state(self):
        with tempfile.TemporaryDirectory() as td:
            existing = Path(td) / "existing.json"
            created = Path(td) / "created" / "hooks.json"
            existing.write_bytes(b"before")
            snapshot = cli._snapshot_paths([existing, created])
            existing.write_bytes(b"after")
            created.parent.mkdir()
            created.write_bytes(b"new")
            cli._restore_paths(snapshot)
            self.assertEqual(existing.read_bytes(), b"before")
            self.assertFalse(created.exists())
            self.assertFalse(created.parent.exists())

    def test_install_manifest_preserves_first_host_state_across_reinstall(self):
        with tempfile.TemporaryDirectory() as td:
            home = Path(td) / "data"
            original = Path(td) / "host" / "settings.json"
            created = Path(td) / "host" / "hooks.json"
            original.parent.mkdir()
            original.write_bytes(b"original")
            manifest = cli.InstallManifest()
            cli._capture_install_state(home, manifest, [original, created])
            original.write_bytes(b"installed")
            created.write_bytes(b"installed")
            cli._capture_install_state(home, manifest, [original, created])
            cli.AtomicFileManager(home / "backups", manifest).restore_all()
            self.assertEqual(original.read_bytes(), b"original")
            self.assertFalse(created.exists())

    def test_install_without_key_waits(self):
        with (
            tempfile.TemporaryDirectory() as td,
            patch.dict(os.environ, {"MEMNETAI_INTEGRATION_HOME": td}),
            patch("sys.stdout", new_callable=io.StringIO) as out,
        ):
            self.assertEqual(cli.main(["install"]), 0)
            self.assertEqual(json.loads(out.getvalue())["status"], "waiting_for_api_key")
            self.assertFalse(secret_path(Path(td)).exists())

    @unittest.skipIf(os.name == "nt", "POSIX permission assertion")
    def test_secret_is_private(self):
        with tempfile.TemporaryDirectory() as td:
            path = save_api_key(Path(td), "secret-value")
            self.assertEqual(load_api_key(Path(td)), "secret-value")
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)

    def test_workbuddy_transcript_extracts_latest_assistant(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "chat.jsonl"
            path.write_text('\n'.join([
                json.dumps({"role": "assistant", "content": "old"}),
                json.dumps({
                    "type": "assistant",
                    "message": {"content": [{"type": "text", "text": "latest"}]},
                }),
            ]), encoding="utf-8")
            self.assertEqual(extract_last_assistant(path), "latest")
            item = normalize(
                {"host": "workbuddy", "session_id": "s", "transcript_path": str(path)},
                event="after",
            )
            self.assertEqual(item.response, "latest")
            self.assertEqual(
                item.event_id("assistant", "latest"), item.event_id("assistant", "latest")
            )

    def test_workbuddy_is_inferred_from_transcript_path(self):
        item = normalize(
            {"session_id": "s", "transcript_path": "/home/u/.workbuddy/sessions/a.jsonl"},
            event="after",
        )
        self.assertEqual(item.host, "workbuddy")

    def test_hook_before_codex_output(self):
        runtime = Mock()
        runtime.before_reply.return_value = Mock(
            ok=True, payload=Mock(memories=("memory",)), user_notice=None
        )
        payload = json.dumps({"session_id": "s", "turn_id": "t", "prompt": "hello"})
        with (
            patch.object(cli, "_runtime", return_value=runtime),
            patch("sys.stdin", io.StringIO(payload)),
            patch("sys.stdout", new_callable=io.StringIO) as out,
        ):
            self.assertEqual(cli.main(["hook-before"]), 0)
            result = json.loads(out.getvalue())
            self.assertEqual(result["hookSpecificOutput"]["additionalContext"], "memory")
            self.assertNotIn("api", out.getvalue().lower())

    def test_api_key_message_is_never_buffered(self):
        runtime = Mock()
        payload = json.dumps({"session_id": "s", "turn_id": "t", "prompt": "secret-key"})
        with (
            patch.object(cli, "_runtime", return_value=runtime),
            patch.object(cli, "load_api_key", return_value="secret-key"),
            patch("sys.stdin", io.StringIO(payload)),
            patch("sys.stdout", new_callable=io.StringIO) as out,
        ):
            self.assertEqual(cli.main(["hook-before"]), 0)
            self.assertEqual(json.loads(out.getvalue()), {})
            runtime.before_reply.assert_not_called()

    def test_install_key_comes_from_stdin_and_is_not_printed(self):
        adapter = Mock()
        adapter.detect.return_value = True
        adapter.install.return_value = {"installed": True}
        scheduler = Mock()
        scheduler.install.return_value = Mock(scheduler="mock", identifier="mock")
        client = Mock()
        with (
            tempfile.TemporaryDirectory() as td,
            patch.dict(os.environ, {"MEMNETAI_INTEGRATION_HOME": td}),
            patch("sys.stdin", io.StringIO("top-secret\n")),
            patch("sys.stdout", new_callable=io.StringIO) as out,
            patch.object(cli, "SDKClient", return_value=client),
            patch.object(cli, "_adapters", return_value=[adapter]),
            patch.object(cli, "_scheduler", return_value=scheduler),
            patch.object(cli, "initialize"),
        ):
            self.assertEqual(cli.main(["install", "--api-key-stdin"]), 0)
            self.assertNotIn("top-secret", out.getvalue())
            self.assertEqual(load_api_key(Path(td)), "top-secret")


if __name__ == "__main__":
    unittest.main()
