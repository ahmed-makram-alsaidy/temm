import argparse
import base64
import hashlib
import json
import platform
import re
from pathlib import Path


_LOCK_LINE = re.compile(r"^([A-Za-z0-9_.-]+)==([^\s]+)\s+--hash=sha256:([a-f0-9]{64})$")


class BuildProvenance:
    def manifest(self, root: Path, paths: list[str], environment: dict) -> dict:
        files = []
        for relative in sorted(set(paths)):
            path = root / relative
            if path.is_file():
                data = path.read_bytes()
                files.append({
                    "path": relative.replace("\\", "/"),
                    "size": len(data),
                    "sha256": hashlib.sha256(data).hexdigest(),
                })
        payload = {
            "schema_version": "1.0",
            "files": files,
            "environment": environment,
            "python_dependencies_locked": all((root / name).is_file() for name in ("requirements-lock-win.txt", "requirements-lock-linux.txt")),
            "frontend_dependencies_locked": (root / "apps/web/package-lock.json").is_file(),
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        payload["manifest_sha256"] = hashlib.sha256(encoded).hexdigest()
        return payload

    def python_components(self, lock_path: Path, licenses: dict[str, str] | None = None) -> list[dict]:
        components = []
        licenses = licenses or {}
        for line_number, raw in enumerate(lock_path.read_text(encoding="utf-8").splitlines(), 1):
            line = raw.strip()
            if not line:
                continue
            match = _LOCK_LINE.fullmatch(line)
            if not match:
                raise ValueError(f"Invalid lock entry at {lock_path.name}:{line_number}")
            name, version, digest = match.groups()
            normalized = name.lower().replace("_", "-")
            component = {
                "type": "library",
                "name": normalized,
                "version": version,
                "hashes": [{"alg": "SHA-256", "content": digest}],
                "properties": [{"name": "aifleet:lock", "value": lock_path.name}],
            }
            if normalized in licenses:
                component["licenses"] = [{"expression": licenses[normalized]}]
            components.append(component)
        return sorted(components, key=lambda item: (item["name"], item["version"]))

    def frontend_components(self, lock_path: Path) -> list[dict]:
        package_lock = json.loads(lock_path.read_text(encoding="utf-8"))
        components = []
        for package_path, metadata in package_lock.get("packages", {}).items():
            if not package_path or "version" not in metadata:
                continue
            name = metadata.get("name") or package_path.rsplit("node_modules/", 1)[-1]
            component = {"type": "library", "name": name, "version": metadata["version"]}
            if metadata.get("license"):
                component["licenses"] = [{"expression": metadata["license"]}]
            integrity = metadata.get("integrity", "")
            if integrity.startswith("sha512-"):
                component["hashes"] = [{"alg": "SHA-512", "content": base64.b64decode(integrity[7:]).hex()}]
            components.append(component)
        return sorted(components, key=lambda item: (item["name"], item["version"]))

    def sbom(self, root: Path) -> dict:
        components = []
        licenses = json.loads((root / "dependency-licenses.json").read_text(encoding="utf-8"))["python"]
        for lock_name in ("requirements-lock-win.txt", "requirements-lock-linux.txt"):
            components.extend(self.python_components(root / lock_name, licenses))
        components.extend(self.frontend_components(root / "apps/web/package-lock.json"))
        unique = {}
        for component in components:
            key = (component["name"], component["version"], json.dumps(component.get("properties", []), sort_keys=True))
            unique[key] = component
        return {
            "bomFormat": "CycloneDX",
            "specVersion": "1.6",
            "version": 1,
            "metadata": {"component": {"type": "application", "name": "ai-fleet-os", "licenses": [{"expression": "Apache-2.0"}]}},
            "components": [unique[key] for key in sorted(unique)],
        }

    def generate(self, root: Path, output: Path, environment: dict | None = None) -> dict:
        output.mkdir(parents=True, exist_ok=True)
        tracked = ["LICENSE", "dependency-licenses.json", "requirements.txt", "requirements-lock-win.txt", "requirements-lock-linux.txt", "pyproject.toml", "sdk/LICENSE", "sdk/pyproject.toml", "sdk/aifleet_cli.py", "sdk/aifleet_sdk/__init__.py", "sdk/aifleet_sdk/client.py", "apps/web/package.json", "apps/web/package-lock.json", "apps/web/public/THIRD_PARTY_LICENSES.txt"]
        manifest = self.manifest(root, tracked, environment or {"python": platform.python_version(), "platform": platform.system().lower()})
        sbom = self.sbom(root)
        artifacts = {
            "build-provenance.json": json.dumps(manifest, indent=2, sort_keys=True) + "\n",
            "sbom.cdx.json": json.dumps(sbom, indent=2, sort_keys=True) + "\n",
        }
        checksums = []
        for name in sorted(artifacts):
            data = artifacts[name].encode()
            (output / name).write_bytes(data)
            checksums.append(f"{hashlib.sha256(data).hexdigest()}  {name}")
        checksum_text = "\n".join(checksums) + "\n"
        (output / "SHA256SUMS").write_text(checksum_text, encoding="utf-8", newline="\n")
        return {"files": sorted([*artifacts, "SHA256SUMS"]), "checksums": checksums}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    build_provenance.generate(args.root.resolve(), args.output.resolve())
    return 0


build_provenance = BuildProvenance()


if __name__ == "__main__":
    raise SystemExit(main())
