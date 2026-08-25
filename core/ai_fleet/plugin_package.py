import hashlib
from pathlib import Path


class PluginPackageError(ValueError):
    pass


def hash_plugin_folder(folder: Path) -> str:
    root = folder.resolve(strict=True)
    files = sorted(
        path for path in root.rglob("*")
        if path.is_file() and "__pycache__" not in path.parts and path.suffix.lower() not in {".pyc", ".pyo"}
    )
    if len(files) > 1000:
        raise PluginPackageError("Plugin package contains too many files.")
    digest = hashlib.sha256()
    for path in files:
        if path.is_symlink():
            raise PluginPackageError("Plugin package symlinks are not allowed.")
        if path.stat().st_size > 10 * 1024 * 1024:
            raise PluginPackageError("Plugin package file exceeds 10 MiB.")
        relative = path.relative_to(root).as_posix().encode()
        digest.update(len(relative).to_bytes(4, "big"))
        digest.update(relative)
        with path.open("rb") as handle:
            while chunk := handle.read(65536):
                digest.update(chunk)
    return digest.hexdigest()


def contained_entrypoint(folder: Path, entrypoint: str) -> Path:
    root = folder.resolve(strict=True)
    target = (root / entrypoint).resolve(strict=True)
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise PluginPackageError("Plugin entrypoint escapes package folder.") from exc
    if not target.is_file() or target.suffix.lower() != ".py":
        raise PluginPackageError("Plugin entrypoint is not a Python file.")
    return target
