# explain-video

Turn a Russian screen recording into a clearer narrated demo: transcribe the
speech, ask for missing context, rewrite it in plain Russian, and replace the
original audio with a synthetic narrator. The screen footage stays in order.

This is an experimental command-line tool for **Linux/macOS and Python 3.11+**. It
requires **FFmpeg** (including ffprobe and the libx264 encoder), an **OpenAI API
key**, and internet access. API calls cost money. Russian is currently built
into transcription and rewriting; this is not a multilingual interface.

## Install

On Ubuntu/Debian with Python 3.11 or newer:

```bash
sudo apt update
sudo apt install git ffmpeg python3-venv
```

On macOS, install [Homebrew](https://docs.brew.sh/Installation) first, then:

```bash
brew install python ffmpeg
```

[Homebrew's FFmpeg package](https://formulae.brew.sh/formula/ffmpeg) includes the
media tools. On either platform, continue with:

```bash
git clone https://github.com/peace-for-all/explain-blyat.git
cd explain-blyat
python3 -m venv .venv
source .venv/bin/activate
python -m pip install .
cp .env.example .env
```

Edit `.env` and set `OPENAI_API_KEY` to your own key. Do not share this file.
There is no shared account or hosted backend. Native Windows is not verified;
Windows users can use a Linux environment in WSL.

## Run

```bash
explain-video "screen recording.mp4"
```

The command transcribes the first audio track, then asks up to five questions
in the terminal. Answer each with one or more lines and finish with a blank
line; a blank first line skips it. It then rewrites, generates narration, and
saves everything in a new `screen recording.explained/` folder beside the source. The original video
is never overwritten and all original audio is excluded from the output.

## Find your result

For `explain-video demo.mov`, the result looks like:

```text
demo.mov                         original recording
demo.explained/
  demo.explained.mp4              finished video — open or share this
  script.txt                     narration text — review or edit this
  details/                       transcript, voice, answers, and diagnostics
```

The terminal prints the absolute video path, a `file://` link (clickable in
terminals that support it), and copyable commands to play the video and open its
folder. On macOS, it also provides `open -R ...` to reveal the video in Finder.
Nothing opens automatically.

Run the same command again to create `demo.explained-2/`, then `-3/`, and so on.
Previous results remain intact. Use `--output-dir my-demo` to choose a folder;
that folder must be new and its parent must exist. Sync runs use `demo.synced/`.
The old `--output-prefix` option still produces flat files for existing scripts.
Old flat output files are left in place; the new layout applies to new runs.

## Input formats

Input is decoded by FFmpeg rather than restricted by filename extension. MP4,
MOV, MKV, and WebM are covered by synthetic end-to-end tests. Other formats may
work when your FFmpeg build can decode them. The file needs a video stream, an
audio stream, and readable duration metadata. See
[FFmpeg's format documentation](https://ffmpeg.org/ffmpeg-formats.html).
The output is always **MP4 with H.264 video and AAC audio**. This targets ordinary
SDR screen recordings, not every codec, HDR recording, or camera format.

## More commands

```bash
# Skip questions (also required for unattended runs).
explain-video input.mp4 --non-interactive

# Add context and save a separate version.
explain-video input.mp4 --facts extra-facts.txt --output-dir demo-v2

# Use a script you have reviewed; still transcribes the input.
explain-video input.mp4 --script narration.txt --output-dir demo-v3

# Experimental scene timing; sends sampled screenshots to OpenAI.
explain-video input.mp4 --sync

explain-video --help
```

`python -m explain_video` works too. Activate the virtual environment in each
new terminal. Configuration defaults to `.env` in your **current directory**;
use `--config /path/to/.env` when running elsewhere. Exported shell variables
override the file. The file accepts `KEY=value` with optional surrounding quotes;
shell expansion and inline comments are not supported.

Run folders include private transcript, voice, metadata, and any questions/answers.
Share the finished MP4, rather than the whole run folder, unless you intend to
share those supporting files too. Each new run folder contains a hidden
`.gitignore` that excludes its contents from ordinary Git adds.

## Configuration

See [`.env.example`](.env.example) for model and voice settings. OpenAI narration
is the default. For optional Microsoft Edge narration, set
`EXPLAIN_TTS_PROVIDER=edge` and leave `EXPLAIN_VOICE` blank (or choose
`ru-RU-SvetlanaNeural`). OpenAI transcription and rewriting still need your key.
Edge narration also uses an online service.

## Privacy, cost, and limits

- Audio, transcripts, supplied facts, and answers are sent to OpenAI. Narration
  text is sent to the selected speech provider. `--sync` additionally sends
  sampled screen images to OpenAI. Only process material you may share with them.
- No API keys, recordings, or example output from the author's machine are
  included. Each user supplies their own recording and credentials.
- There is no automatic paid retry or resume. A rerun starts paid stages again
  in a new folder. Completed artifacts survive later failures and cancellation.
- Output storage must support hard links (for example, APFS on Mac or ext4 on Linux).
  For FAT/exFAT drives, use `--output-dir` on your local system disk.
- Default timing matches overall duration, with a final-frame hold or silence
  when needed. Scene sync is experimental. Review factual accuracy and timing
  before sharing, and disclose that the voice is synthetic.

See the [full usage guide](docs/usage.md) for timing rules, artifacts, provider
settings, interruption behavior, and media limits.

## Development

```bash
python -m pip install -e .
python -m unittest discover -s tests -v
python -m pip check
```

Tests use generated video/audio and mocked APIs, so they need FFmpeg but no API
key or paid calls. GitHub Actions runs them on Linux with Python 3.11–3.14 and
macOS with Python 3.14, including installation from a built wheel outside the
checkout. CI covers synthetic media and mocked API contracts; it does not test
live provider access or opening a desktop video player. See
[CONTRIBUTING.md](CONTRIBUTING.md) for the code map and contribution guidance.

## License

[MIT](LICENSE).
