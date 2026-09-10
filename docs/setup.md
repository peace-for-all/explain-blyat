# Manual installation and setup details

The recommended path is `./setup.sh`, followed by setting your own
`OPENAI_API_KEY` in `.env` and running `./run "video.mp4"`.
Setup downloads software; it does not upload recordings or call OpenAI.

## System dependencies

Ubuntu/Debian, using Python 3.11 or newer:

```bash
sudo apt update
sudo apt install ffmpeg python3-venv
```

macOS with [Homebrew](https://docs.brew.sh/Installation):

```bash
brew install python ffmpeg
```

Other systems need Python 3.11+, venv/pip, curl (for the automatic installer), and
FFmpeg with ffprobe, libx264 and AAC encoding. The automatic installer checks
media tools before downloading Python packages. If the available FFmpeg lacks
encoders, it stops with an explanation instead of claiming the tool is ready.

## Manual Python environment

From the checkout directory:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install .
# Only create .env if you do not already have one:
(umask 077; set -C; cat .env.example > .env)
```

Edit `.env` to add your key. The copy command refuses to overwrite an existing
file. Run `./run "video.mp4"` or use `explain-video` with the environment activated.

## What automatic setup changes

System packages are installed only when media/download tools are missing or
incomplete. Privileged commands are limited to those package-manager operations
and the official Homebrew bootstrap, if necessary.

[uv's unmanaged installer](https://docs.astral.sh/uv/reference/installer/) is
used to keep its binaries in `.tools/` without editing shell profiles. Its
[managed Python](https://docs.astral.sh/uv/guides/install-python/) distribution
and cache are kept under `.tools/` too. Python packages live in `.venv/`, never in
system Python. Existing virtual environments are validated and reused; setup
reinstalls this local application so source updates take effect.

A new `.env` has mode 0600. Existing config files and values are left unchanged.
The script does not print keys. A configured key means only that a value exists;
setup makes no paid requests or account-access checks.

If a package download or system installation fails, fix the reported cause and
rerun setup. Completed installations can be reused. For a broken or outdated
`.venv`, move it aside before rerunning; the script never deletes it for you.
The checkout must be writable by your normal user. Symlinked `.venv`, `.tools`,
or `.env` paths are rejected to avoid modifying an unexpected location.
