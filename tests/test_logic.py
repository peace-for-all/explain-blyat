import json
import math
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx

from explain_video.config import load_config
from explain_video.media import choose_timing
from explain_video.pipeline import output_paths, publish
from explain_video.providers import OpenAIAPI, OpenAIRewrite, OpenAITranscription, OpenAITTS, speech_chunks


class LogicTests(unittest.TestCase):
    def test_output_names(self):
        paths = output_paths(Path("/tmp/Видео demo.v1.mp4"))
        self.assertEqual(paths["video"], Path("/tmp/Видео demo.v1.explained.mp4"))
        self.assertEqual(paths["voice"].name, "Видео demo.v1.voice.wav")
        self.assertEqual(len(set(paths.values())), 5)

    def test_no_clobber(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            original, destination = root / "original", root / "destination"
            original.write_text("original")
            destination.symlink_to(original)
            with self.assertRaises(FileExistsError):
                publish(original, destination)
            self.assertEqual(original.read_text(), "original")

    def test_variant_paths_and_optional_facts(self):
        paths = output_paths(Path("/tmp/demo.mp4"), Path("/tmp/demo.v2"), include_facts=True)
        self.assertEqual(paths["video"], Path("/tmp/demo.v2.explained.mp4"))
        self.assertEqual(paths["facts"], Path("/tmp/demo.v2.facts.txt"))
        self.assertNotIn("facts", output_paths(Path("demo.mp4")))

    def test_timing(self):
        self.assertAlmostEqual(choose_timing(10, 10.5).speed, 10 / 10.5)
        self.assertEqual(choose_timing(10, 20).freeze_seconds, 10)
        self.assertEqual(choose_timing(10, 4).quiet_seconds, 6)
        self.assertEqual(choose_timing(10, 4).output_duration, 10)
        self.assertEqual(choose_timing(10, 10).speed, 1)

    def test_timing_boundaries(self):
        self.assertAlmostEqual(choose_timing(9, 10).speed, .9)
        self.assertAlmostEqual(choose_timing(11, 10).speed, 1.1)
        self.assertEqual(choose_timing(8.99, 10).speed, 1)
        self.assertEqual(choose_timing(11.01, 10).speed, 1)

    def test_bad_durations(self):
        for bad in [0, -1, math.nan, math.inf]:
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                choose_timing(10, bad)

    def test_config_environment_precedence(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {"OPENAI_API_KEY": "shell-secret"}, clear=True):
            path = Path(directory) / ".env"
            path.write_text('OPENAI_API_KEY="file-secret"\nEXPLAIN_TTS_PROVIDER=openai\n')
            config = load_config(path, "nova")
            self.assertEqual(config.api_key, "shell-secret")
            self.assertEqual(config.voice, "nova")
            self.assertNotIn("secret", repr(config))

    def test_chunks_preserve_words(self):
        script = "Это первое предложение. А это второе предложение. " * 100
        chunks = speech_chunks(script, 100)
        self.assertTrue(all(len(chunk) <= 100 for chunk in chunks))
        self.assertEqual(" ".join(chunks).split(), script.split())


class ProviderTests(unittest.TestCase):
    def api(self, handler):
        client = httpx.Client(transport=httpx.MockTransport(handler))
        self.addCleanup(client.close)
        return OpenAIAPI("test-key", client)

    def test_rewrite_request_and_reasoning_output(self):
        def handler(request):
            data = json.loads(request.content)
            self.assertEqual(data["input"], "Исходная речь")
            self.assertFalse(data["store"])
            self.assertIn("предположения", data["instructions"])
            return httpx.Response(200, json={"status": "completed", "output": [
                {"type": "reasoning"}, {"type": "message", "content": [
                    {"type": "output_text", "text": "Простое объяснение."}]}]})
        provider = OpenAIRewrite(self.api(handler), "test-model")
        self.assertEqual(provider.rewrite("Исходная речь"), "Простое объяснение.")

    def test_rewrite_rejects_incomplete_and_refusal(self):
        for data in [{"status": "incomplete", "output": []},
                     {"status": "completed", "output": [{"type": "message", "content": [{"type": "refusal"}]}]}]:
            provider = OpenAIRewrite(self.api(lambda request: httpx.Response(200, json=data)), "test")
            with self.assertRaises(ValueError):
                provider.rewrite("Речь")

    def test_facts_are_separate_source_material(self):
        # Synthetic value, not a claim about the user's production system.
        facts = "Уточнение: примерно 12 примеров, не гарантия."
        def handler(request):
            payload = json.loads(request.content)
            self.assertEqual(json.loads(payload["input"]), {"transcript": "Система учится.", "facts": facts})
            self.assertIn("второй допустимый источник", payload["instructions"])
            self.assertIn("не выбирай молча", payload["instructions"])
            self.assertIn("приблизительность", payload["instructions"])
            return httpx.Response(200, json={"status": "completed", "output": [
                {"type": "message", "content": [{"type": "output_text", "text": "Объяснение."}]}]})
        provider = OpenAIRewrite(self.api(handler), "test-model")
        self.assertEqual(provider.rewrite("Система учится.", facts=facts), "Объяснение.")

    def test_empty_facts_fail_before_api(self):
        def handler(request):
            self.fail("Empty facts must not trigger a paid request")
        with self.assertRaisesRegex(ValueError, "Facts"):
            OpenAIRewrite(self.api(handler), "test").rewrite("Речь", facts="  ")

    def test_transcription_multipart(self):
        def handler(request):
            self.assertIn(b'name="language"', request.content)
            self.assertIn(b'filename="audio.wav"', request.content)
            return httpx.Response(200, json={"text": "Проверка"})
        with tempfile.TemporaryDirectory() as directory:
            audio = Path(directory) / "audio.wav"
            audio.write_bytes(b"fixture")
            self.assertEqual(OpenAITranscription(self.api(handler), "test").transcribe(audio), "Проверка")

    def test_tts_request_and_wav_output(self):
        # A real valid WAV is rendered through ffmpeg, not a mocked output file.
        import io
        import wave
        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as wav:
            wav.setparams((1, 2, 24000, 0, "NONE", "not compressed"))
            wav.writeframes(b"\0\0" * 2400)
        def handler(request):
            data = json.loads(request.content)
            self.assertEqual(data["voice"], "coral")
            self.assertEqual(data["response_format"], "wav")
            self.assertEqual(data["input"], "Привет.")
            self.assertEqual(data["instructions"], "Говори тепло и чуть бодрее.")
            return httpx.Response(200, content=buffer.getvalue())
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "voice.wav"
            OpenAITTS(self.api(handler), "gpt-4o-mini-tts", "Говори тепло и чуть бодрее.").synthesize("Привет.", target, "coral")
            with wave.open(str(target)) as wav:
                self.assertEqual(wav.getnframes(), 2400)

    def test_api_error_does_not_leak_body(self):
        api = self.api(lambda request: httpx.Response(401, text="private transcript or secret"))
        with self.assertRaisesRegex(RuntimeError, "HTTP 401") as error:
            api.post("responses", json={})
        self.assertNotIn("private", str(error.exception))

    def test_missing_key(self):
        with self.assertRaisesRegex(ValueError, "OPENAI_API_KEY"):
            OpenAIAPI("")
