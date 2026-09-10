#!/usr/bin/env bash
# Compatible with macOS's Bash 3.2. Run as your normal user, not with sudo.
set -Eeuo pipefail

SETUP_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)
SETUP_TEMP=""

say() { printf '\n%s\n' "$*"; }
fail() { printf '\nSetup stopped: %s\n' "$*" >&2; exit 1; }
cleanup() { if [[ -n "$SETUP_TEMP" ]]; then rm -rf "$SETUP_TEMP"; fi; }

have_media() {
    command -v ffmpeg >/dev/null 2>&1 && command -v ffprobe >/dev/null 2>&1 || return 1
    local encoders
    encoders=$(ffmpeg -hide_banner -encoders 2>/dev/null) || return 1
    [[ "$encoders" == *" libx264 "* && "$encoders" == *" aac "* ]]
}

as_admin() {
    command -v sudo >/dev/null 2>&1 || fail "sudo is required to install system packages; ask an administrator to install FFmpeg and curl, then rerun."
    sudo "$@"
}

install_linux_dependencies() {
    if command -v apt-get >/dev/null 2>&1; then
        as_admin apt-get update
        as_admin apt-get install -y ffmpeg curl ca-certificates
    elif command -v dnf >/dev/null 2>&1; then
        as_admin dnf install -y ffmpeg curl ca-certificates
    elif command -v pacman >/dev/null 2>&1; then
        # Do not refresh package databases separately: Arch partial upgrades are unsupported.
        as_admin pacman -S --needed --noconfirm ffmpeg curl ca-certificates
    elif command -v zypper >/dev/null 2>&1; then
        as_admin zypper --non-interactive install ffmpeg curl ca-certificates
    else
        fail "No supported Linux package manager found (apt, dnf, pacman, zypper). Install FFmpeg with libx264/AAC and curl, then rerun."
    fi
}

download() {
    curl --fail --silent --show-error --location --proto '=https' --tlsv1.2 \
        --connect-timeout 20 --max-time 180 --retry 2 "$1" --output "$2"
}

install_mac_dependencies() {
    local brew_command=""
    if command -v brew >/dev/null 2>&1; then
        brew_command=$(command -v brew)
    elif [[ -x /opt/homebrew/bin/brew ]]; then
        brew_command=/opt/homebrew/bin/brew
    elif [[ -x /usr/local/bin/brew ]]; then
        brew_command=/usr/local/bin/brew
    else
        say "Installing Homebrew using its official installer (it may request your password or Apple's developer tools)."
        download https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh "$SETUP_TEMP/homebrew-install.sh"
        /bin/bash "$SETUP_TEMP/homebrew-install.sh"
        if [[ -x /opt/homebrew/bin/brew ]]; then
            brew_command=/opt/homebrew/bin/brew
        elif [[ -x /usr/local/bin/brew ]]; then
            brew_command=/usr/local/bin/brew
        else
            fail "Homebrew installation did not finish. Complete https://brew.sh installation, then rerun ./setup.sh."
        fi
    fi
    eval "$("$brew_command" shellenv)"
    "$brew_command" install ffmpeg
}

main() {
    if [[ "${1:-}" == --help || "${1:-}" == -h ]]; then
        printf '%s\n' 'Usage: ./setup.sh' 'Install system media tools and a local Python environment. Preserve existing .env and .venv.'
        return
    fi
    [[ $# -eq 0 ]] || fail "Unknown argument. Use ./setup.sh --help."
    [[ $EUID -ne 0 ]] || fail "Run ./setup.sh as your normal user, without sudo. Only system package installation uses sudo."
    case "$(uname -s)" in
        Linux) SETUP_OS=Linux ;;
        Darwin) SETUP_OS=macOS ;;
        *) fail "Supported systems: Linux and macOS. On Windows, use WSL with Linux." ;;
    esac
    say "Setting up explain-video on $SETUP_OS in $SETUP_ROOT"
    if [[ "$SETUP_OS" == macOS ]]; then
        export PATH="$PATH:/opt/homebrew/bin:/usr/local/bin"
    fi
    [[ ! -L "$SETUP_ROOT/.tools" && ! -L "$SETUP_ROOT/.venv" ]] || fail ".tools and .venv must not be symlinks; existing paths were left unchanged."
    [[ ! -L "$SETUP_ROOT/.env" ]] || fail ".env must not be a symlink; it was left unchanged."
    if [[ -e "$SETUP_ROOT/.env" && ! -f "$SETUP_ROOT/.env" ]]; then
        fail "Existing .env is not a regular config file; it was left unchanged."
    fi
    if [[ -e "$SETUP_ROOT/.venv" ]]; then
        [[ -f "$SETUP_ROOT/.venv/pyvenv.cfg" && -x "$SETUP_ROOT/.venv/bin/python" ]] || fail "Existing .venv is not a working virtual environment. Move it aside yourself, then rerun."
        "$SETUP_ROOT/.venv/bin/python" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) and sys.prefix != sys.base_prefix else 1)' || fail "Existing .venv requires Python 3.11+. It was left unchanged; move it aside before rerunning."
    fi
    SETUP_TEMP=$(mktemp -d "${TMPDIR:-/tmp}/explain-video-setup.XXXXXX")
    trap cleanup EXIT
    trap 'exit 130' INT
    trap 'exit 143' TERM
    trap 'printf "\nSetup failed. Fix the error above and rerun ./setup.sh; existing configuration is preserved.\n" >&2' ERR

    if ! have_media || ! command -v curl >/dev/null 2>&1; then
        say "Installing FFmpeg and download tools. System packages may require your administrator password."
        if [[ "$SETUP_OS" == macOS ]]; then
            install_mac_dependencies
        else
            install_linux_dependencies
        fi
    fi
    have_media || fail "FFmpeg must include ffprobe, libx264 and AAC encoding. Install a full FFmpeg build from your distribution's supported repositories and rerun. No third-party repositories were enabled by this script."
    command -v curl >/dev/null 2>&1 || fail "curl is missing; install it and rerun."

    mkdir -p "$SETUP_ROOT/.tools"
    if [[ ! -x "$SETUP_ROOT/.tools/uv" ]]; then
        say "Installing the uv Python bootstrap tool locally in .tools (no shell profile changes)."
        download https://github.com/astral-sh/uv/releases/latest/download/uv-installer.sh "$SETUP_TEMP/uv-install.sh"
        UV_UNMANAGED_INSTALL="$SETUP_ROOT/.tools" sh "$SETUP_TEMP/uv-install.sh"
    fi
    export UV_PYTHON_INSTALL_DIR="$SETUP_ROOT/.tools/python"
    export UV_PYTHON_CACHE_DIR="$SETUP_ROOT/.tools/python-cache"
    export UV_PYTHON_BIN_DIR="$SETUP_ROOT/.tools/bin"
    export UV_CACHE_DIR="$SETUP_ROOT/.tools/cache"
    if [[ ! -e "$SETUP_ROOT/.venv" ]]; then
        say "Creating .venv with Python 3.13 (downloaded locally; system Python stays unchanged)."
        "$SETUP_ROOT/.tools/uv" venv --python 3.13 --managed-python --seed "$SETUP_ROOT/.venv"
    else
        say "Reusing the existing .venv."
    fi
    say "Installing explain-video and its Python dependencies into .venv."
    "$SETUP_ROOT/.tools/uv" pip install --python "$SETUP_ROOT/.venv/bin/python" --reinstall-package explain-video "$SETUP_ROOT"
    "$SETUP_ROOT/.tools/uv" pip check --python "$SETUP_ROOT/.venv/bin/python"
    "$SETUP_ROOT/.venv/bin/python" -m explain_video --help >/dev/null

    "$SETUP_ROOT/.venv/bin/python" - "$SETUP_ROOT" <<'PY'
import os
import sys
from pathlib import Path
from explain_video.config import load_config

root = Path(sys.argv[1])
config = root / ".env"
if config.is_symlink():
    raise SystemExit("Setup stopped: .env is a symlink; it was left unchanged. Configure a regular .env file before rerunning.")
try:
    descriptor = os.open(config, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
except FileExistsError:
    print("Existing .env preserved.")
else:
    with os.fdopen(descriptor, "w", encoding="utf-8") as target:
        target.write((root / ".env.example").read_text(encoding="utf-8"))
    print("Created .env with owner-only permissions.")
try:
    settings = load_config(config)
except (ValueError, OSError) as error:
    raise SystemExit(f"Setup stopped: check your .env configuration ({type(error).__name__}).")
if settings.api_key.strip():
    print("Software ready. API key is configured; no API request was made.")
else:
    print(f"Software ready. Before processing a video, edit {config} and set OPENAI_API_KEY to your own key.")
PY
    printf '\nRun a video (no activation needed):\n  %q %q\n' "$SETUP_ROOT/run" 'path/to/video.mp4'
    printf '\nOr from the project folder:\n  ./run "path/to/video.mp4"\n'
    say "Setup complete. Rerun ./setup.sh after pulling updates."
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
    main "$@"
fi
