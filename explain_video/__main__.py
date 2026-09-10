import argparse
import shlex
import sys
from pathlib import Path

from .config import load_config
from .pipeline import output_paths, run_pipeline
from .providers import make_providers
from .interactive import read_answer
from .sync import SyncEngine, TimedTranscription


def create_run_directory(source: Path, requested: Path | None, synced: bool) -> Path:
    if requested is not None:
        directory = requested.absolute()
        try:
            directory.mkdir()
        except FileExistsError as error:
            raise ValueError(f"Output directory already exists: {directory}; choose a new --output-dir") from error
        (directory / ".gitignore").write_text("*\n", encoding="utf-8")
        return directory
    base = source.absolute().with_name(source.stem + (".synced" if synced else ".explained"))
    number = 1
    while True:
        directory = base if number == 1 else base.with_name(f"{base.name}-{number}")
        try:
            directory.mkdir()
        except FileExistsError:
            number += 1
            continue
        (directory / ".gitignore").write_text("*\n", encoding="utf-8")
        return directory


def print_result(video: Path, script: Path) -> None:
    video, script = video.absolute(), script.absolute()
    print(f"\nVideo ready: {video}")
    print(f"Video link: {video.as_uri()}")
    print(f"Narration script: {script}")
    if sys.platform == "darwin":
        print(f"Play video: {shlex.join(['open', str(video)])}")
        print(f"Show in Finder: {shlex.join(['open', '-R', str(video)])}")
    elif sys.platform.startswith("linux"):
        print(f"Play video: {shlex.join(['xdg-open', str(video)])}")
        print(f"Open folder: {shlex.join(['xdg-open', str(video.parent)])}")
    else:
        print(f"Open this folder in your file manager and double-click the video: {video.parent}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Replace a screen recording's audio with a simple Russian explanation.")
    parser.add_argument("input", type=Path, nargs="?", help="Recording with video and audio (MP4, MOV, MKV, WebM, etc.; decoded by FFmpeg)")
    parser.add_argument("--guide", action="store_true", help="Open an offline question-based planning and recording guide")
    parser.add_argument("--voice", help="Voice identifier for the configured TTS provider")
    parser.add_argument("--sync", action="store_true", help="Experimental scene alignment using timestamps and screenshots")
    parser.add_argument("--script", type=Path, help="Reuse an approved UTF-8 narration script; skips questions and rewriting")
    parser.add_argument("--non-interactive", action="store_true", help="Skip listener questions (required without a terminal)")
    parser.add_argument("--facts", type=Path, help="UTF-8 text file with extra facts or explicit corrections")
    output = parser.add_mutually_exclusive_group()
    output.add_argument("--output-dir", type=Path, help="New run folder (default: INPUT.explained, numbered on reruns)")
    output.add_argument("--output-prefix", type=Path, help="Legacy flat output path prefix, e.g. demo-v2; use --output-dir for grouped files")
    parser.add_argument("--config", type=Path, default=Path(".env"), help="Environment file (default: .env in current directory)")
    args = parser.parse_args()
    if args.guide:
        if args.input is not None or any((args.voice, args.sync, args.script, args.non_interactive,
                                         args.facts, args.output_dir, args.output_prefix)):
            parser.error("--guide is a separate planning step; use it without video-processing options")
        from .guide import open_guide
        try:
            open_guide()
        except OSError as error:
            print(f"explain-video: {error}", file=sys.stderr)
            return 1
        return 0
    if args.input is None:
        parser.error("provide a recording, or use --guide to prepare one")
    run_directory = None
    try:
        if not args.input.is_file():
            raise ValueError(f"Input file not found: {args.input}")
        if args.config != Path(".env") and not args.config.is_file():
            raise ValueError(f"Config file not found: {args.config}")
        config = load_config(args.config, args.voice)
        narration_script = args.script.read_text(encoding="utf-8") if args.script else None
        if narration_script is not None and not narration_script.strip():
            raise ValueError("Supplied script is empty")
        if args.script and args.facts:
            raise ValueError("--script cannot be combined with --facts; revise the script or omit --script")
        facts = args.facts.read_text(encoding="utf-8") if args.facts is not None else None
        if facts is not None and not facts.strip():
            raise ValueError("Facts file is empty; add facts or omit --facts")
        interactive = not args.non_interactive and args.script is None
        if interactive and not sys.stdin.isatty():
            raise ValueError("Interactive questions need a terminal. Run in a terminal, or use --non-interactive to skip questions.")
        providers = make_providers(config)
        sync_engine = None
        if args.sync:
            transcriber = TimedTranscription(providers[0].api)
            sync_engine = SyncEngine(providers[0].api, config.rewrite_model, transcriber)
            providers = (transcriber, providers[1], providers[2])
        if args.output_prefix is None:
            run_directory = create_run_directory(args.input, args.output_dir, args.sync)
            print(f"Run folder: {run_directory}", flush=True)
        metadata = run_pipeline(args.input, *providers, config.voice,
                                progress=lambda message: print(message, flush=True),
                                facts=facts, output_prefix=args.output_prefix,
                                question_provider=providers[1] if interactive else None,
                                answer_question=read_answer if interactive else None,
                                sync_engine=sync_engine, narration_script=narration_script,
                                output_dir=run_directory)
    except (ValueError, RuntimeError, OSError) as error:
        print(f"explain-video: {error}", file=sys.stderr)
        if run_directory is not None:
            print(f"Run folder (any completed files are retained): {run_directory}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nCancelled; completed intermediate artifacts were retained.", file=sys.stderr)
        if run_directory is not None:
            print(f"Run folder: {run_directory}", file=sys.stderr)
        return 130
    paths = output_paths(args.input, args.output_prefix, output_dir=run_directory)
    print_result(paths["video"], paths["script"])
    print(f"Video {metadata['input_duration']:.1f}s → narration {metadata['narration_duration']:.1f}s. {metadata['video_adjustment']}.")
    for warning in metadata["warnings"]:
        print(f"Note: {warning}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
