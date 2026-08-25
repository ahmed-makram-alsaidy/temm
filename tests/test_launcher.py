import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import run


ROOT = Path(__file__).resolve().parent.parent


class LauncherTests(unittest.TestCase):
    def test_port_validation(self):
        self.assertEqual(run.parse_port("8787"), 8787)
        for value in ["0", "65536", "not-a-port"]:
            with self.assertRaises(ValueError):
                run.parse_port(value)

    def test_browser_opens_only_after_readiness(self):
        response = MagicMock()
        response.__enter__.return_value.status = 200
        with patch("run.urllib.request.urlopen", return_value=response) as request, patch("run.webbrowser.open") as browser:
            self.assertTrue(run.open_when_ready("http://localhost:8787", timeout_seconds=0.1))
        request.assert_called()
        browser.assert_called_once_with("http://localhost:8787")

    def test_browser_does_not_open_when_server_never_ready(self):
        with patch("run.urllib.request.urlopen", side_effect=OSError), patch("run.webbrowser.open") as browser, patch("run.time.sleep"):
            with patch("run.time.monotonic", side_effect=[0, 1]):
                self.assertFalse(run.open_when_ready("http://localhost:8787", timeout_seconds=0.5))
        browser.assert_not_called()

    def test_windows_launchers_are_fail_fast(self):
        powershell = (ROOT / "start.ps1").read_text()
        batch = (ROOT / "start.bat").read_text()
        self.assertIn('$ErrorActionPreference = "Stop"', powershell)
        self.assertIn("$LASTEXITCODE", powershell)
        self.assertNotIn("Start-Process \"http", powershell)
        self.assertIn("if errorlevel 1", batch)
        self.assertNotIn("pause", batch.lower())


if __name__ == "__main__":
    unittest.main()
