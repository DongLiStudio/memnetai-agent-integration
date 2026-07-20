import json
import os
import tempfile
import unittest
from subprocess import CompletedProcess
from pathlib import Path
from unittest.mock import patch

from memnetai_agent_integration.adapters.codex import CodexAdapter
from memnetai_agent_integration.adapters.generic_prompt import GenericPromptAdapter, PROMPT_MARKER_START
from memnetai_agent_integration.adapters.hermes import HermesAdapter
from memnetai_agent_integration.adapters.workbuddy import WorkBuddyAdapter


class AdapterTests(unittest.TestCase):
    @unittest.skipUnless(os.name == "nt", "Windows Hermes home convention")
    def test_hermes_uses_local_appdata_on_windows(self) -> None:
        with tempfile.TemporaryDirectory() as directory, patch.dict(
            os.environ, {"LOCALAPPDATA": directory}, clear=False
        ):
            with patch.dict(os.environ, {"HERMES_HOME": ""}, clear=False):
                self.assertEqual(
                    HermesAdapter().plugin_dir,
                    Path(directory) / "hermes" / "plugins" / "memnetai-memory",
                )

    def test_codex_hooks_merge_and_remove_without_destroying_user_hooks(self) -> None:
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {"CODEX_HOME": directory}):
            path = Path(directory) / "hooks.json"
            path.write_text(json.dumps({"hooks": {"Stop": [{"hooks": [{"type": "command", "command": "user-command"}]}]}}), encoding="utf-8")
            adapter = CodexAdapter()
            executable = Path("C:/Program Files/MemNetAI/memnetai-integration.exe")
            adapter.install(executable)
            self.assertTrue(adapter.verify(executable).verified)
            adapter.install(executable)
            data = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(2, len(data["hooks"]["Stop"]))
            adapter.uninstall(executable)
            data = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual("user-command", data["hooks"]["Stop"][0]["hooks"][0]["command"])

    def test_workbuddy_uses_workbuddy_home(self) -> None:
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {"WORKBUDDY_HOME": directory}):
            adapter = WorkBuddyAdapter()
            adapter.install(Path("memnetai-integration"))
            self.assertEqual(Path(directory) / "settings.json", adapter.config_path)
            self.assertTrue(adapter.verify(Path("memnetai-integration")).verified)

    def test_hermes_plugin_is_idempotent_and_reversible(self) -> None:
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {"HERMES_HOME": directory}):
            def runner(args):
                stdout = '[{"key":"memnetai-memory"}]' if "list" in args else ""
                return CompletedProcess(args, 0, stdout, "")
            adapter = HermesAdapter(runner=runner)
            executable = Path("/opt/memnetai/bin/memnetai-integration")
            adapter.install(executable)
            adapter.install(executable)
            plugin = Path(directory) / "plugins" / "memnetai-memory" / "__init__.py"
            self.assertIn("pre_llm_call", plugin.read_text(encoding="utf-8"))
            self.assertTrue(adapter.verify(executable).verified)
            adapter.uninstall(executable)
            self.assertFalse(plugin.exists())

    def test_generic_prompt_marker_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "AGENTS.md"
            target.write_text("user content\n", encoding="utf-8")
            adapter = GenericPromptAdapter(target)
            adapter.install(Path("memnetai-integration"))
            self.assertIn(PROMPT_MARKER_START, target.read_text(encoding="utf-8"))
            adapter.uninstall(Path("memnetai-integration"))
            self.assertEqual("user content\n", target.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
