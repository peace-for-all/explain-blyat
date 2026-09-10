import json
import math
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path


def command(args: list[str]) -> bytes:
    result = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if result.returncode:
        raise RuntimeError(f"{args[0]} failed: {result.stderr.decode(errors='replace')[-2000:]}")
    return result.stdout


def check_tools() -> None:
    for tool in ("ffmpeg", "ffprobe"):
        if not shutil.which(tool):
            raise ValueError(f"Missing {tool}; install ffmpeg (Ubuntu: sudo apt install ffmpeg; macOS: brew install ffmpeg)")


def probe(path: Path) -> dict:
    return json.loads(command(["ffprobe", "-v", "error", "-show_format", "-show_streams",
                               "-of", "json", str(path.resolve())]))


def duration(info: dict, kind: str) -> float:
    stream = next((s for s in info["streams"] if s["codec_type"] == kind), None)
    if stream is None:
        raise ValueError(f"Input has no {kind} stream")
    value = float(stream.get("duration", info.get("format", {}).get("duration", 0)))
    if not math.isfinite(value) or value <= 0:
        raise ValueError(f"Cannot determine positive {kind} duration")
    return value


@dataclass(frozen=True)
class Timing:
    speed: float
    freeze_seconds: float
    quiet_seconds: float
    output_duration: float
    description: str


def choose_timing(video: float, narration: float) -> Timing:
    if any(not math.isfinite(v) or v <= 0 for v in (video, narration)):
        raise ValueError("Durations must be positive and finite")
    ratio = video / narration
    if 0.9 <= ratio <= 1.1:
        return Timing(ratio, 0, 0, narration, f"Video speed {ratio:.4f}x")
    if narration > video:
        return Timing(1, narration - video, 0, narration, f"Final frame frozen for {narration-video:.2f}s")
    return Timing(1, 0, video - narration, video, f"Original footage preserved; quiet tail {video-narration:.2f}s")


def extract_audio(source: Path, target: Path) -> None:
    command(["ffmpeg", "-nostdin", "-v", "error", "-n", "-i", str(source.resolve()),
             "-map", "0:a:0", "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(target)])


def render(source: Path, voice: Path, target: Path, timing: Timing) -> None:
    # Map ONLY the new audio: original OBS audio tracks can never enter the output.
    filters = [f"setpts=(PTS-STARTPTS)/{timing.speed:.10f}"]
    if timing.freeze_seconds:
        filters.append(f"tpad=stop_mode=clone:stop_duration={timing.freeze_seconds:.6f}")
    # H.264 yuv420p needs even dimensions; pad at most one pixel, never downscale.
    filters.append("pad=ceil(iw/2)*2:ceil(ih/2)*2")
    command(["ffmpeg", "-nostdin", "-v", "error", "-n", "-i", str(source.resolve()),
             "-i", str(voice.resolve()), "-map", "0:v:0", "-map", "1:a:0",
             "-map_metadata", "-1", "-map_chapters", "-1", "-vf", ",".join(filters),
             "-af", "asetpts=PTS-STARTPTS,apad", "-t", f"{timing.output_duration:.6f}",
             "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p",
             "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(target)])
