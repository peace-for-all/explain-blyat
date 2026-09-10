import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from explain_video.__main__ import main


class CLITests(unittest.TestCase):
    def test_invalid_supplied_script_fails_before_providers(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "input.mp4"
            source.touch()
            empty = root / "empty.txt"
            empty.write_text("  ")
            for path in (root / "missing.txt", empty):
                with patch("sys.argv", ["explain-video", str(source), "--sync", "--script", str(path)]), \
                        patch("explain_video.__main__.make_providers") as providers, patch("sys.stderr"):
                    self.assertEqual(main(), 1)
                    providers.assert_not_called()

    def test_sync_script_skips_interview_and_uses_separate_prefix(self):
        from unittest.mock import Mock
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "input.mp4"
            source.touch()
            script = root / "approved.txt"
            script.write_text("Утверждённый текст.")
            providers = (Mock(), Mock(), Mock())
            result = {"input_duration": 1, "narration_duration": 1, "video_adjustment": "sync", "warnings": []}
            with patch("sys.argv", ["explain-video", str(source), "--sync", "--script", str(script)]), \
                    patch("explain_video.__main__.make_providers", return_value=providers), \
                    patch("explain_video.__main__.run_pipeline", return_value=result) as pipeline, \
                    patch("sys.stdin.isatty", return_value=False), patch("builtins.print"):
                self.assertEqual(main(), 0)
                kwargs = pipeline.call_args.kwargs
                self.assertIsNone(kwargs["question_provider"])
                self.assertIsNone(kwargs["answer_question"])
                self.assertEqual(kwargs["narration_script"], "Утверждённый текст.")
                self.assertEqual(kwargs["output_prefix"], root / "input.synced")
                self.assertIsNotNone(kwargs["sync_engine"])

    def test_bad_facts_fail_before_providers(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "input.mp4"
            source.touch()
            missing = root / "missing.txt"
            empty = root / "empty.txt"
            empty.write_text("  ")
            invalid = root / "invalid.txt"
            invalid.write_bytes(b"\xff")
            for path in (missing, empty, invalid):
                with self.subTest(path=path.name), patch("sys.argv", ["explain-video", str(source), "--facts", str(path)]), \
                        patch("explain_video.__main__.make_providers") as providers, patch("sys.stderr"):
                    self.assertEqual(main(), 1)
                    providers.assert_not_called()
