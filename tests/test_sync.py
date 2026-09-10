import array
import hashlib
import json
import math
import tempfile
import unittest
import wave
from pathlib import Path
from unittest.mock import Mock, patch

import httpx

from explain_video import media
from explain_video.pipeline import run_pipeline, output_paths
from explain_video.sync import SyncEngine, TimedTranscription, render_synced, sample_times, scene_timing, validate_plan, validate_timestamps
from explain_video.providers import OpenAIAPI


def raw_plan():
    return {"scenes": [
        {"source_start": 0, "text": "Красный.", "reason": "Красный экран"},
        {"source_start": 2, "text": "Зелёный.", "reason": "Зелёный экран"},
        {"source_start": 4, "text": "Синий.", "reason": "Синий экран"},
    ]}


SCRIPT = "Красный. Зелёный. Синий."


class SyncLogicTests(unittest.TestCase):
    def test_plan_covers_source_and_exact_script(self):
        scenes = validate_plan(raw_plan(), SCRIPT, 6)
        self.assertEqual([(s["source_start"], s["source_end"]) for s in scenes], [(0, 2), (2, 4), (4, 6)])

    def test_invalid_plans(self):
        cases = []
        for value in [float("nan"), float("inf"), True, -1, 6, 0, 0.2]:
            plan = raw_plan()
            plan["scenes"][1]["source_start"] = value
            cases.append(plan)
        for value in ["", "Подменённый текст.", "Синий."]:
            plan = raw_plan()
            plan["scenes"][1]["text"] = value
            cases.append(plan)
        plan = raw_plan()
        plan["scenes"][0]["source_start"] = 1
        cases.extend([plan, {"scenes": []}, {"scenes": raw_plan()["scenes"] * 3}])
        for plan in cases:
            with self.subTest(plan=plan), self.assertRaises(ValueError):
                validate_plan(plan, SCRIPT, 6)

    def test_sampling_bounded_and_inside_video(self):
        for duration in [0.1, 1, 88, 600]:
            times = sample_times(duration)
            self.assertLessEqual(len(times), 24)
            self.assertEqual(times[0], 0)
            self.assertTrue(all(0 <= t < duration for t in times))

    def test_scene_speed_limits_and_padding(self):
        self.assertAlmostEqual(scene_timing(2, 1).speed, 1.1)
        self.assertGreater(scene_timing(2, 1).quiet_seconds, 0)
        self.assertAlmostEqual(scene_timing(2, 3).speed, .9)
        self.assertGreater(scene_timing(2, 3).freeze_seconds, 0)

    def test_bad_timestamps(self):
        for segments in [[], None, [{"start": -1, "end": 1, "text": "x"}],
                         [{"start": 0, "end": 8, "text": "x"}],
                         [{"start": 6.1, "end": 6.2, "text": "x"}],
                         [{"start": float("nan"), "end": 1, "text": "x"}]]:
            with self.assertRaises(ValueError):
                validate_timestamps(segments, 6)
        for duration in [0, -1, float("nan"), float("inf")]:
            with self.assertRaises(ValueError):
                validate_plan(raw_plan(), SCRIPT, duration)

    def test_gap_rejected_before_tts(self):
        plan = {"source_duration": 6, "scenes": validate_plan(raw_plan(), SCRIPT, 6)}
        plan["scenes"][0]["source_end"] = 1
        tts = Mock()
        with self.assertRaisesRegex(ValueError, "gaps or overlaps"):
            render_synced(Path("source"), SCRIPT, plan, tts, "marin", Path("assets"), Path("work"))
        tts.synthesize.assert_not_called()

    def test_timed_transcription_contract(self):
        with tempfile.TemporaryDirectory() as directory:
            wav = Path(directory) / "audio.wav"
            with wave.open(str(wav), "wb") as f:
                f.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
                f.writeframes(b"\0\0" * 16000)
            def handler(request):
                self.assertIn(b"whisper-1", request.content)
                self.assertIn(b"verbose_json", request.content)
                self.assertIn(b"timestamp_granularities[]", request.content)
                return httpx.Response(200, json={"text": "Привет.", "segments": [{"start": 0, "end": 1, "text": "Привет."}]})
            with httpx.Client(transport=httpx.MockTransport(handler)) as client:
                provider = TimedTranscription(OpenAIAPI("test", client))
                self.assertEqual(provider.transcribe(wav), "Привет.")
                self.assertEqual(len(provider.segments), 1)


class SyncMediaTests(unittest.TestCase):
    def test_three_scene_sync_preserves_colors_audio_and_approved_script(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.mp4"
            media.command(["ffmpeg", "-nostdin", "-v", "error", "-n",
                "-f", "lavfi", "-i", "color=red:size=160x90:rate=30:duration=2",
                "-f", "lavfi", "-i", "color=green:size=160x90:rate=30:duration=2",
                "-f", "lavfi", "-i", "color=blue:size=160x90:rate=30:duration=2",
                "-f", "lavfi", "-i", "sine=frequency=220:sample_rate=24000:duration=6",
                "-filter_complex", "[0:v][1:v][2:v]concat=n=3:v=1:a=0[v]", "-map", "[v]", "-map", "3:a:0",
                "-c:v", "libx264", "-c:a", "aac", str(source)])
            original = hashlib.sha256(source.read_bytes()).hexdigest()
            request_count = []
            def handler(request):
                request_count.append(1)
                payload = json.loads(request.content)
                images = [c for c in payload["input"][0]["content"] if c["type"] == "input_image"]
                self.assertGreaterEqual(len(images), 2)
                self.assertTrue(images[0]["image_url"].startswith("data:image/jpeg;base64,"))
                return httpx.Response(200, json={"status": "completed", "output": [
                    {"type": "message", "content": [{"type": "output_text", "text": json.dumps(raw_plan(), ensure_ascii=False)}]}]})
            transcriber = Mock()
            transcriber.name, transcriber.model = "fixture", "fixture"
            transcriber.transcribe.return_value = SCRIPT
            transcriber.segments = [{"start": 0, "end": 6, "text": SCRIPT}]
            rewriter = Mock()
            class ToneTTS:
                name = "test"
                def synthesize(self, text, target, voice):
                    hz, seconds = {"Красный.": (440, 1), "Зелёный.": (660, 3), "Синий.": (880, 2)}[text]
                    media.command(["ffmpeg", "-v", "error", "-n", "-f", "lavfi", "-i",
                                   f"sine=frequency={hz}:sample_rate=24000:duration={seconds}", str(target)])
            prefix = root / "synced"
            with httpx.Client(transport=httpx.MockTransport(handler)) as client:
                engine = SyncEngine(OpenAIAPI("test", client), "test", transcriber)
                meta = run_pipeline(source, transcriber, rewriter, ToneTTS(), "marin", lambda s: None,
                                    sync_engine=engine, narration_script=SCRIPT, output_prefix=prefix)
            rewriter.rewrite.assert_not_called()
            self.assertEqual(len(request_count), 1)
            paths = output_paths(source, prefix, include_sync=True)
            self.assertTrue(all(p.exists() for p in paths.values()))
            sync = json.loads(paths["sync"].read_text())
            self.assertEqual(paths["script"].read_text().strip(), SCRIPT)
            self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(), original)
            info = media.probe(paths["video"])
            self.assertEqual([s["codec_type"] for s in info["streams"]], ["video", "audio"])
            self.assertAlmostEqual(media.duration(info, "video"), sync["output_duration"], delta=.1)
            self.assertAlmostEqual(media.duration(info, "audio"), sync["output_duration"], delta=.1)
            for scene, color_index, hz in zip(sync["scenes"], [0, 1, 2], [440, 660, 880]):
                timestamp = scene["output_start"] + .3
                pixel = media.command(["ffmpeg", "-v", "error", "-ss", str(timestamp), "-i", str(paths["video"]),
                    "-frames:v", "1", "-vf", "scale=1:1", "-pix_fmt", "rgb24", "-f", "rawvideo", "pipe:1"])
                self.assertEqual(max(range(3), key=lambda i: pixel[i]), color_index)
                audio = media.command(["ffmpeg", "-v", "error", "-ss", str(timestamp), "-i", str(paths["video"]),
                    "-t", "0.25", "-map", "0:a:0", "-ar", "24000", "-f", "f32le", "pipe:1"])
                samples = array.array("f", audio)
                def energy(frequency):
                    return abs(sum(x * complex(math.cos(2*math.pi*frequency*i/24000), math.sin(2*math.pi*frequency*i/24000)) for i, x in enumerate(samples)))
                self.assertGreater(energy(hz), energy(220) * 100)
            self.assertEqual(meta["rewrite_model"], "supplied-script")
            with self.assertRaisesRegex(ValueError, "already exists"):
                run_pipeline(source, transcriber, rewriter, ToneTTS(), "marin", sync_engine=engine,
                             narration_script=SCRIPT, output_prefix=prefix)
