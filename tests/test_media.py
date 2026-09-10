import array
import hashlib
import io
import json
import math
import shutil
import tempfile
import unittest
from unittest.mock import Mock, patch
from pathlib import Path

from explain_video.media import command, probe, duration
from explain_video.pipeline import run_pipeline, output_paths
from explain_video.__main__ import main


class FakeTranscription:
    name = "test-transcription"
    def transcribe(self, path):
        assert duration(probe(path), "audio") > 0
        return "Тут мы, э, обновили список."


class FakeRewrite:
    model = "test-rewrite"
    def rewrite(self, transcript, *, facts=None):
        assert "список" in transcript
        self.facts_received = facts
        return "Список обновлён."


class ToneTTS:
    name = "test-tone"
    def __init__(self, seconds):
        self.seconds = seconds
    def synthesize(self, script, target, voice):
        assert script == "Список обновлён."
        command(["ffmpeg", "-nostdin", "-v", "error", "-n", "-f", "lavfi", "-i",
                 f"sine=frequency=880:sample_rate=16000:duration={self.seconds}", str(target)])


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "ffmpeg required")
class MediaTests(unittest.TestCase):
    def test_cli_groups_outputs_for_mp4_mov_mkv_and_webm(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for extension in ("mp4", "mov", "mkv", "webm"):
                with self.subTest(extension=extension):
                    source = root / f"Видео {extension}.{extension}"
                    codecs = ["-c:v", "libvpx-vp9", "-c:a", "libopus"] if extension == "webm" else ["-c:v", "libx264", "-c:a", "aac"]
                    command(["ffmpeg", "-nostdin", "-v", "error", "-n", "-f", "lavfi", "-i",
                             "testsrc2=size=64x64:rate=10:duration=0.4", "-f", "lavfi", "-i",
                             "sine=frequency=220:sample_rate=48000:duration=0.4", *codecs, "-shortest", str(source)])
                    original = source.read_bytes()
                    output = io.StringIO()
                    with patch("sys.argv", ["explain-video", str(source), "--non-interactive"]), \
                         patch("explain_video.__main__.make_providers", return_value=(FakeTranscription(), FakeRewrite(), ToneTTS(.4))), \
                         patch("sys.stdout", output):
                        self.assertEqual(main(), 0)
                    folder = root / f"Видео {extension}.explained"
                    self.assertEqual({p.name for p in folder.iterdir()},
                                     {f"Видео {extension}.explained.mp4", "script.txt", "details", ".gitignore"})
                    self.assertEqual({p.name for p in (folder / "details").iterdir()},
                                     {"transcript.txt", "voice.wav", "meta.json"})
                    paths = output_paths(source, output_dir=folder)
                    info = probe(paths["video"])
                    self.assertEqual([s["codec_name"] for s in info["streams"]], ["h264", "aac"])
                    self.assertEqual(source.read_bytes(), original)
                    self.assertIn(paths["video"].as_uri(), output.getvalue())
                    self.assertFalse(output_paths(source)["transcript"].exists())

    def test_unsupported_output_filesystem_fails_before_paid_calls(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "input.mp4"
            source.touch()
            transcription, rewrite, tts, sync = Mock(), Mock(), Mock(), Mock()
            info = {"streams": [
                {"codec_type": "video", "duration": "1"},
                {"codec_type": "audio", "duration": "1"},
            ]}
            with patch("explain_video.media.probe", return_value=info), \
                 patch("explain_video.pipeline.os.link", side_effect=OSError("not supported")):
                with self.assertRaisesRegex(ValueError, "must support hard links"):
                    run_pipeline(source, transcription, rewrite, tts, "fixture", sync_engine=sync)
            self.assertEqual(transcription.mock_calls, [])
            self.assertEqual(rewrite.mock_calls, [])
            self.assertEqual(tts.mock_calls, [])
            self.assertEqual(sync.mock_calls, [])
            self.assertEqual(list(Path(directory).iterdir()), [source])

    def test_pipeline_three_timing_branches(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for seconds in (1, 1.9, 3):
                with self.subTest(narration=seconds):
                    source = root / f"screen {seconds}.mp4"
                    command(["ffmpeg", "-nostdin", "-v", "error", "-n", "-f", "lavfi", "-i",
                             "testsrc2=size=320x180:rate=20:duration=2", "-f", "lavfi", "-i",
                             "sine=frequency=220:sample_rate=16000:duration=2", "-c:v", "libx264",
                             "-c:a", "aac", "-shortest", str(source)])
                    before = hashlib.sha256(source.read_bytes()).hexdigest()
                    rewrite = FakeRewrite()
                    facts = "Данные обновляются раз в час." if seconds == 1 else None
                    prefix = root / "variant" if facts else None
                    meta = run_pipeline(source, FakeTranscription(), rewrite, ToneTTS(seconds), "fixture", lambda s: None,
                                        facts=facts, output_prefix=prefix)
                    paths = output_paths(source, prefix, include_facts=facts is not None)
                    self.assertEqual(rewrite.facts_received, facts)
                    if facts:
                        self.assertEqual(paths["facts"].read_text(), facts + "\n")
                        self.assertEqual(meta["auxiliary_facts"]["sha256"], hashlib.sha256(paths["facts"].read_bytes()).hexdigest())
                        self.assertFalse(output_paths(source)["video"].exists())
                    else:
                        self.assertIsNone(meta["auxiliary_facts"])
                    self.assertTrue(all(p.exists() for p in paths.values()))
                    self.assertEqual(before, hashlib.sha256(source.read_bytes()).hexdigest())
                    info = probe(paths["video"])
                    self.assertEqual([s["codec_type"] for s in info["streams"]], ["video", "audio"])
                    self.assertEqual(info["streams"][0]["width"], 320)
                    self.assertAlmostEqual(duration(info, "video"), max(2, seconds) if seconds != 1.9 else 1.9, delta=.1)
                    self.assertEqual(json.loads(paths["meta"].read_text()), meta)
                    # Verify signal content: new 880 Hz tone dominates, source 220 Hz is absent.
                    raw = command(["ffmpeg", "-v", "error", "-i", str(paths["video"]), "-t", "0.5",
                                   "-map", "0:a:0", "-f", "f32le", "-ar", "16000", "-ac", "1", "pipe:1"])
                    samples = array.array("f", raw)
                    def energy(hz):
                        return abs(sum(s * complex(math.cos(2*math.pi*hz*i/16000), math.sin(2*math.pi*hz*i/16000))
                                       for i, s in enumerate(samples)))
                    self.assertGreater(energy(880), energy(220) * 100)
                    with self.assertRaisesRegex(ValueError, "already exists"):
                        run_pipeline(source, FakeTranscription(), FakeRewrite(), ToneTTS(seconds), "fixture", output_prefix=prefix)

    def test_no_audio_fails_before_provider(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "silent.mp4"
            command(["ffmpeg", "-nostdin", "-v", "error", "-n", "-f", "lavfi", "-i",
                     "color=size=64x64:duration=0.2", str(source)])
            with self.assertRaisesRegex(ValueError, "no audio"):
                run_pipeline(source, None, None, None, "unused")
            self.assertFalse(any(p.exists() for p in output_paths(source).values()))

    def test_failed_rewrite_retains_transcript_only(self):
        class FailedRewrite:
            def rewrite(self, transcript):
                raise RuntimeError("provider unavailable")
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "input.mp4"
            command(["ffmpeg", "-nostdin", "-v", "error", "-n", "-f", "lavfi", "-i",
                     "color=size=64x64:duration=0.2", "-f", "lavfi", "-i", "anullsrc",
                     "-t", "0.2", str(source)])
            with self.assertRaisesRegex(RuntimeError, "provider unavailable"):
                folder = Path(directory) / "run"
                folder.mkdir()
                run_pipeline(source, FakeTranscription(), FailedRewrite(), None, "unused", lambda s: None,
                             output_dir=folder)
            paths = output_paths(source, output_dir=folder)
            self.assertTrue(paths["transcript"].exists())
            self.assertFalse(paths["video"].exists())
            self.assertFalse(list(folder.glob(".explain-video-*")))
