import argparse
import json
import re
from pathlib import Path


class LicensePolicyError(RuntimeError):
    pass


class LicensePolicy:
    SPDX = "Apache-2.0"
    RUNTIME_LICENSE_FILE = "THIRD_PARTY_LICENSES.txt"

    def verify(self, root: Path) -> dict:
        errors = []
        license_path = root / "LICENSE"
        sdk_license = root / "sdk" / "LICENSE"
        if not license_path.is_file():
            errors.append("LICENSE is missing")
        else:
            text = license_path.read_text(encoding="utf-8")
            for marker in ("Apache License", "Version 2.0, January 2004", "END OF TERMS AND CONDITIONS"):
                if marker not in text:
                    errors.append(f"LICENSE is not canonical Apache-2.0 text: missing {marker}")
        if not sdk_license.is_file() or license_path.is_file() and sdk_license.read_bytes() != license_path.read_bytes():
            errors.append("sdk/LICENSE must be byte-identical to LICENSE")
        self._verify_metadata(root, errors)
        python_inventory = self._python_inventory(root, errors)
        runtime = self.frontend_runtime_components(root / "apps" / "web" / "package-lock.json", errors)
        bundle = root / "apps" / "web" / "public" / self.RUNTIME_LICENSE_FILE
        if not bundle.is_file():
            errors.append(f"apps/web/public/{self.RUNTIME_LICENSE_FILE} is missing")
        else:
            bundle_text = bundle.read_text(encoding="utf-8")
            for component in runtime:
                marker = f"{component['name']} {component['version']} — {component['license']}"
                if marker not in bundle_text:
                    errors.append(f"third-party bundle is missing {marker}")
        if errors:
            raise LicensePolicyError("; ".join(errors))
        return {"license": self.SPDX, "python_dependencies": len(python_inventory), "frontend_runtime_dependencies": len(runtime), "notice_required": False, "third_party_bundle": bundle.relative_to(root).as_posix()}

    def _verify_metadata(self, root: Path, errors: list[str]):
        for relative in ("pyproject.toml", "sdk/pyproject.toml"):
            text = (root / relative).read_text(encoding="utf-8")
            if f'license = "{self.SPDX}"' not in text:
                errors.append(f"{relative} does not declare {self.SPDX}")
        package = json.loads((root / "apps" / "web" / "package.json").read_text(encoding="utf-8"))
        package_lock = json.loads((root / "apps" / "web" / "package-lock.json").read_text(encoding="utf-8"))
        if package.get("license") != self.SPDX:
            errors.append("apps/web/package.json has inconsistent license metadata")
        if package_lock.get("packages", {}).get("", {}).get("license") != self.SPDX:
            errors.append("apps/web/package-lock.json has inconsistent root license metadata")
        readme = (root / "README.md").read_text(encoding="utf-8")
        policy = (root / "docs" / "LICENSING.md").read_text(encoding="utf-8")
        if "Apache License 2.0" not in readme or self.SPDX not in readme:
            errors.append("README license claim is missing")
        if self.SPDX not in policy or "Nothing in this repository relicenses third-party material" not in policy:
            errors.append("licensing policy does not preserve third-party terms")

    def _python_inventory(self, root: Path, errors: list[str]) -> dict:
        inventory_path = root / "dependency-licenses.json"
        if not inventory_path.is_file():
            errors.append("dependency-licenses.json is missing")
            return {}
        payload = json.loads(inventory_path.read_text(encoding="utf-8"))
        inventory = payload.get("python", {})
        locked = set()
        pattern = re.compile(r"^([A-Za-z0-9_.-]+)==")
        for lock_name in ("requirements-lock-win.txt", "requirements-lock-linux.txt"):
            for line in (root / lock_name).read_text(encoding="utf-8").splitlines():
                match = pattern.match(line.strip())
                if match:
                    locked.add(match.group(1).lower().replace("_", "-"))
        missing = sorted(locked - set(inventory))
        extra = sorted(set(inventory) - locked)
        invalid = sorted(name for name, expression in inventory.items() if not isinstance(expression, str) or not expression.strip() or expression == "UNKNOWN")
        if missing:
            errors.append(f"Python dependency license inventory is missing: {', '.join(missing)}")
        if extra:
            errors.append(f"Python dependency license inventory has unlocked entries: {', '.join(extra)}")
        if invalid:
            errors.append(f"Python dependency license inventory has invalid expressions: {', '.join(invalid)}")
        return inventory

    def frontend_runtime_components(self, lock_path: Path, errors: list[str] | None = None) -> list[dict]:
        errors = errors if errors is not None else []
        payload = json.loads(lock_path.read_text(encoding="utf-8"))
        packages = payload.get("packages", {})
        queue = sorted(packages.get("", {}).get("dependencies", {}))
        visited = set()
        components = []
        while queue:
            name = queue.pop(0)
            if name in visited:
                continue
            visited.add(name)
            metadata = packages.get(f"node_modules/{name}")
            if not metadata:
                errors.append(f"frontend runtime dependency is not locked: {name}")
                continue
            license_id = metadata.get("license")
            if not license_id:
                errors.append(f"frontend runtime dependency has no license metadata: {name}")
                license_id = "UNKNOWN"
            components.append({"name": name, "version": metadata.get("version"), "license": license_id})
            queue.extend(sorted(set(metadata.get("dependencies", {})) - visited))
        return sorted(components, key=lambda item: item["name"])

    def generate_frontend_bundle(self, root: Path) -> Path:
        web = root / "apps" / "web"
        errors = []
        components = self.frontend_runtime_components(web / "package-lock.json", errors)
        sections = ["TEMM third-party runtime licenses", "", "These components are not licensed under the TEMM Apache-2.0 license. They remain under the terms reproduced below.", ""]
        for component in components:
            package_root = web / "node_modules" / Path(*component["name"].split("/"))
            license_path = next((package_root / name for name in ("LICENSE", "LICENSE.md", "LICENSE.txt", "COPYING") if (package_root / name).is_file()), None)
            if not license_path:
                errors.append(f"installed dependency license text is missing: {component['name']}")
                continue
            text = license_path.read_text(encoding="utf-8").strip()
            sections.extend(["=" * 80, f"{component['name']} {component['version']} — {component['license']}", "=" * 80, text, ""])
        if errors:
            raise LicensePolicyError("; ".join(errors))
        destination = web / "public" / self.RUNTIME_LICENSE_FILE
        destination.write_text("\n".join(sections).rstrip() + "\n", encoding="utf-8", newline="\n")
        return destination


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--generate-frontend", action="store_true")
    args = parser.parse_args()
    root = args.root.resolve()
    service = LicensePolicy()
    if args.generate_frontend:
        service.generate_frontend_bundle(root)
    print(json.dumps(service.verify(root), indent=2, sort_keys=True))
    return 0


license_policy = LicensePolicy()


if __name__ == "__main__":
    raise SystemExit(main())
