import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from explain_video.guide import open_guide
from explain_video.__main__ import main


class GuideTests(unittest.TestCase):
    def test_preserves_existing_files_and_symlinks(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            original = root / 'guide.html'
            original.write_text('private plan')
            (root / 'guide-2.html').symlink_to(original)
            with patch('webbrowser.open', return_value=False), patch('sys.stdout', io.StringIO()) as out:
                result = open_guide(original)
            self.assertEqual(result.name, 'guide-3.html')
            self.assertEqual(original.read_text(), 'private plan')
            self.assertIn(result.as_uri(), out.getvalue())
            self.assertIn('What do you want to do?', result.read_text())

    def test_guide_needs_no_video_config_or_providers(self):
        with patch('sys.argv', ['explain-video', '--guide']), \
             patch('explain_video.guide.open_guide') as guide, \
             patch('explain_video.__main__.load_config') as config, \
             patch('explain_video.__main__.make_providers') as providers:
            self.assertEqual(main(), 0)
            guide.assert_called_once()
            config.assert_not_called()
            providers.assert_not_called()

    def test_guide_rejects_ignored_processing_options(self):
        for options in [['video.mp4'], ['--sync'], ['--facts', 'facts.txt']]:
            with patch('sys.argv', ['explain-video', '--guide', *options]), patch('sys.stderr'), \
                 patch('explain_video.guide.open_guide') as guide:
                with self.assertRaises(SystemExit) as error:
                    main()
                self.assertEqual(error.exception.code, 2)
                guide.assert_not_called()
