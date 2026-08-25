import argparse
import hashlib
import json
import os
import shutil
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath


class InstallerError(RuntimeError):
    pass


@dataclass(frozen=True)
class InstallLayout:
    install_root: Path
    data_root: Path

    @property
    def versions(self): return self.install_root / "versions"
    @property
    def state(self): return self.install_root / "install-state.json"
    @property
    def launcher(self): return self.install_root / "TEMM.cmd"


class WindowsInstaller:
    def package(self, source: Path, output: Path, version: str, include: list[str]) -> dict:
        if not version or any(character not in "0123456789.-abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ" for character in version):
            raise InstallerError("Version is invalid.")
        source_root = source.resolve(strict=True)
        selected = []
        for relative in sorted(set(include)):
            path = (source_root / relative).resolve(strict=True)
            try:
                path.relative_to(source_root)
            except ValueError as exc:
                raise InstallerError("Package source escapes repository root.") from exc
            candidates = [path] if path.is_file() else sorted(item for item in path.rglob("*") if item.is_file()) if path.is_dir() else []
            for candidate in candidates:
                if candidate.is_symlink() or "__pycache__" in candidate.parts or candidate.suffix.lower() in {".pyc", ".pyo"}:
                    continue
                selected.append(candidate)
        files = []
        for path in sorted(set(selected)):
            relative = path.relative_to(source_root).as_posix()
            data = path.read_bytes()
            files.append({"path": relative, "size": len(data), "sha256": hashlib.sha256(data).hexdigest()})
        manifest = {"schema_version": "1.0", "product": "ai-fleet-os", "version": version, "entrypoint": "start.bat", "files": files}
        manifest_bytes = (json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n").encode()
        output.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
            for item in files:
                info = zipfile.ZipInfo(item["path"], (1980, 1, 1, 0, 0, 0))
                info.external_attr = 0o100644 << 16
                archive.writestr(info, (source / item["path"]).read_bytes())
            info = zipfile.ZipInfo("install-manifest.json", (1980, 1, 1, 0, 0, 0))
            info.external_attr = 0o100644 << 16
            archive.writestr(info, manifest_bytes)
        payload = output.read_bytes()
        return {"path": str(output), "sha256": hashlib.sha256(payload).hexdigest(), "size": len(payload), "manifest": manifest}

    def install(self, package: Path, expected_sha256: str, layout: InstallLayout) -> dict:
        package = package.resolve(strict=True)
        if hashlib.sha256(package.read_bytes()).hexdigest() != expected_sha256:
            raise InstallerError("Installer package checksum mismatch.")
        layout.install_root.mkdir(parents=True, exist_ok=True)
        layout.data_root.mkdir(parents=True, exist_ok=True)
        staged = Path(tempfile.mkdtemp(prefix=".install-", dir=layout.install_root))
        destination = None
        try:
            manifest = self._extract_verify(package, staged)
            destination = layout.versions / manifest["version"]
            layout.versions.mkdir(parents=True, exist_ok=True)
            if destination.exists():
                raise InstallerError("This version is already installed; use a distinct update version.")
            os.rename(staged, destination)
            previous = self._state(layout).get("current_version")
            state = {"schema_version": "1.0", "current_version": manifest["version"], "previous_version": previous if previous != manifest["version"] else None, "data_root": str(layout.data_root), "package_sha256": expected_sha256}
            self._write_state(layout, state)
            self._write_launcher(layout, manifest["version"], manifest["entrypoint"])
            return state
        except Exception:
            if staged.exists():
                shutil.rmtree(staged, ignore_errors=True)
            raise

    def rollback(self, layout: InstallLayout) -> dict:
        state = self._state(layout)
        previous = state.get("previous_version")
        if not previous or not (layout.versions / previous).is_dir():
            raise InstallerError("No retained version is available for rollback.")
        current = state["current_version"]
        state["current_version"] = previous
        state["previous_version"] = current
        self._write_state(layout, state)
        manifest = json.loads((layout.versions / previous / "install-manifest.json").read_text(encoding="utf-8"))
        self._write_launcher(layout, previous, manifest["entrypoint"])
        return state

    def uninstall(self, layout: InstallLayout, purge_data: bool = False) -> dict:
        if layout.versions.exists():
            shutil.rmtree(layout.versions)
        layout.state.unlink(missing_ok=True)
        layout.launcher.unlink(missing_ok=True)
        preserved = layout.data_root.exists()
        if purge_data and layout.data_root.exists():
            shutil.rmtree(layout.data_root)
            preserved = False
        return {"uninstalled": True, "data_preserved": preserved, "data_root": str(layout.data_root)}

    def _extract_verify(self, package: Path, staged: Path) -> dict:
        with zipfile.ZipFile(package) as archive:
            infos = archive.infolist()
            if not 2 <= len(infos) <= 10000:
                raise InstallerError("Installer package file count is invalid.")
            for info in infos:
                path = PurePosixPath(info.filename)
                mode = info.external_attr >> 16
                if "\\" in info.filename or path.is_absolute() or ".." in path.parts or any(":" in part for part in path.parts) or (mode & 0o170000) not in {0, 0o100000}:
                    raise InstallerError("Installer package contains an unsafe path.")
                if info.file_size > 100 * 1024 * 1024:
                    raise InstallerError("Installer package file exceeds size limit.")
            archive.extractall(staged)
        manifest_path = staged / "install-manifest.json"
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise InstallerError("Installer manifest is missing or invalid.") from exc
        if manifest.get("schema_version") != "1.0" or manifest.get("product") != "ai-fleet-os" or not manifest.get("version") or manifest.get("entrypoint") != "start.bat":
            raise InstallerError("Installer manifest contract is invalid.")
        declared = {item["path"]: item for item in manifest.get("files", []) if isinstance(item, dict)}
        actual = {path.relative_to(staged).as_posix(): path for path in staged.rglob("*") if path.is_file() and path.name != "install-manifest.json"}
        if set(declared) != set(actual):
            raise InstallerError("Installer package files do not match manifest.")
        for relative, path in actual.items():
            data = path.read_bytes()
            if declared[relative].get("size") != len(data) or declared[relative].get("sha256") != hashlib.sha256(data).hexdigest():
                raise InstallerError("Installer package file integrity failed.")
        return manifest

    def _state(self, layout: InstallLayout) -> dict:
        if not layout.state.is_file():
            return {}
        try:
            return json.loads(layout.state.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise InstallerError("Installer state is corrupt.") from exc

    def _write_state(self, layout: InstallLayout, state: dict):
        temporary = layout.state.with_suffix(".tmp")
        temporary.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
        os.replace(temporary, layout.state)

    def _write_launcher(self, layout: InstallLayout, version: str, entrypoint: str):
        content = f'@echo off\r\nset "AI_FLEET_DATA_DIR={layout.data_root}"\r\npushd "%~dp0versions\\{version}"\r\ncall "{entrypoint}" %*\r\nset "AI_FLEET_EXIT=%ERRORLEVEL%"\r\npopd\r\nexit /b %AI_FLEET_EXIT%\r\n'
        temporary = layout.launcher.with_suffix(".tmp")
        temporary.write_text(content, encoding="utf-8", newline="")
        os.replace(temporary, layout.launcher)


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    package_parser = subparsers.add_parser("package")
    package_parser.add_argument("--source", type=Path, required=True)
    package_parser.add_argument("--output", type=Path, required=True)
    package_parser.add_argument("--version", required=True)
    package_parser.add_argument("--include", nargs="+", required=True)
    for command in ("install", "rollback", "uninstall"):
        item = subparsers.add_parser(command)
        item.add_argument("--install-root", type=Path, required=True)
        item.add_argument("--data-root", type=Path, required=True)
        if command == "install":
            item.add_argument("--package", type=Path, required=True)
            item.add_argument("--sha256", required=True)
        if command == "uninstall":
            item.add_argument("--purge-data", action="store_true")
    args = parser.parse_args()
    service = WindowsInstaller()
    if args.command == "package": result = service.package(args.source, args.output, args.version, args.include)
    else:
        layout = InstallLayout(args.install_root, args.data_root)
        if args.command == "install": result = service.install(args.package, args.sha256, layout)
        elif args.command == "rollback": result = service.rollback(layout)
        else: result = service.uninstall(layout, args.purge_data)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
