import unittest
from pathlib import Path
from unittest.mock import patch
from wechat_report.bootstrap import capture
class NoLoginTests(unittest.TestCase):
 def test_default_never_touches_wechat_or_files(self):
  with patch('wechat_report.bootstrap.subprocess.run') as run, patch('wechat_report.bootstrap.subprocess.Popen') as popen, patch('wechat_report.bootstrap.tempfile.TemporaryDirectory') as tmp:
   with self.assertRaisesRegex(RuntimeError,'默认不启动'):capture(Path('/not/a/real/account'))
   run.assert_not_called();popen.assert_not_called();tmp.assert_not_called()
