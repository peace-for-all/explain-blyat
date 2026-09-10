import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import httpx

from explain_video.interactive import read_answer
from explain_video.pipeline import run_pipeline, output_paths
from explain_video.providers import OpenAIAPI, OpenAIRewrite, validate_questions
from explain_video.__main__ import main


class QuestionTests(unittest.TestCase):
    def test_analysis_then_rewrite_contract(self):
        requests = []
        def handler(request):
            data = json.loads(request.content)
            requests.append(data)
            if len(requests) == 1:
                self.assertEqual(data["text"]["format"]["type"], "json_schema")
                self.assertTrue(data["text"]["format"]["strict"])
                self.assertEqual(json.loads(data["input"])["facts"], "Условия пока не известны.")
                text = json.dumps({"questions": ["Что нужно проверить?"]}, ensure_ascii=False)
            else:
                material = json.loads(data["input"])
                self.assertEqual(material["transcript"], "Система обновилась.")
                self.assertEqual(material["answers"], [{"question": "Что нужно проверить?", "answer": "Пока не знаю."}])
                self.assertIn("Сам вопрос не является фактом", data["instructions"])
                text = "Система обновилась. Порядок проверки ещё уточняется."
            return httpx.Response(200, json={"status": "completed", "output": [
                {"type": "message", "content": [{"type": "output_text", "text": text}]}]})
        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            provider = OpenAIRewrite(OpenAIAPI("test", client), "test-model")
            qs = provider.questions("Система обновилась.", facts="Условия пока не известны.")
            provider.rewrite("Система обновилась.", answers=[{"question": qs[0], "answer": "Пока не знаю."}])
        self.assertEqual(len(requests), 2)

    def test_bad_question_lists_fail(self):
        for value in [None, "question", [""], [123], ["a"] * 6, ["a", "a"], ["x" * 501], ["\x1b[31m"]]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_questions(value)
        self.assertEqual(validate_questions([]), [])

    def test_multiline_skip_and_eof(self):
        with patch("builtins.input", side_effect=["Примерно несколько.", "Нужно проверить.", ""]), patch("builtins.print"):
            self.assertEqual(read_answer("Сколько?", 1, 1), "Примерно несколько.\nНужно проверить.")
        with patch("builtins.input", return_value=""), patch("builtins.print"):
            self.assertIsNone(read_answer("Сколько?", 1, 1))
        with patch("builtins.input", side_effect=EOFError), patch("builtins.print"), self.assertRaisesRegex(RuntimeError, "Input closed"):
            read_answer("Сколько?", 1, 1)

    def test_nonterminal_fails_before_paid_calls(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "input.mp4"
            source.touch()
            with patch("sys.argv", ["explain-video", str(source)]), patch("sys.stdin.isatty", return_value=False), \
                    patch("sys.stderr"), patch("explain_video.__main__.make_providers") as providers:
                self.assertEqual(main(), 1)
                providers.assert_not_called()

    def test_cli_interactive_default_and_explicit_opt_out(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "input.mp4"
            source.touch()
            providers = (Mock(), Mock(), Mock())
            metadata = {"input_duration": 1, "narration_duration": 1, "video_adjustment": "none", "warnings": []}
            for flags, tty, enabled in [([], True, True), (["--non-interactive"], False, False)]:
                with self.subTest(flags=flags), patch("sys.argv", ["explain-video", str(source), *flags]), \
                        patch("sys.stdin.isatty", return_value=tty), patch("builtins.print"), \
                        patch("explain_video.__main__.make_providers", return_value=providers), \
                        patch("explain_video.__main__.run_pipeline", return_value=metadata) as pipeline:
                    self.assertEqual(main(), 0)
                    self.assertIs(pipeline.call_args.kwargs["question_provider"], providers[1] if enabled else None)
                    self.assertEqual(pipeline.call_args.kwargs["answer_question"] is not None, enabled)


class InterviewPipelineTests(unittest.TestCase):
    def run_case(self, questions, answers, cancelled=False):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "input.mp4"
            source.write_bytes(b"source")
            folder = root / "run"
            folder.mkdir()
            paths = output_paths(source, include_facts=True, include_questions=True, output_dir=folder)
            transcriber = Mock(name="transcriber")
            transcriber.name, transcriber.model = "test", "test"
            transcriber.transcribe.return_value = "Рассказ."
            rewriter = Mock()
            rewriter.model = "test"
            rewriter.rewrite.return_value = "Объяснение."
            questioner = Mock()
            questioner.model = "test"
            questioner.questions.return_value = questions
            tts = Mock()
            tts.name, tts.model = "test", "test"
            tts.synthesize.side_effect = lambda script, target, voice: target.write_bytes(b"voice")
            info = {"streams": [{"codec_type": "video", "duration": "1"}, {"codec_type": "audio", "duration": "1"}]}
            answer_callback = Mock(side_effect=answers)
            with patch("explain_video.media.check_tools"), patch("explain_video.media.probe", return_value=info), \
                    patch("explain_video.media.extract_audio", side_effect=lambda s, t: t.write_bytes(b"audio")), \
                    patch("explain_video.media.render", side_effect=lambda s, v, t, timing: t.write_bytes(b"video")):
                def run():
                    return run_pipeline(source, transcriber, rewriter, tts, "marin", lambda s: None,
                                        facts="Дополнение.", question_provider=questioner, answer_question=answer_callback,
                                        output_dir=folder)
                if cancelled:
                    with self.assertRaises(KeyboardInterrupt):
                        run()
                    rewriter.rewrite.assert_not_called()
                    tts.synthesize.assert_not_called()
                    self.assertTrue(paths["transcript"].exists())
                    self.assertFalse(paths["video"].exists())
                else:
                    meta = run()
                    self.assertEqual(meta["clarification"]["question_count"], len(questions))
                    questioner.questions.assert_called_once_with("Рассказ.", facts="Дополнение.")
                    expected = [{"question": q, "answer": a.strip()} for q, a in zip(questions, answers) if a and a.strip()]
                    context = {"facts": "Дополнение."}
                    if expected:
                        context["answers"] = expected
                    rewriter.rewrite.assert_called_once_with("Рассказ.", **context)
                journal = json.loads(paths["questions"].read_text())
                self.assertEqual(journal["status"], "cancelled" if cancelled else "completed")
                self.assertEqual(source.read_bytes(), b"source")
                return journal

    def test_answers_and_skips_are_separate(self):
        journal = self.run_case(["Сколько?", "Когда?"], ["Примерно десять.", None])
        self.assertEqual([i["status"] for i in journal["items"]], ["answered", "skipped"])

    def test_no_questions_still_rewrites(self):
        self.assertEqual(self.run_case([], [])["items"], [])

    def test_all_skipped_do_not_become_facts(self):
        self.run_case(["Сколько?"], [None])

    def test_cancellation_preserves_previous_answer(self):
        journal = self.run_case(["Сколько?", "Когда?"], ["Пока не знаю.", KeyboardInterrupt()], cancelled=True)
        self.assertEqual(journal["items"][0]["answer"], "Пока не знаю.")
        self.assertEqual(journal["items"][1]["status"], "pending")
