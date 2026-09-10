import tempfile
import io
import shlex
import unittest
from pathlib import Path
from unittest.mock import patch

from explain_video.__main__ import main, create_run_directory, print_result


class CLITests(unittest.TestCase):
    def test_numbered_runs_preserve_previous_results_and_skip_symlinks(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "Видео demo.mov"
            first = create_run_directory(source, None, False)
            (first / "script.txt").write_text("previous")
            (first.parent / (first.name + "-2")).symlink_to(first)
            third = create_run_directory(source, None, False)
            self.assertEqual(third.name, "Видео demo.explained-3")
            self.assertEqual((first / "script.txt").read_text(), "previous")
            self.assertEqual((third / ".gitignore").read_text(), "*\n")
            self.assertEqual(create_run_directory(source, None, True).name, "Видео demo.synced")
            with self.assertRaisesRegex(ValueError, "already exists"):
                create_run_directory(source, first, False)

    def test_result_links_and_open_commands_handle_special_filenames(self):
        video = Path("/tmp/Видео's $demo/video.mp4")
        for platform, command in [("darwin", "open"), ("linux", "xdg-open")]:
            output = io.StringIO()
            with patch("sys.platform", platform), patch("sys.stdout", output):
                print_result(video, video.parent / "script.txt")
            lines = output.getvalue().splitlines()
            self.assertIn(f"Video link: {video.as_uri()}", lines)
            play = next(line.removeprefix("Play video: ") for line in lines if line.startswith("Play video: "))
            self.assertEqual(shlex.split(play), [command, str(video)])
            if platform == "darwin":
                show = next(line.removeprefix("Show in Finder: ") for line in lines if line.startswith("Show in Finder: "))
                self.assertEqual(shlex.split(show), ["open", "-R", str(video)])

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
                self.assertIsNone(kwargs["output_prefix"])
                self.assertEqual(kwargs["output_dir"], root / "input.synced")
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
