import os
from pathlib import Path
from typing import Union


class PathPolicyError(ValueError):
    pass


class PathPolicy:
    def existing_directory(self, value: Union[str, Path]) -> Path:
        path = self._resolve(value)
        if not path.is_dir():
            raise PathPolicyError("Path must be an existing directory.")
        return path

    def existing_file(self, value: Union[str, Path]) -> Path:
        path = self._resolve(value)
        if not path.is_file():
            raise PathPolicyError("Path must be an existing file.")
        return path

    def contained_file(self, root: Union[str, Path], value: Union[str, Path]) -> Path:
        root_path = self.existing_directory(root)
        file_path = self.existing_file(value)
        try:
            common = Path(os.path.commonpath([str(root_path), str(file_path)]))
        except ValueError as exc:
            raise PathPolicyError("Path is outside the approved workspace.") from exc
        if os.path.normcase(str(common)) != os.path.normcase(str(root_path)):
            raise PathPolicyError("Path is outside the approved workspace.")
        return file_path

    def _resolve(self, value: Union[str, Path]) -> Path:
        text = str(value)
        if not text or "\x00" in text or "\r" in text or "\n" in text:
            raise PathPolicyError("Path is invalid.")
        path = Path(text).expanduser()
        if not path.is_absolute():
            raise PathPolicyError("Path must be absolute.")
        try:
            return path.resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            raise PathPolicyError("Path does not exist or cannot be resolved.") from exc


path_policy = PathPolicy()
