"""Offline viewer interactions tested without a browser or network."""
from pathlib import Path
import shutil
import subprocess
import unittest


class ViewerTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which('node'), 'Node.js is optional and not installed')
    def test_controls_and_recorded_event_navigation(self):
        subprocess.run([shutil.which('node'),str(Path(__file__).with_name('viewer-smoke.cjs'))],
                       check=True,capture_output=True,text=True,timeout=20)


if __name__=='__main__':unittest.main()
