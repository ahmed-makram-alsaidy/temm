import hashlib
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from tools.installer.windows_installer import InstallLayout, InstallerError, WindowsInstaller


class WindowsInstallerTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.root = Path(self.folder.name)
        self.source = self.root / "source"
        self.source.mkdir()
        (self.source / "start.bat").write_text("@echo off\r\necho start\r\n", encoding="utf-8", newline="")
        (self.source / "run.py").write_text("print('run')\n", encoding="utf-8")
        self.layout = InstallLayout(self.root / "installed", self.root / "data")
        self.service = WindowsInstaller()

    def tearDown(self):
        self.folder.cleanup()

    def package(self, version, name):
        output = self.root / name
        return self.service.package(self.source, output, version, ["start.bat", "run.py"])

    def test_package_is_deterministic_and_install_update_rollback_preserve_data(self):
        first = self.package("1.0.0", "first.zip")
        second = self.package("1.0.0", "second.zip")
        self.assertEqual(first["sha256"], second["sha256"])
        state = self.service.install(Path(first["path"]), first["sha256"], self.layout)
        self.assertEqual(state["current_version"], "1.0.0")
        (self.layout.data_root / "user.db").write_text("keep")
        with self.assertRaisesRegex(InstallerError, "already installed"):
            self.service.install(Path(first["path"]), first["sha256"], self.layout)
        self.assertTrue((self.layout.versions / "1.0.0" / "run.py").is_file())
        (self.source / "run.py").write_text("print('updated')\n", encoding="utf-8")
        update = self.package("1.1.0", "update.zip")
        state = self.service.install(Path(update["path"]), update["sha256"], self.layout)
        self.assertEqual(state["previous_version"], "1.0.0")
        launcher = self.layout.launcher.read_text()
        self.assertIn("versions\\1.1.0", launcher)
        self.assertIn('call "start.bat"', launcher)
        rolled_back = self.service.rollback(self.layout)
        self.assertEqual(rolled_back["current_version"], "1.0.0")
        self.assertEqual((self.layout.data_root / "user.db").read_text(), "keep")
        result = self.service.uninstall(self.layout)
        self.assertTrue(result["data_preserved"])
        self.assertTrue((self.layout.data_root / "user.db").is_file())
        self.assertFalse(self.layout.launcher.exists())

    def test_checksum_manifest_and_archive_paths_are_enforced(self):
        package = self.package("1.0.0", "package.zip")
        with self.assertRaisesRegex(InstallerError, "checksum"):
            self.service.install(Path(package["path"]), "0" * 64, self.layout)
        malicious = self.root / "malicious.zip"
        with zipfile.ZipFile(malicious, "w") as archive:
            archive.writestr("..\\escape.txt", "bad")
            archive.writestr("install-manifest.json", json.dumps({"schema_version": "1.0", "product": "ai-fleet-os", "version": "1", "entrypoint": "start.bat", "files": []}))
        digest = hashlib.sha256(malicious.read_bytes()).hexdigest()
        with self.assertRaisesRegex(InstallerError, "unsafe path"):
            self.service.install(malicious, digest, self.layout)
        self.assertFalse((self.root / "escape.txt").exists())

    def test_package_recurses_directories_and_excludes_python_cache(self):
        package_dir = self.source / "core"
        package_dir.mkdir()
        (package_dir / "module.py").write_text("value = 1\n")
        cache = package_dir / "__pycache__"
        cache.mkdir()
        (cache / "module.pyc").write_bytes(b"cache")
        result = self.service.package(self.source, self.root / "recursive.zip", "1.0.0", ["start.bat", "core"])
        paths = [item["path"] for item in result["manifest"]["files"]]
        self.assertEqual(paths, ["core/module.py", "start.bat"])

    def test_powershell_wrappers_are_fail_fast_and_preserve_data_by_default(self):
        root = Path(__file__).parents[1] / "tools" / "installer"
        install = (root / "install.ps1").read_text(encoding="utf-8")
        uninstall = (root / "uninstall.ps1").read_text(encoding="utf-8")
        build = (root / "build-windows-package.ps1").read_text(encoding="utf-8")
        for text in (install, uninstall, build):
            self.assertIn('$ErrorActionPreference = "Stop"', text)
        self.assertIn("[switch]$PurgeData", uninstall)
        self.assertIn('if ($PurgeData)', uninstall)
        self.assertNotIn('--purge-data",', install)
        self.assertIn("requirements-lock-win.txt", build)

    def test_repository_runtime_package_includes_license_artifacts(self):
        repository = Path(__file__).parents[1]
        with tempfile.TemporaryDirectory() as folder:
            result = self.service.package(repository, Path(folder) / "runtime.zip", "0.1.0", ["LICENSE", "dependency-licenses.json", "apps/web/dist"])
            paths = {item["path"] for item in result["manifest"]["files"]}
        self.assertIn("LICENSE", paths)
        self.assertIn("dependency-licenses.json", paths)
        self.assertIn("apps/web/dist/THIRD_PARTY_LICENSES.txt", paths)

    def test_uninstall_can_explicitly_purge_data(self):
        package = self.package("1.0.0", "package.zip")
        self.service.install(Path(package["path"]), package["sha256"], self.layout)
        (self.layout.data_root / "user.db").write_text("delete")
        result = self.service.uninstall(self.layout, purge_data=True)
        self.assertFalse(result["data_preserved"])
        self.assertFalse(self.layout.data_root.exists())


if __name__ == "__main__":
    unittest.main()
