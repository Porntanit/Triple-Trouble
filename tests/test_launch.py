"""Launcher tests never install software, download models or open a browser."""

import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import launch


class LaunchTests(unittest.TestCase):
    def test_bundle_structure_and_missing_file(self):
        launch.validate_bundle()
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaisesRegex(RuntimeError, "Extract the entire ZIP"):
                launch.validate_bundle(Path(folder))

    def test_model_tags(self):
        self.assertTrue(launch.model_is_installed("nomic-embed-text", {"nomic-embed-text:latest"}))
        self.assertTrue(launch.model_is_installed("gemma3:1b", {"gemma3:1b"}))
        self.assertFalse(launch.model_is_installed("gemma3:1b", {"gemma3:4b"}))

    @patch("launch.subprocess.run")
    @patch("launch.installed_models", return_value={"gemma3:1b", "nomic-embed-text:latest"})
    @patch("launch.ollama_cli", return_value="/test/ollama")
    def test_ready_models_need_no_download(self, cli, models, run):
        launch.ensure_ollama()
        run.assert_not_called()

    @patch("builtins.input", return_value="n")
    @patch("launch.subprocess.run")
    @patch("launch.installed_models", return_value={"gemma3:1b"})
    @patch("launch.ollama_cli", return_value="/test/ollama")
    def test_declined_download_does_not_run(self, cli, models, run, answer):
        with self.assertRaisesRegex(RuntimeError, "postponed"):
            launch.ensure_ollama()
        run.assert_not_called()

    @patch("launch.socket.socket")
    def test_busy_port_falls_back(self, socket):
        socket.return_value.__enter__.return_value.bind.side_effect = [OSError("busy"), None]
        self.assertEqual(launch.choose_port(), 5056)

    def test_prepared_environment_skips_pip(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            requirements = root / "requirements.txt"
            requirements.write_text("example==1\n")
            environment = root / ".venv"
            (environment / "bin").mkdir(parents=True)
            executable = environment / "bin" / "python"
            executable.touch()
            (environment / ".triple-trouble-requirements").write_text(
                hashlib.sha256(requirements.read_bytes()).hexdigest()
            )
            with (
                patch.object(launch, "ROOT", root),
                patch("launch.subprocess.run", return_value=Mock(returncode=0)) as run,
            ):
                self.assertEqual(launch.environment_python(), executable)
                self.assertEqual(run.call_count, 2)
                self.assertFalse(any("pip" in call.args[0] for call in run.call_args_list))


if __name__ == "__main__":
    unittest.main()
