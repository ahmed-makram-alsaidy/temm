import hashlib
import json
import ast
import fnmatch
import glob
import re
from pathlib import Path
from typing import Any


class WorkspaceAcceptanceService:
    IGNORED_PARTS = {"node_modules", "dist", ".git"}
    # Output of running the project rather than work anyone authored. This is the
    # floor TEMM owns, for a workspace that declares nothing of its own; the
    # workspace's own declaration is read on top of it. Deliberately narrow: it
    # names caches, virtual environments, framework build directories and the local
    # databases and logs a running application writes, and nothing whose absence
    # from measurement could hide source.
    ARTIFACT_PARTS = {
        "__pycache__", ".mypy_cache", ".ruff_cache", ".pytest_cache", ".tox",
        ".venv", "venv", ".next", ".nuxt", ".svelte-kit", ".turbo", ".vite",
        ".parcel-cache", ".gradle", "coverage", "htmlcov", ".idea", ".vscode",
    }
    ARTIFACT_SUFFIXES = {
        ".pyc", ".pyo", ".pyd", ".log", ".db", ".db-journal", ".db-wal",
        ".db-shm", ".sqlite", ".sqlite3",
    }
    DECLARATION_FILENAME = ".gitignore"
    # Unfinished-work markers, matched as whole words so ordinary vocabulary
    # ("latest", "manifest", "resampled") cannot condemn a real deliverable.
    STRONG_PLACEHOLDER_PATTERN = re.compile(r"\b(todo|fixme|lorem ipsum|your code here|write your code|replace this)\b", re.IGNORECASE)
    # "placeholder" is also the name of a standard HTML attribute and React prop,
    # so it marks unfinished work only as prose, never as an identifier: a form
    # with `placeholder="Customer name"` is finished work, not a stub. Excluded
    # are assignment, key, optional-field, argument, and member-access positions.
    PLACEHOLDER_WORD_PATTERN = re.compile(r"(?<![\w.\"'`])placeholders?\b(?!\s*[=:?,)\]}]|\s*\()", re.IGNORECASE)
    # Stub vocabulary that only means something in a tiny file: a substantial
    # module that mentions "example" or names a `foo` fixture is still real work.
    WEAK_PLACEHOLDER_PATTERN = re.compile(r"\b(foo|bar|baz|qux|xxx|yyy|zzz|hello world|example|sample)\b", re.IGNORECASE)
    WEAK_PLACEHOLDER_MAX_CHARS = 200

    def snapshot(self, root: Path, protected: set[str] | None = None) -> dict[str, str]:
        """Hash the workspace's authored files, leaving generated output out.

        This snapshot is the sole evidence behind three separate conclusions, and one
        runtime artifact corrupts all three: the `changed_files_subset` scope clause,
        the `no_effect` verdict, and the `file_write`/`coding`/`file_read` capability
        floor renewed from a diff. An executor asked to verify its own work starts the
        application, the application writes its own database, and that single hash
        change used to fail the scope clause of a run that delivered perfectly, prove
        an effect for a run that delivered nothing, and re-certify a coding floor from
        a file no model authored.

        Production evidence, attempt-cde42a0d2608 on task-3bd4d689eb9d, 2026-08-22
        01:09:02: 67 tool uses, 64 of 400 steps and 3.56M tokens over 25 minutes
        produced exactly one diff entry - `backend/data/app.db`, which the workspace's
        own `.gitignore` declares generated on line 18. The scope clause failed with
        `outside_scope: ["backend/data/app.db"]`, and the capability renewal recorded
        `production_workspace_effect` for a run that wrote no code at all.

        `protected` names the paths acceptance measures, and nothing in it is ever
        excluded. That is what keeps a careless or self-serving ignore rule from making
        a contract unmeasurable - and because the caller passes `changed_files_subset`'s
        own allowed-path list in, a write inside the permitted scope can never be
        hidden from the clause that polices it.
        """
        keep = protected or set()
        rules = self._declared_ignores(root)
        result = {}
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            relative = path.relative_to(root)
            if self.IGNORED_PARTS.intersection(relative.parts):
                continue
            key = relative.as_posix()
            if key not in keep and self._is_generated(relative, rules):
                continue
            result[key] = hashlib.sha256(path.read_bytes()).hexdigest()
        return result

    def measured_paths(self, criteria: list[dict]) -> set[str]:
        """Every path a contract names, so the snapshot can refuse to hide any of them.

        The scope clause's own path list is included, unlike the collector that decides
        which paths a repair must preserve: there the question is what the task must
        deliver, here it is what must stay visible to measurement, and a path an
        attempt is permitted to write is exactly a path whose changes have to be seen.
        """
        paths: set[str] = set()

        def walk(evaluator: dict) -> None:
            if not isinstance(evaluator, dict):
                return
            for check in evaluator.get("checks") or []:
                walk(check)
            if evaluator.get("path"):
                paths.add(str(evaluator["path"]))
            for value in evaluator.get("paths") or []:
                paths.add(str(value))

        for criterion in criteria or []:
            walk(criterion.get("evaluator") or {})
        return paths

    def artifact_census(self, root: Path, protected: set[str] | None = None) -> dict:
        """What the snapshot left out, so an empty diff is never unexplained.

        Counts and a bounded sample of paths - no file contents, and nothing beyond a
        filename the workspace itself declares generated.
        """
        keep = protected or set()
        rules = self._declared_ignores(root)
        excluded: list[str] = []
        measured = 0
        for path in sorted(root.rglob("*")):
            if not path.is_file():
                continue
            relative = path.relative_to(root)
            if self.IGNORED_PARTS.intersection(relative.parts):
                continue
            if relative.as_posix() not in keep and self._is_generated(relative, rules):
                excluded.append(relative.as_posix())
            else:
                measured += 1
        return {
            "files_measured": measured,
            "generated_excluded": len(excluded),
            "declaration": self.DECLARATION_FILENAME if rules else None,
            "declared_rules": len(rules),
            "excluded_sample": excluded[:8],
        }

    def _is_generated(self, relative: Path, rules: list[tuple[str, bool, bool, bool]]) -> bool:
        """Whether this path is output of the project rather than work in it."""
        if relative.as_posix() == self.DECLARATION_FILENAME:
            # The declaration can never remove itself from view. Otherwise the one file
            # that decides what is measured would be the one file nothing measures, and
            # an executor could put its own writes out of sight with a single edit.
            return False
        if self.ARTIFACT_PARTS.intersection(relative.parts):
            return True
        if relative.suffix.lower() in self.ARTIFACT_SUFFIXES:
            return True
        return self._declared_generated(relative, rules)

    def _declared_ignores(self, root: Path) -> list[tuple[str, bool, bool, bool]]:
        """Read the workspace's own statement of which of its paths are generated.

        A project knows what it generates and says so, and that statement beats any list
        TEMM could guess: `backend/data/` is a name only this project knows. Parsed is
        the practical subset of the format - comments, blank lines, `!` negation, a
        trailing `/` for directory-only rules, and `*` globbing, with a pattern
        containing a slash anchored at the workspace root and one without matching at
        any depth. As in the format itself, the last rule that matches decides.

        An unreadable or absent declaration yields no rules rather than an error: a
        malformed ignore file is not a reason to fail an attempt, it only means the
        floor above is all TEMM knows.
        """
        rules: list[tuple[str, bool, bool, bool]] = []
        try:
            lines = (root / self.DECLARATION_FILENAME).read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            return rules
        for line in lines:
            value = line.strip()
            if not value or value.startswith("#"):
                continue
            negated = value.startswith("!")
            if negated:
                value = value[1:].strip()
            directory_only = value.endswith("/")
            value = value.rstrip("/")
            anchored = "/" in value.strip("/")
            value = value.lstrip("/")
            if value:
                rules.append((value, negated, directory_only, anchored))
        return rules

    def _declared_generated(self, relative: Path, rules: list[tuple[str, bool, bool, bool]]) -> bool:
        parts = relative.parts
        # Every ancestor directory, then the file itself, because a rule naming a
        # directory excludes everything beneath it.
        candidates = [("/".join(parts[:index]), True) for index in range(1, len(parts))]
        candidates.append((relative.as_posix(), False))
        generated = False
        for pattern, negated, directory_only, anchored in rules:
            for value, is_directory in candidates:
                if directory_only and not is_directory:
                    continue
                if fnmatch.fnmatchcase(value if anchored else value.rsplit("/", 1)[-1], pattern):
                    generated = not negated
                    break
        return generated

    def diff(self, before: dict[str, str], after: dict[str, str]) -> list[dict]:
        return [{"path": path, "before": before.get(path), "after": after.get(path), "change": "added" if path not in before else "deleted" if path not in after else "modified"} for path in sorted(set(before) | set(after)) if before.get(path) != after.get(path)]

    def evaluate(self, root: Path, criteria: list[dict], diff: list[dict] | None = None, gate_results: list[dict] | None = None) -> list[dict]:
        changed = {item["path"] for item in diff or []}
        gates = {item.get("kind"): item for item in gate_results or []}
        return [self._evaluate_one(root, item, changed, gates) for item in criteria]

    def _evaluate_one(self, root: Path, criterion: dict, changed: set[str], gates: dict[str, dict]) -> dict:
        evaluator = criterion.get("evaluator") or {}
        kind = evaluator.get("type")
        relative = evaluator.get("path")
        path = root / relative if relative else None
        passed = False
        detail: dict[str, Any] = {"evaluator": evaluator}
        try:
            if kind == "json_root_dependencies_absent":
                data = json.loads(path.read_text(encoding="utf-8"))
                dependencies = data.get("dependencies", {}) if relative == "package.json" else data.get("packages", {}).get("", {}).get("dependencies", {})
                names = evaluator.get("names", [])
                passed = all(name not in dependencies for name in names)
                detail["remaining"] = [name for name in names if name in dependencies]
            elif kind == "path_absent":
                passed = not path.exists()
            elif kind == "path_exists_contains":
                measured, hops = self._substance_source(root, path)
                text = measured.read_text(encoding="utf-8")
                required = evaluator.get("contains", [])
                passed = all(value in text for value in required)
                detail["missing"] = [value for value in required if value not in text]
                if hops:
                    detail["resolved_through_reexport"] = hops
            elif kind == "file_contains_excludes":
                text = path.read_text(encoding="utf-8")
                required = evaluator.get("contains", [])
                excluded = evaluator.get("excludes", [])
                passed = all(value in text for value in required) and all(value not in text for value in excluded)
                detail.update({"missing": [value for value in required if value not in text], "present_but_excluded": [value for value in excluded if value in text]})
            elif kind == "file_exact_content":
                expected = evaluator.get("content", "")
                if path.is_file():
                    actual = path.read_text(encoding="utf-8")
                    # Strip trailing whitespace when evaluator allows it (default for proof/cert files)
                    if evaluator.get("strip_trailing_whitespace", True):
                        passed = actual.rstrip() == expected.rstrip()
                    else:
                        passed = actual == expected
                    detail["actual_length"] = len(actual)
                    detail["expected_length"] = len(expected)
                    if not passed:
                        detail["actual_repr"] = repr(actual[:200])
                        detail["expected_repr"] = repr(expected[:200])
                else:
                    passed = False
                detail["path_exists"] = path.is_file()
            elif kind == "changed_files_subset":
                allowed = set(evaluator.get("paths", []))
                # Pass if no changes at all (no unauthorized drift) OR changes are within scope.
                # Empty change set means the workspace is already in the target state.
                passed = not changed or changed <= allowed
                detail.update({"changed": sorted(changed), "outside_scope": sorted(changed - allowed)})
            elif kind == "gate_passed":
                gate = gates.get(evaluator.get("kind"))
                passed = bool(gate and gate.get("status") == "passed")
                detail["gate"] = gate
            elif kind == "all_of":
                nested = [self._evaluate_one(root, {"criterion_id": f"{criterion['criterion_id']}:{index}", "evaluator": check}, changed, gates) for index, check in enumerate(evaluator.get("checks", []))]
                passed = bool(nested) and all(item["status"] == "passed" for item in nested)
                detail["checks"] = nested
            elif kind == "python_syntax_valid":
                if path and path.is_file():
                    try:
                        content = path.read_text(encoding="utf-8")
                        ast.parse(content)
                        passed = True
                    except (SyntaxError, UnicodeError):
                        passed = False
                    detail["parse_error"] = None if passed else "Syntax error in Python file"
                else:
                    passed = False
                    detail["error"] = "File not found or not a file"
            elif kind == "deliverable_surface":
                candidates = [root / value for value in evaluator.get("paths", [])]
                if path:
                    candidates.insert(0, path)
                files = [candidate for candidate in candidates if candidate.is_file()]
                if files:
                    # Substance is read where it lives. Reachability, further down, is
                    # still asked of the contracted path, because that is the module the
                    # application imports and the one the contract named.
                    resolved = [self._substance_source(root, candidate) for candidate in files]
                    measured = [item[0] for item in resolved]
                    hops = [hop for item in resolved for hop in item[1]]
                    content = "\n".join(candidate.read_text(encoding="utf-8") for candidate in measured)
                    # Check for placeholder content
                    if self._is_placeholder_content(content):
                        passed = False
                        detail["reason"] = "Placeholder content"
                    else:
                        # Additional checks based on file type or surface_type if provided
                        surface_type = evaluator.get("surface_type", "generic")
                        if surface_type == "frontend":
                            # For frontend, we expect HTML with some structural elements
                            if all(candidate.suffix.lower() in [".html", ".htm"] for candidate in measured):
                                # Check for at least one HTML tag and not just a comment
                                if "<" in content and ">" in content and not (content.strip().startswith("<!--") and content.strip().endswith("-->")):
                                    passed = True
                                else:
                                    passed = False
                                    detail["reason"] = "No HTML tags found or only comment"
                            else:
                                # For JS/TS, we expect some framework indicators or DOM manipulation
                                # We'll do a simple check for now
                                if len(content.strip()) > 0:
                                    passed = True
                                else:
                                    passed = False
                                    detail["reason"] = "Empty file"
                        elif surface_type == "backend":
                            # For backend, we expect a server file with a route or listen
                            if "app.listen" in content or "app.route" in content or "@app.route" in content or "http.createServer" in content:
                                passed = True
                            else:
                                passed = False
                                detail["reason"] = "No server indicators found"
                        elif surface_type == "cli":
                            # For CLI, we expect a main function or shebang
                            if "#!" in content.split('\n')[0] or "def main(" in content or "if __name__ == '__main__':" in content:
                                passed = True
                            else:
                                passed = False
                                detail["reason"] = "No CLI indicators found"
                        else:
                            # Generic: just not placeholder and not empty
                            if len(content.strip()) > 0:
                                passed = True
                            else:
                                passed = False
                                detail["reason"] = "Empty file"
                    min_chars = int(evaluator.get("min_chars", 1))
                    required_any = [str(value) for value in evaluator.get("required_any", [])]
                    # Substance is still sized on the file as written - a licence
                    # header is content - so only the clause match reads the stripped
                    # text.
                    resolution = self._endpoint_resolution(root, measured, required_any)
                    matched = resolution["matched"]
                    passed = passed and len(content) >= min_chars and (not required_any or bool(matched))
                    detail.update({"files": [candidate.relative_to(root).as_posix() for candidate in files], "content_length": len(content), "matched": matched})
                    if required_any:
                        detail["required_any_resolution"] = resolution
                    if hops:
                        detail["measured_files"] = [self._hop_label(self._resolved_or_none(root), candidate) for candidate in measured]
                        detail["resolved_through_reexport"] = hops
                    if passed and evaluator.get("require_reachable", True):
                        reach = self._reachability(root, files)
                        detail["reachability"] = reach
                        if reach["status"] == "unreachable":
                            passed = False
                            detail["reason"] = "Surface is not reachable from any application entry point"
                else:
                    passed = False
                    detail["error"] = "File not found or not a file"
            elif kind == "paths_exist":
                paths = [str(value) for value in evaluator.get("paths", [])]
                missing = [value for value in paths if not (root / value).is_file()]
                passed = bool(paths) and not missing
                detail["missing"] = missing
            elif kind == "workspace_material":
                files = [candidate for candidate in root.rglob("*") if candidate.is_file() and not self.IGNORED_PARTS.intersection(candidate.relative_to(root).parts)]
                passed = len(files) >= int(evaluator.get("min_files", 1))
                detail["file_count"] = len(files)
            else:
                passed = False
                detail["error"] = f"Unknown evaluator kind: {kind}"
        except (OSError, UnicodeError, json.JSONDecodeError, SyntaxError) as exc:
            detail["error"] = type(exc).__name__
            passed = False
        return {"criterion_id": criterion["criterion_id"], "status": "passed" if passed else "failed", "evidence": detail}

    def _is_placeholder_content(self, content: str) -> bool:
        """Report whether content is a stub rather than a real deliverable.

        Indicators are matched as whole words. Substring matching rejected
        legitimate code for containing "latest" or "resample", which made the
        acceptance contract unsatisfiable rather than merely unmet, so every
        attempt at the work failed no matter how complete it was. Whole words
        were still too coarse for "placeholder": it is a standard HTML attribute,
        so a 23KB orders screen with three real form fields was condemned as a
        stub, and no form-bearing screen could ever satisfy its contract.
        """
        if not content or content.isspace():
            return True
        if self.STRONG_PLACEHOLDER_PATTERN.search(content) or self.PLACEHOLDER_WORD_PATTERN.search(content):
            return True
        lines = [line.strip() for line in content.splitlines() if line.strip()]
        if not lines:
            return True
        # Content that is only commentary declares intent without implementing it.
        body = [line for line in lines if not line.startswith(("#", "//", "/*", "*", "<!--", "-->", "'"))]
        if not body:
            return True
        # Stub vocabulary only condemns content too small to be the real thing.
        return len("\n".join(body)) < self.WEAK_PLACEHOLDER_MAX_CHARS and bool(self.WEAK_PLACEHOLDER_PATTERN.search(content))

    # --- Reachability ------------------------------------------------------
    # Everything below answers one question about a candidate file: does a chain
    # of imports lead to it from something the application actually starts at?
    MODULE_SUFFIXES = (".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs")
    SOURCE_SUFFIXES = MODULE_SUFFIXES + (".py",)
    MANIFEST_NAMES = ("package.json", "pyproject.toml", "setup.py")
    ENTRY_RELATIVE_PATHS = (
        "src/main.tsx", "src/main.ts", "src/main.jsx", "src/main.js",
        "src/index.tsx", "src/index.ts", "src/index.jsx", "src/index.js",
        "src/server.ts", "src/server.js", "src/app.ts", "src/app.js",
        "main.tsx", "main.ts", "main.jsx", "main.js",
        "index.tsx", "index.ts", "index.jsx", "index.js",
        "src/main.py", "src/__main__.py", "main.py", "__main__.py", "app.py", "manage.py",
    )
    # Bounded so a pathological tree cannot turn one criterion into a full-disk
    # walk. Far above any real application's module count.
    REACHABILITY_MAX_MODULES = 4000
    # Evidence names the entry points it walked from; a suite contributes hundreds,
    # and the receipt is read by people.
    MAX_SHOWN_ENTRY_POINTS = 12
    # --- Endpoint clauses --------------------------------------------------
    # How far out from a contracted surface an endpoint clause may resolve. A screen
    # reaches its API client in one hop and reaches it through a hook or a context
    # provider in two; past that the module is somebody else's business and a match
    # there says nothing about this surface.
    ENDPOINT_CLOSURE_MAX_DEPTH = 3
    # Bounded like every other walk here, and far above a real screen's fan-out.
    ENDPOINT_CLOSURE_MAX_MODULES = 200
    # A request path as it is written in code: quoted, and ending where a path ends -
    # a closing quote, a query, an interpolation, or another segment. The delimiter is
    # what makes a short tail safe to infer from: `/me` matches `"/me"` and
    # `` `/me/${id}` `` and does not match `"/members"`.
    ENDPOINT_TAIL_TEMPLATE = r"""['"`]{tail}(?:['"`?/]|\$\{{)"""
    # The base a client factors out of every path, as a literal it can be read from -
    # either alone (`"/api"`, the same-origin fallback) or ending a URL
    # (`"https://api.example.com/api"`, which is what a deployed `VITE_API_URL` holds).
    # Requiring the base to stand alone would fail every absolute base on correct code,
    # which is the defect this reading exists to remove. Newlines are excluded so the
    # match cannot run across a quote it never closed, and the tail still has to be
    # written as a path in the same closure - that half is what carries the weight.
    ENDPOINT_BASE_TEMPLATE = r"""['"`][^'"`\n]*{base}/?['"`]"""

    # Static import, side-effect import, re-export, `require`, and dynamic
    # `import()` - every form that puts one module in another's graph.
    JS_IMPORT_PATTERN = re.compile(r"""(?:\brequire\s*\(|\bimport\s*\(|\bfrom\b|\bimport\b)\s*['"]([^'"]+)['"]""")
    # Vite's directory import. A route table built this way wires real screens
    # without naming one, and calling those unreachable would be plainly wrong.
    JS_GLOB_PATTERN = re.compile(r"""import\.meta\.glob\w*\(\s*\[?\s*['"]([^'"]+)['"]""")
    # What a test runner collects with no configuration: vitest and jest take
    # `*.test.*` and `*.spec.*`, pytest takes `test_*.py`, `*_test.py` and
    # `conftest.py`. A module named this way is loaded by the runner, which is why
    # the application never imports it.
    TEST_NAME_PATTERN = re.compile(r"(?:\.(?:test|spec)\.[^.]+$)|(?:^test_.+\.py$)|(?:.+_test\.py$)|(?:^conftest\.py$)", re.IGNORECASE)
    # Where projects keep tests. A file here that the runner does not collect is a
    # helper for the tests that do - reachable only if one of them imports it.
    TEST_DIRECTORY_NAMES = {"test", "tests", "__tests__", "spec", "specs", "e2e"}
    # The scan for collected tests is bounded the same way the import walk is: a
    # suite larger than this is entered through its first 500 modules, in path order.
    REACHABILITY_MAX_TEST_ENTRIES = 500
    # Directories that hold no authored source, kept out of the scan alongside
    # IGNORED_PARTS and anything dot-prefixed.
    TEST_SCAN_SKIP_DIRECTORIES = {"__pycache__", "build", "coverage", "htmlcov", "venv"}

    def _reachability(self, root: Path, files: list[Path]) -> dict:
        """Report whether any of these files is reachable from an entry point.

        `deliverable_surface` accepted a file that exists and holds real content as
        having delivered a surface, but a surface nobody can open is not delivered.
        Production evidence 2026-08-19: NEXA's `OrdersPage.tsx` - 23KB, a complete
        multi-item order workflow against a live `/api/orders` client - satisfied
        every criterion of its requirement while being imported by exactly zero
        files. The requirement stood one acceptance away from complete, and the
        browser step that opens the orders screen would have failed outright.

        The verdict is `not_applicable` unless the workspace answers both halves of
        the question: a candidate that is a source module, and at least one entry
        point to walk from. A criterion naming an `index.html`, or a directory of
        loose files with nothing that starts, is judged exactly as it was before.

        Which entry points those are depends on what the surface is. Production
        evidence 2026-08-21, attempt-18a944ee9c04: a 347-second, 2.08M-token run
        wrote `backend/src/tests/orders.test.ts` - 12886 characters of executable
        proof that an order totals correctly and takes stock from 20 to 17 - and the
        criterion failed on reachability alone, because the walk started at
        `backend/src/index.ts` and `backend/src/app.ts` and no application imports
        its tests. The runner does. Stated as a rule the executor could satisfy, that
        criterion asked for production code to import a test file; the criterion was
        unsatisfiable by construction, and every attempt at it cost another run of
        that size. So the test runner is an entry point in its own right, and the
        modules it collects are where the walk for a test surface begins. Nothing is
        relaxed for application code: an orphaned screen fails exactly as before.
        """
        root_resolved = root.resolve()
        modules = [item for item in files if item.suffix.lower() in self.SOURCE_SUFFIXES]
        if not modules:
            return {"status": "not_applicable", "reason": "No source module among the candidates"}
        package_root = self._package_root(root_resolved, modules[0])

        def shown(path: Path) -> str:
            try:
                return path.relative_to(root_resolved).as_posix() or "."
            except ValueError:
                return path.as_posix()

        application_entries = self._application_entry_points(package_root)
        # Asked only when a candidate is part of the tests, because scanning for
        # collected tests costs a directory walk and answers nothing otherwise.
        runner_entries = self._test_entry_points(package_root) if any(self._test_scoped(package_root, item) for item in modules) else []
        if not application_entries and not runner_entries:
            return {"status": "not_applicable", "reason": "No application entry point found", "package_root": shown(package_root)}
        targets = {item.resolve() for item in modules}
        walked = 0
        for kind, entries in (("application", application_entries), ("test_runner", runner_entries)):
            if not entries:
                continue
            reached, seen = self._walk_modules(entries, package_root, targets)
            walked += len(seen)
            if reached is not None:
                return {"status": "reachable", "module": shown(reached), "entry_kind": kind, "entry_points": self._shown_entries(entries, shown), "modules_walked": walked}
        return {"status": "unreachable", "modules": [shown(item) for item in modules], "entry_points": self._shown_entries(application_entries + runner_entries, shown), "modules_walked": walked}

    def _application_entry_points(self, package_root: Path) -> list[Path]:
        """The files the application itself starts at."""
        entries = [package_root / value for value in self.ENTRY_RELATIVE_PATHS]
        return [item.resolve() for item in entries if item.is_file()]

    def _test_entry_points(self, package_root: Path) -> list[Path]:
        """Every module the project's test runner collects by convention, bounded.

        These are entry points in the same sense as `src/main.tsx`: nothing in the
        package imports them, something outside it loads them directly.
        """
        found: list[Path] = []
        visited = 0
        stack = [package_root]
        while stack and len(found) < self.REACHABILITY_MAX_TEST_ENTRIES and visited < self.REACHABILITY_MAX_MODULES:
            try:
                children = sorted(stack.pop().iterdir())
            except OSError:
                continue
            for child in children:
                if child.is_dir():
                    if child.name in self.IGNORED_PARTS or child.name in self.TEST_SCAN_SKIP_DIRECTORIES or child.name.startswith("."):
                        continue
                    stack.append(child)
                    continue
                visited += 1
                if child.suffix.lower() in self.SOURCE_SUFFIXES and self.TEST_NAME_PATTERN.search(child.name):
                    found.append(child.resolve())
        return sorted(set(found))

    def _walk_modules(self, entries: list[Path], package_root: Path, targets: set[Path] | None = None) -> tuple[Path | None, set[Path]]:
        """Follow imports out from these entry points, stopping at the first target."""
        seen: set[Path] = set()
        queue = list(entries)
        while queue and len(seen) < self.REACHABILITY_MAX_MODULES:
            current = queue.pop()
            if current in seen:
                continue
            seen.add(current)
            if targets and current in targets:
                return current, seen
            queue.extend(self._module_edges(current, package_root))
        return None, seen

    def _shown_entries(self, entries: list[Path], shown) -> list[str]:
        """The entry points named in the evidence, capped so a large suite stays legible."""
        names = list(dict.fromkeys(shown(item) for item in entries))
        return names if len(names) <= self.MAX_SHOWN_ENTRY_POINTS else names[: self.MAX_SHOWN_ENTRY_POINTS] + [f"... and {len(names) - self.MAX_SHOWN_ENTRY_POINTS} more"]

    def _test_scoped(self, package_root: Path, module: Path) -> bool:
        """Is this module part of the project's tests?"""
        resolved = module.resolve()
        try:
            relative = resolved.relative_to(package_root)
        except ValueError:
            relative = Path(resolved.name)
        return self.test_scoped_path(relative.as_posix())

    @classmethod
    def test_scoped_path(cls, value: str) -> bool:
        """Whether a path belongs to the tests, read from the path alone.

        Shared with the dispatcher, which states the obligation a surface carries
        before any of it exists on disk: telling an executor to make a test file
        reachable from the application is telling it to do the wrong thing.
        """
        parts = [part for part in str(value).replace("\\", "/").split("/") if part not in ("", ".")]
        if not parts:
            return False
        return bool(cls.TEST_NAME_PATTERN.search(parts[-1])) or any(part.lower() in cls.TEST_DIRECTORY_NAMES for part in parts[:-1])

    @classmethod
    def test_collected_path(cls, value: str) -> bool:
        """Whether the runner collects this path itself, rather than a test importing it."""
        name = str(value).replace("\\", "/").rsplit("/", 1)[-1]
        return bool(cls.TEST_NAME_PATTERN.search(name))

    def reachable_modules(self, root: Path, files: list[Path]) -> list[str]:
        """Workspace-relative modules reachable from the application entry points.

        This is the app shell the reachability walk sees, computed against the same
        package root as `_reachability` (derived from `files`, so a monorepo's other
        packages are excluded). A surface becomes reachable only by adding an import
        edge from a module already on this graph to the surface, so every module here
        is a legitimate - and the only useful - place to wire the surface in. A repair
        carrying a reachability-bearing `deliverable_surface` widens its write scope to
        this set: without it the contract demands an edit the scope forbids and can
        never pass. Editing anything off this graph cannot establish reachability, so
        nothing outside it is lost by leaving it out of scope.

        A test helper is wired in from a collected test rather than from the
        application, so for one of those the graph is the runner's. A collected test
        needs no wiring at all - it is an entry point - and widens nothing.
        """
        root_resolved = root.resolve()
        modules = [item for item in files if item.suffix.lower() in self.SOURCE_SUFFIXES]
        if not modules:
            return []
        package_root = self._package_root(root_resolved, modules[0])
        entries = self._application_entry_points(package_root)
        if any(self._test_scoped(package_root, item) and not self.test_collected_path(item.name) for item in modules):
            entries = list(dict.fromkeys(entries + self._test_entry_points(package_root)))
        if not entries:
            return []
        _, seen = self._walk_modules(entries, package_root)
        out: list[str] = []
        for item in seen:
            try:
                out.append(item.relative_to(root_resolved).as_posix())
            except ValueError:
                continue
        return list(dict.fromkeys(out))

    # A module whose entire body forwards its exports elsewhere. `export * as ns`,
    # `export type { X }`, and a braced list are all the same shape: no declaration
    # of its own, one specifier, everything the importer sees defined elsewhere.
    REEXPORT_STATEMENT_PATTERN = re.compile(r"""^export\s+(?:type\s+)?(?:\*\s*(?:as\s+[\w$]+\s*)?|\{[^{}]*\}\s*)from\s*['"]([^'"]+)['"]$""")
    # Aliases chain in real trees - a page barrel behind a directory barrel - but a
    # long chain means something other than an alias, so the walk is short.
    REEXPORT_MAX_HOPS = 3

    @staticmethod
    def _without_comments(text: str) -> str:
        """The code of a module, with block and line comments removed.

        Prose is not behaviour. A clause satisfied by a comment measures nothing, and
        the same stripping keeps a licence header from making a re-export look like a
        module with substance of its own.

        A `//` after a colon is a scheme, not a comment. Without that guard the rest of
        any line holding `"https://host/api"` is deleted along with the base literal it
        carries, so an absolute API base would fail a clause its code plainly satisfies -
        a false negative of exactly the kind this reading exists to remove. The cost is a
        line comment opened directly after a colon, which is rare enough and errs toward
        reading real code rather than discarding it.
        """
        text = re.sub(r"/\*.*?\*/", " ", text, flags=re.DOTALL)
        return re.sub(r"(?m)(?<!:)//.*$", "", text)

    def _endpoint_resolution(self, root: Path, measured: list[Path], required_any: list[str]) -> dict:
        """Which `required_any` clauses this surface satisfies, and on what grounds.

        The clause means "this surface talks to that endpoint", and it was measured as
        "this file's text contains that string". For any frontend that factors its base
        URL out - which is every one worth shipping - those are different questions
        with opposite answers, and the substring is wrong in both directions.

        Production evidence 2026-08-21/22, NEXA project-23a514f0c426. Wrong negative:
        `frontend/src/api/client.ts` holds `API_BASE = import.meta.env.VITE_API_URL ??
        "/api"` and composes `fetch(`${API_BASE}${path}`)`, so every call site names
        only the tail - `"/auth/me"`, `"/auth/login"`, `` `/activities${query}` ``. The
        literal `/api/auth/me` appears nowhere in `frontend/src`, so no screen can
        contain it without hardcoding a string it never uses. attempt-a267d4d0addd
        completed in 342s over 52 tool uses, created `LoginPage.tsx` and
        `AuthProvider.tsx` with the endpoints reached correctly through the shared
        client, touched every path its own run-focus named, and failed both clauses on
        `matched: []`. Wrong positive: the one screen in the project that passed this
        family, `OrdersPage.tsx`, passed on a doc comment - "reuses the shared API
        client for /api/orders" - while calling `api.listOrders()` like every other
        screen. So the clause was failed by working code and passed by prose.

        Both faces are one fault, and one reading answers both. A clause is satisfied
        when the literal is in the surface's own code, or when the surface's own import
        closure reaches a module that issues the request: the endpoint's tail written
        as a path, and the base it hangs off written as a literal the client can be
        read from. Comments count for nothing on either route.

        This cannot manufacture a pass. The closure is the surface's own - walked
        outward from the contracted file, never inward from the entry points - so a
        file that imports no client resolves nothing, and a file that does not exist
        resolves nothing at all. `min_chars`, the placeholder check and reachability are
        untouched and still measured on the contracted path, so a stub that imports the
        client fails exactly as before. The inferred half is guarded: a tail counts only
        where a path is actually written, quoted and ending as a path ends, which is why
        `/me` cannot be read out of `"/members"`. Any ambiguity resolves the other way -
        an unreadable module, an unresolvable specifier, a base that exists only in the
        environment - and the clause fails as it did before.
        """
        if not required_any:
            return {"matched": [], "scope": "no_clause"}
        own = self._without_comments("\n".join(self._read_or_empty(item) for item in measured))
        matched: list[str] = []
        grounds: list[dict] = []
        outstanding: list[str] = []
        for value in required_any:
            if value.lower() in own.lower():
                matched.append(value.lower())
                grounds.append({"clause": value, "form": "literal", "scope": "surface"})
            else:
                outstanding.append(value)
        if not outstanding:
            return {"matched": matched, "scope": "surface", "grounds": grounds}
        closure = self._endpoint_closure(root, measured)
        texts = [(module, self._without_comments(self._read_or_empty(module))) for _, module in closure]
        combined = "\n".join(text for _, text in texts)
        for value in outstanding:
            found = self._clause_in_closure(root, value, texts, combined)
            if found is None:
                continue
            matched.append(value.lower())
            grounds.append(found)
        return {
            "matched": matched,
            "scope": "import_closure",
            "grounds": grounds,
            "unresolved": [value for value in required_any if value.lower() not in matched],
            "closure_modules": len(closure),
            "closure_depth_limit": self.ENDPOINT_CLOSURE_MAX_DEPTH,
        }

    def _clause_in_closure(self, root: Path, value: str, texts: list[tuple[Path, str]], combined: str) -> dict | None:
        """Where a surface's import closure issues this endpoint's request, if anywhere.

        Only a rooted path resolves out here. A clause that is not one is a statement
        about the contracted file itself - `Routes` in `App.tsx` describes App.tsx - and
        answering it from the closure would pass a shell that has no routing because
        something it imports happens to mention one. The measured defect is entirely in
        request paths and the widening stops there; every other clause is still read on
        the contracted surface exactly as before.

        Two ways a closure answers a path, in order of directness: a module writes it
        whole, or a module writes its tail off a base the closure defines. The split is
        tried at every segment boundary because a base is `/api` in one project and
        `/api/v1` in the next, and both readings demand the path be written where a path
        is written - quoted and delimited - so neither can be read out of a longer word.
        Which reading was used is reported, so a receipt says how a clause was answered
        rather than only that it was.
        """
        if not value.startswith("/"):
            return None
        resolved_root = self._resolved_or_none(root)
        whole = re.compile(self.ENDPOINT_TAIL_TEMPLATE.format(tail=re.escape(value)), re.IGNORECASE)
        for module, text in texts:
            if whole.search(text):
                return {"clause": value, "form": "literal", "scope": "import_closure", "module": self._hop_label(resolved_root, module)}
        segments = [part for part in value.split("/") if part]
        for index in range(1, len(segments)):
            base = "/" + "/".join(segments[:index])
            tail = "/" + "/".join(segments[index:])
            if not re.search(self.ENDPOINT_BASE_TEMPLATE.format(base=re.escape(base)), combined, re.IGNORECASE):
                continue
            pattern = self.ENDPOINT_TAIL_TEMPLATE.format(tail=re.escape(tail))
            for module, text in texts:
                if re.search(pattern, text, re.IGNORECASE):
                    return {
                        "clause": value,
                        "form": "composed",
                        "scope": "import_closure",
                        "module": self._hop_label(resolved_root, module),
                        "base": base,
                        "tail": tail,
                    }
        return None

    def _endpoint_closure(self, root: Path, measured: list[Path]) -> list[tuple[int, Path]]:
        """The modules a surface imports, outward from the surface, depth-bounded.

        Deliberately the opposite direction from `_reachability`: that asks whether the
        application reaches this file, this asks what this file reaches. Answering an
        endpoint clause from the reachability graph would let any module in the app
        satisfy any clause about any surface.
        """
        modules = [item for item in measured if item.suffix.lower() in self.MODULE_SUFFIXES]
        if not modules:
            return []
        package_root = self._package_root(self._resolved_or_none(root), modules[0])
        seen = {self._resolved_or_none(item) for item in modules}
        found: list[tuple[int, Path]] = []
        frontier = [self._resolved_or_none(item) for item in modules]
        for depth in range(1, self.ENDPOINT_CLOSURE_MAX_DEPTH + 1):
            following: list[Path] = []
            for module in frontier:
                for edge in self._module_edges(module, package_root):
                    resolved = self._resolved_or_none(edge)
                    if resolved in seen:
                        continue
                    seen.add(resolved)
                    found.append((depth, resolved))
                    following.append(resolved)
                    if len(found) >= self.ENDPOINT_CLOSURE_MAX_MODULES:
                        return found
            if not following:
                break
            frontier = following
        return found

    @staticmethod
    def _read_or_empty(path: Path) -> str:
        """A module's text, or nothing when it cannot be read.

        An unreadable module contributes no evidence either way, which fails a clause
        that only it could have answered - the conservative direction.
        """
        try:
            return path.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            return ""

    def _substance_source(self, root: Path, path: Path) -> tuple[Path, list[str]]:
        """The module whose content answers a contract about `path`.

        Normally that is `path` itself. When `path` is a pure re-export it is the
        module `path` forwards to, because a re-export has no substance of its own to
        measure: every symbol the importer receives is defined elsewhere, and reading
        the forwarding line instead of the definition measures the wrong file.

        Production evidence 2026-08-21: `task-234c939b0fe9` executed genuinely - 72
        tool uses, all three engineering gates green, eight files changed - and failed
        `customers:screen` (min_chars 1500, required_any `/api/customers`) and
        `customers:search` (contains `search`) because
        `frontend/src/pages/CustomersPage.tsx` is 57 bytes of
        `export { default, CustomersPage } from "./CustomerPage";` while the screen
        those clauses describe sits in the 18,232 bytes of `CustomerPage.tsx` beside
        it. The barrel is load-bearing, not contract-gaming: `App.tsx` imports
        `CustomersPage` through it and renders it. So a delivered, wired, reachable
        screen failed clauses its real module satisfies many times over.

        This cannot be used to manufacture a pass. Substance is still measured, only
        at the module that has it: the target must itself contain what the clause
        requires, and a pure re-export contributes not one character toward it. What
        the resolution buys is the ability to see through a file layout, not a lower
        bar. Any ambiguity resolves the other way - an aggregator forwarding to
        several modules, a file with a declaration of its own, an unresolvable
        specifier, a cycle - and the contracted path is measured exactly as before.

        Returns the module to read and the hops taken to reach it, so a receipt says
        where it looked rather than appearing to have read a file it did not.
        """
        hops: list[str] = []
        current = path
        resolved_root = self._resolved_or_none(root)
        seen = {self._resolved_or_none(current)}
        for _ in range(self.REEXPORT_MAX_HOPS):
            target = self._pure_reexport_target(root, current)
            if target is None or self._resolved_or_none(target) in seen:
                break
            seen.add(self._resolved_or_none(target))
            current = target
            hops.append(self._hop_label(resolved_root, target))
        return current, hops

    def _hop_label(self, resolved_root: Path, target: Path) -> str:
        """Where the substance was read, named relative to the workspace when it can be.

        A root reached through a symlink, a junction, or a Windows 8.3 short name is
        not a textual prefix of the resolved target even though it is the same
        directory, and `relative_to` raises on that. A receipt line is not worth
        failing a criterion over, so the absolute path stands in.
        """
        candidate = self._resolved_or_none(target)
        try:
            return candidate.relative_to(resolved_root).as_posix()
        except ValueError:
            return candidate.as_posix()

    def _pure_reexport_target(self, root: Path, module: Path) -> Path | None:
        """The single module `module` forwards to, or nothing if it is not pure.

        Scoped to JS/TS on purpose. The barrel is that ecosystem's idiom and the
        measured defect is there; Python's nearest equivalent re-exports through
        `__init__.py`, which a contract names as a package rather than as the module
        holding a screen. Extending this needs its own evidence, not an analogy.
        """
        if module.suffix.lower() not in self.MODULE_SUFFIXES:
            return None
        try:
            text = module.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            return None
        specifiers = set()
        for statement in self._top_level_statements(text):
            match = self.REEXPORT_STATEMENT_PATTERN.match(statement)
            if match is None:
                # One statement that is not a re-export means the file has substance
                # of its own, and that substance is what the contract asked about.
                return None
            specifiers.add(match.group(1))
        if len(specifiers) != 1:
            # Nothing forwarded, or forwarded to several modules. An aggregator has no
            # single module to measure in, so the contracted path stands.
            return None
        target = self._resolve_module(module, specifiers.pop(), self._package_root(root, module))
        if target is None or not target.is_file():
            return None
        resolved_root = self._resolved_or_none(root)
        if resolved_root is None or not self._resolved_or_none(target).is_relative_to(resolved_root):
            return None
        return target

    @staticmethod
    def _resolved_or_none(path: Path) -> Path:
        """`resolve()` without requiring the path to exist, for identity comparison."""
        try:
            return path.resolve()
        except OSError:
            return path

    @staticmethod
    def _top_level_statements(text: str):
        """Statements of a module, split where a statement can actually end.

        Comments are removed first because they are not substance - a licence header
        above a re-export does not make the file a module in its own right. Splitting
        on `;` and on newlines outside brackets keeps a braced export list that spans
        lines in one piece. Anything this splits wrongly fails to match the re-export
        shape, which resolves to the contracted path - the conservative direction.
        """
        text = WorkspaceAcceptanceService._without_comments(text)
        depth = 0
        current: list[str] = []
        for character in text:
            if character in "{([":
                depth += 1
            elif character in "})]":
                depth = max(depth - 1, 0)
            if character == ";" or (character == "\n" and depth == 0):
                statement = " ".join("".join(current).split())
                if statement:
                    yield statement
                current = []
                continue
            current.append(character)
        statement = " ".join("".join(current).split())
        if statement:
            yield statement

    def _package_root(self, root: Path, module: Path) -> Path:
        """The nearest enclosing manifest directory - a monorepo has several."""
        current = module.resolve().parent
        while True:
            if any((current / name).is_file() for name in self.MANIFEST_NAMES):
                return current
            if current == root or current.parent == current:
                return root
            current = current.parent

    def _module_edges(self, module: Path, package_root: Path) -> list[Path]:
        suffix = module.suffix.lower()
        if suffix == ".py":
            return self._python_edges(module, package_root)
        if suffix not in self.MODULE_SUFFIXES:
            return []
        try:
            text = module.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            return []
        edges = [self._resolve_module(module, match.group(1), package_root) for match in self.JS_IMPORT_PATTERN.finditer(text)]
        for match in self.JS_GLOB_PATTERN.finditer(text):
            specifier = match.group(1)
            if not specifier.startswith("."):
                continue
            for found in glob.glob(str(module.parent / specifier), recursive=True):
                candidate = Path(found)
                if candidate.is_file() and candidate.suffix.lower() in self.SOURCE_SUFFIXES:
                    edges.append(candidate.resolve())
        return [item for item in edges if item is not None]

    def _python_edges(self, module: Path, package_root: Path) -> list[Path]:
        try:
            tree = ast.parse(module.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, SyntaxError, ValueError):
            return []
        edges: list[Path] = []

        def add(target: Path) -> None:
            for candidate in self._module_candidates(target):
                if candidate.is_file() and not self.IGNORED_PARTS.intersection(candidate.parts):
                    edges.append(candidate.resolve())
                    return

        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                base = module.parent
                for _ in range(max(node.level - 1, 0)):
                    base = base.parent
                parts = (node.module or "").split(".") if node.module else []
                target = (base if node.level else package_root).joinpath(*parts)
                add(target)
                for alias in node.names:
                    add(target / alias.name)
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    add(package_root.joinpath(*alias.name.split(".")))
        return edges

    def _resolve_module(self, importer: Path, specifier: str, package_root: Path) -> Path | None:
        """Resolve one import specifier to a workspace file, or to nothing.

        A bare specifier names a published package, which is not workspace code and
        so not part of the graph a surface is reached through.
        """
        if specifier.startswith("."):
            bases = [importer.parent / specifier]
        elif specifier.startswith(("@/", "~/")):
            bases = [package_root / "src" / specifier[2:], package_root / specifier[2:]]
        elif specifier.startswith(("src/", "./src/")):
            bases = [package_root / specifier]
        else:
            return None
        for base in bases:
            for candidate in self._module_candidates(base):
                if candidate.is_file() and not self.IGNORED_PARTS.intersection(candidate.parts):
                    return candidate.resolve()
        return None

    def _module_candidates(self, target: Path):
        yield target
        for suffix in self.SOURCE_SUFFIXES:
            yield target.with_name(target.name + suffix)
        for suffix in self.MODULE_SUFFIXES:
            yield target / f"index{suffix}"
        yield target / "__init__.py"

    def merge_progress(self, criteria: list[dict], results: list[dict]) -> list[dict]:

        by_id = {item["criterion_id"]: item for item in results}
        return [{**criterion, "last_status": by_id.get(criterion["criterion_id"], {}).get("status", "pending"), "last_evidence": by_id.get(criterion["criterion_id"], {}).get("evidence")} for criterion in criteria]


workspace_acceptance_service = WorkspaceAcceptanceService()
