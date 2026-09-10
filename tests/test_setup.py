"""Offline installer/launcher checks; never execute a real package manager."""
import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class SetupTests(unittest.TestCase):
    def shell(self, text, *args):
        return subprocess.run(["bash", "-c", 'source "$1"; ' + text, "test", str(ROOT / "setup.sh"), *args],
                              text=True, capture_output=True)

    def test_system_package_dispatch_and_failure(self):
        for manager in ("apt-get", "dnf", "pacman", "zypper", "unavailable"):
            with self.subTest(manager=manager):
                result = self.shell('''
                    manager=$2
                    command() { [[ "$1" == -v && ( "$2" == "$manager" || "$2" == sudo ) ]]; }
                    sudo() { printf '%s\\n' "$*"; }
                    install_linux_dependencies
                ''', manager)
                if manager == "unavailable":
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn("No supported Linux package manager", result.stderr)
                else:
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertIn(manager, result.stdout)
                    self.assertIn("ffmpeg curl ca-certificates", result.stdout)
                    self.assertNotIn("upgrade", result.stdout)

    def test_encoder_preflight_rejects_incomplete_ffmpeg(self):
        for listing, expected in [(" V libx264 encoder\n A aac encoder", 0), (" A aac encoder", 1)]:
            result = self.shell('ffprobe() { :; }; '
                                'listing=$2; ffmpeg() { printf "%s\\n" "$listing"; }; have_media', listing)
            self.assertEqual(result.returncode, expected, result.stderr)

    def test_help_needs_no_dependencies_or_network(self):
        result = subprocess.run(["bash", str(ROOT / "setup.sh"), "--help"], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0)
        self.assertIn("Usage:", result.stdout)

    def test_launcher_preserves_arguments_cwd_and_checkout_config(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "a checkout with spaces"
            (root / ".venv/bin").mkdir(parents=True)
            shutil.copy2(ROOT / "run", root / "run")
            interpreter = root / ".venv/bin/python"
            interpreter.write_text("#!/bin/bash\nexec " + shlex.quote(sys.executable) +
                                   " -c 'import json,os,sys; print(json.dumps([os.getcwd(),sys.argv[1:]]))' \"$@\"\n")
            interpreter.chmod(0o755)
            # macOS temp paths commonly pass through /var -> /private/var.
            # Exercise the same behavior on Linux with an explicit symlink.
            alias = Path(directory) / "checkout alias"
            alias.symlink_to(root, target_is_directory=True)
            args = ["a video's $name.mov", "--config", "my config.env"]
            result = subprocess.run(["bash", str(alias / "run"), *args], cwd=directory, text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            cwd, forwarded = json.loads(result.stdout)
            self.assertEqual(Path(cwd).resolve(), Path(directory).resolve())
            self.assertEqual(forwarded, ["-m", "explain_video", "--config", str(root.resolve() / ".env"), *args])

    @unittest.skipIf(os.geteuid() == 0, "installer must run as a normal user")
    def test_invalid_existing_environment_is_preserved_before_downloads(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".venv").mkdir()
            marker = root / ".venv/keep.txt"
            marker.write_text("keep me")
            result = self.shell('SETUP_ROOT=$2; main', str(root))
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("not a working virtual environment", result.stderr)
            self.assertEqual(marker.read_text(), "keep me")
            self.assertFalse((root / ".tools").exists())

    @unittest.skipIf(os.geteuid() == 0, "installer must run as a normal user")
    def test_symlinked_config_is_preserved_before_downloads(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "private.env"
            target.write_text("OPENAI_API_KEY=test-placeholder")
            (root / ".env").symlink_to(target)
            result = self.shell('SETUP_ROOT=$2; main', str(root))
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("must not be a symlink", result.stderr)
            self.assertEqual(target.read_text(), "OPENAI_API_KEY=test-placeholder")
            self.assertNotIn("test-placeholder", result.stdout + result.stderr)
            self.assertFalse((root / ".tools").exists())

    def test_launcher_before_setup_has_actionable_message(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "run"
            shutil.copy2(ROOT / "run", path)
            result = subprocess.run(["bash", str(path), "--help"], text=True, capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("Run setup first:", result.stderr)
