import argparse
import sys
from pathlib import Path

from .config import load_config
from .pipeline import output_paths, run_pipeline
from .providers import make_providers
from .interactive import read_answer
from .sync import SyncEngine, TimedTranscription


def main() -> int:
    parser = argparse.ArgumentParser(description="Replace a screen recording's audio with a simple Russian explanation.")
    parser.add_argument("input", type=Path)
    parser.add_argument("--voice", help="Voice identifier for the configured TTS provider")
    parser.add_argument("--sync", action="store_true", help="Experimental scene alignment using timestamps and screenshots")
    parser.add_argument("--script", type=Path, help="Reuse an approved UTF-8 narration script; skips questions and rewriting")
    parser.add_argument("--non-interactive", action="store_true", help="Skip listener questions (required without a terminal)")
    parser.add_argument("--facts", type=Path, help="UTF-8 text file with extra facts or explicit corrections")
    parser.add_argument("--output-prefix", type=Path, help="Output path prefix for a separate version, e.g. demo-v2")
    parser.add_argument("--config", type=Path, default=Path(".env"), help="Environment file (default: .env in current directory)")
    args = parser.parse_args()
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
                args.output_prefix = args.input.with_name(args.input.stem + ".synced")
        metadata = run_pipeline(args.input, *providers, config.voice,
                                progress=lambda message: print(message, flush=True),
                                facts=facts, output_prefix=args.output_prefix,
                                question_provider=providers[1] if interactive else None,
                                answer_question=read_answer if interactive else None,
                                sync_engine=sync_engine, narration_script=narration_script)
    except (ValueError, RuntimeError, OSError) as error:
        print(f"explain-video: {error}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nCancelled; completed intermediate artifacts were retained.", file=sys.stderr)
        return 130
    print(f"Saved: {output_paths(args.input, args.output_prefix)['video']}")
    print(f"Video {metadata['input_duration']:.1f}s → narration {metadata['narration_duration']:.1f}s. {metadata['video_adjustment']}.")
    for warning in metadata["warnings"]:
        print(f"Note: {warning}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
