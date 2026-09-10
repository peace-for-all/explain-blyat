# Contributing

Install with `python -m pip install -e .` in a virtual environment. Install
FFmpeg, then run `python -m unittest discover -s tests -v`. Tests synthesize
small media fixtures and mock provider requests; do not use paid API calls or
personal recordings in tests.

## Code map

- `explain_video/__main__.py`: CLI arguments and preflight.
- `config.py`: environment-file parsing and provider defaults.
- `providers.py`: transcription, rewriting, questions, and speech providers.
- `interactive.py`: terminal answers.
- `pipeline.py`: stage orchestration, artifacts, and no-overwrite publication.
- `media.py`: FFmpeg commands and whole-video timing.
- `sync.py`: experimental timestamp/screenshot planning and scene rendering.

Preserve source files, refuse output collisions, and retain completed artifacts
on failures. Keep secrets out of errors and metadata. Provider changes should
have mocked contract tests; timing changes should have synthetic media tests.
Document changes in data sent to external services and any new paid calls.

For bug reports, include OS, Python and FFmpeg versions, the command with private
paths removed, and a sanitized error. Never attach `.env`, API keys, private
screen captures, transcripts, or generated artifacts. Prefer synthetic input
that reproduces the problem.

## Source releases

Run `python scripts/export_source.py` to create `dist/explain-video-source.zip`.
The exporter uses an explicit source-file allowlist and rejects symlinks; it
excludes local credentials, media, artifacts, build outputs, and Git history.
Review the archive contents before uploading. MIT applies to contributions.
