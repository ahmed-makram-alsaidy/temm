import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.request
import venv
import zipfile
from pathlib import Path


class SdkDistributionTests(unittest.TestCase):
    def test_wheel_contains_only_public_sdk_and_cli(self):
        root = Path(__file__).parents[1]
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder)
            result = subprocess.run([sys.executable, "-m", "pip", "wheel", str(root / "sdk"), "--no-deps", "--wheel-dir", str(target)], capture_output=True, text=True, timeout=180)
            self.assertEqual(result.returncode, 0, result.stderr)
            wheel = next(target.glob("*.whl"))
            with zipfile.ZipFile(wheel) as archive:
                names = set(archive.namelist())
            self.assertIn("aifleet_sdk/__init__.py", names)
            self.assertIn("aifleet_sdk/client.py", names)
            self.assertIn("aifleet_cli.py", names)
            license_names = [name for name in names if name.endswith(".dist-info/licenses/LICENSE")]
            self.assertEqual(len(license_names), 1)
            with zipfile.ZipFile(wheel) as archive:
                self.assertEqual(archive.read(license_names[0]), (root / "LICENSE").read_bytes())
            self.assertFalse(any(name.startswith("core/") for name in names))

    def test_isolated_installed_console_negotiates_with_live_server(self):
        root = Path(__file__).parents[1]
        folder = tempfile.TemporaryDirectory()
        try:
            target = Path(folder.name)
            wheels = target / "wheels"
            wheels.mkdir()
            built = subprocess.run([sys.executable, "-m", "pip", "wheel", str(root / "sdk"), "--no-deps", "--wheel-dir", str(wheels)], capture_output=True, text=True, timeout=180)
            self.assertEqual(built.returncode, 0, built.stderr)
            environment = target / "venv"
            venv.EnvBuilder(with_pip=True, system_site_packages=True).create(environment)
            scripts = environment / ("Scripts" if os.name == "nt" else "bin")
            python = scripts / ("python.exe" if os.name == "nt" else "python")
            installed = subprocess.run([str(python), "-m", "pip", "install", "--no-deps", str(next(wheels.glob("*.whl")))], capture_output=True, text=True, timeout=180)
            self.assertEqual(installed.returncode, 0, installed.stderr)
            port = "8845"
            env = os.environ.copy()
            env.update({"AI_FLEET_PORT": port, "AI_FLEET_NO_BROWSER": "1", "AI_FLEET_DATA_DIR": str(target / "data")})
            server = subprocess.Popen([sys.executable, "run.py"], cwd=root, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            try:
                for _ in range(120):
                    try:
                        with urllib.request.urlopen(f"http://127.0.0.1:{port}/health/ready", timeout=1) as response:
                            if response.status == 200: break
                    except Exception:
                        __import__("time").sleep(.25)
                else: self.fail("Live SDK test server did not become ready.")
                command = scripts / ("aifleet.exe" if os.name == "nt" else "aifleet")
                result = subprocess.run([str(command), "--base-url", f"http://127.0.0.1:{port}", "--json", "inspect", "fleet"], capture_output=True, text=True, timeout=60)
                self.assertEqual(result.returncode, 0, result.stderr)
                payload = json.loads(result.stdout)
                self.assertIn("fleet_counts", payload)
            finally:
                server.terminate()
                try:
                    server.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    server.kill()
                    server.wait(timeout=10)
        finally:
            # Windows can retain a child process's SQLite lock briefly after exit.
            for attempt in range(10):
                try:
                    folder.cleanup()
                    break
                except PermissionError:
                    if attempt == 9:
                        raise
                    time.sleep(0.25)


if __name__ == "__main__":
    unittest.main()
