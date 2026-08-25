import json
import tempfile
import unittest
from pathlib import Path

from core.ai_fleet.services.workspace_acceptance import WorkspaceAcceptanceService


class WorkspaceAcceptanceTests(unittest.TestCase):
    def test_diff_and_criteria_preserve_partial_progress_without_claiming_completion(self):
        service = WorkspaceAcceptanceService()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "package.json").write_text(json.dumps({"dependencies": {"i18next": "1", "react": "1"}}), encoding="utf-8")
            before = service.snapshot(root)
            (root / "package.json").write_text(json.dumps({"dependencies": {"react": "1"}}), encoding="utf-8")
            after = service.snapshot(root)
            diff = service.diff(before, after)
            results = service.evaluate(root, [
                {"criterion_id": "dependency", "evaluator": {"type": "json_root_dependencies_absent", "path": "package.json", "names": ["i18next"]}},
                {"criterion_id": "missing-context", "evaluator": {"type": "path_exists_contains", "path": "src/context.tsx", "contains": ["Provider"]}},
            ], diff)
        self.assertEqual(diff[0]["path"], "package.json")
        self.assertEqual([item["status"] for item in results], ["passed", "failed"])

    def test_running_the_app_to_verify_the_work_does_not_fail_the_scope_it_stayed_inside(self):
        """Defect #68: the snapshot counted the application's own output as authored work.

        `snapshot` ignored only `{node_modules, dist, .git}`, so every generated runtime
        artifact was hashed and turned up in `workspace_diff`. That diff is the sole
        evidence behind three separate conclusions, and one artifact corrupts all three:
        the `changed_files_subset` scope clause, the `no_effect` verdict, and the
        `file_write`/`coding`/`file_read` capability floor. An executor asked to verify
        its own work starts the application, the application writes its own database,
        and the run is then recorded as having written outside its scope.

        Production evidence, attempt-cde42a0d2608 on task-3bd4d689eb9d, 2026-08-22
        01:09:02, route opencode/x-preview-f-free: 67 tool uses and 3.56M tokens over 25
        minutes, with headless-Chrome viewport measurement in the stdout tail. It wrote
        no source at all, and its entire `workspace_diff` was one entry - `backend/data/
        app.db` - which the workspace's own `.gitignore` declares generated on line 18.
        The scope clause failed on `outside_scope: ["backend/data/app.db"]`, so the clause
        was unsatisfiable for any run that verifies itself, however perfectly it had
        delivered; and the receipt recorded `production_workspace_effect`, renewing the
        route's coding floor from a database file no model authored.
        """
        service = WorkspaceAcceptanceService()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".gitignore").write_text("# Local SQLite storage\nbackend/data/\n", encoding="utf-8")
            (root / "src").mkdir()
            (root / "src" / "App.tsx").write_text("export const App = () => <Routes />;\n", encoding="utf-8")
            (root / "backend" / "data").mkdir(parents=True)
            database = root / "backend" / "data" / "app.db"
            database.write_bytes(b"sqlite-page-0")
            scope = {"criterion_id": "scope", "evaluator": {"type": "changed_files_subset", "paths": ["src/App.tsx"]}}
            protected = service.measured_paths([scope])

            before = service.snapshot(root, protected=protected)
            # The executor starts the app to check its work. The app writes its database.
            database.write_bytes(b"sqlite-page-0-plus-a-row")
            after = service.snapshot(root, protected=protected)
            diff = service.diff(before, after)
            verified = service.evaluate(root, [scope], diff)[0]

            # And the same run, having also delivered its one source file.
            (root / "src" / "App.tsx").write_text("export const App = () => <Routes><Sidebar /></Routes>;\n", encoding="utf-8")
            delivered_diff = service.diff(before, service.snapshot(root, protected=protected))
            delivered = service.evaluate(root, [scope], delivered_diff)[0]
            census = service.artifact_census(root, protected)

        # The database is not work, so it is not evidence of any kind.
        self.assertEqual(diff, [], "The application's own database is not a change the model authored.")
        self.assertEqual(verified["status"], "passed")
        self.assertEqual(verified["evidence"]["outside_scope"], [])
        # Which is what makes the clause satisfiable by a run that delivers and verifies.
        self.assertEqual([item["path"] for item in delivered_diff], ["src/App.tsx"])
        self.assertEqual(delivered["status"], "passed")
        # The two conclusions drawn from an empty diff are now drawn truthfully: a run
        # that only touched the database produced no effect and proves no capability.
        self.assertFalse(bool(diff), "effect_observed must be False for a run that wrote nothing.")
        self.assertEqual([entry["change"] for entry in diff], [], "No change means no capability to renew.")
        # And the exclusion is stated, so an empty diff is never unexplained.
        self.assertEqual(census["generated_excluded"], 1)
        self.assertEqual(census["excluded_sample"], ["backend/data/app.db"])
        self.assertEqual(census["declaration"], ".gitignore")

    def test_the_workspace_declaration_cannot_hide_what_acceptance_measures(self):
        """The measured party authors the declaration, so it may not narrow measurement.

        Honouring `.gitignore` is what makes the exclusion generic - `backend/data/` is a
        name only that project knows, and no list TEMM could guess would contain it. But
        the executor writes that file too, so two things must hold however the workspace
        declares itself: a path any criterion names stays measured, and the declaration
        can never exclude itself. Together they mean an executor cannot put its own
        writes out of sight, because the scope clause passes its own allowed-path list in
        as protected and an edit to the declaration is always visible.
        """
        service = WorkspaceAcceptanceService()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            # A declaration that tries to hide the source, the scope, and itself.
            (root / ".gitignore").write_text("src/\n*.tsx\n.gitignore\nfixtures/seed.db\n", encoding="utf-8")
            (root / "src").mkdir()
            (root / "src" / "App.tsx").write_text("export const App = () => <Routes />;\n", encoding="utf-8")
            (root / "fixtures").mkdir()
            (root / "fixtures" / "seed.db").write_bytes(b"a-seeded-fixture-is-a-deliverable")
            (root / "notes.md").write_text("generated notes\n", encoding="utf-8")
            criteria = [
                {"criterion_id": "scope", "evaluator": {"type": "changed_files_subset", "paths": ["src/App.tsx"]}},
                {"criterion_id": "seed", "evaluator": {"type": "all_of", "checks": [
                    {"type": "paths_exist", "paths": ["fixtures/seed.db"]},
                ]}},
            ]
            protected = service.measured_paths(criteria)
            snapshot = service.snapshot(root, protected=protected)
            unprotected = service.snapshot(root)

        # Everything the contract names is measured, whatever the declaration says.
        self.assertIn("src/App.tsx", snapshot, "A path the scope clause polices must stay visible to it.")
        self.assertIn("fixtures/seed.db", snapshot, "A seeded fixture a criterion names is a deliverable, not an artifact.")
        self.assertEqual(protected, {"src/App.tsx", "fixtures/seed.db"})
        # The declaration is measured even when it excludes itself by name.
        self.assertIn(".gitignore", snapshot)
        self.assertIn(".gitignore", unprotected)
        # A file the declaration says nothing about is measured, declaration or no.
        self.assertIn("notes.md", snapshot)
        # And without protection the declaration is obeyed to the letter, which is
        # exactly why protection has to exist.
        self.assertEqual(sorted(unprotected), [".gitignore", "notes.md"])

    def test_a_workspace_that_declares_nothing_still_excludes_universal_artifacts(self):
        """The floor TEMM owns, for a project with no declaration of its own.

        A missing or unreadable `.gitignore` must not be an error and must not leave
        caches and compiled output counted as authored work - and it must not exclude
        source either, which is why the floor names only build and runtime output.
        """
        service = WorkspaceAcceptanceService()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "src").mkdir()
            (root / "src" / "app.py").write_text("value = 1\n", encoding="utf-8")
            (root / "src" / "__pycache__").mkdir()
            (root / "src" / "__pycache__" / "app.cpython-312.pyc").write_bytes(b"\x00compiled")
            (root / "server.log").write_text("listening on 8000\n", encoding="utf-8")
            (root / "var").mkdir()
            (root / "var" / "state.sqlite3").write_bytes(b"sqlite")
            (root / "README.md").write_text("# Real documentation\n", encoding="utf-8")
            snapshot = service.snapshot(root)
            census = service.artifact_census(root)

        self.assertEqual(sorted(snapshot), ["README.md", "src/app.py"])
        self.assertEqual(census["files_measured"], 2)
        self.assertEqual(census["generated_excluded"], 3)
        self.assertIsNone(census["declaration"], "There was nothing to read, and that is not an error.")

    def test_process_success_does_not_imply_acceptance_success(self):
        process_status = "completed"
        all_satisfied = False
        status = "completed" if process_status == "completed" and all_satisfied else "failed" if process_status == "completed" else process_status
        self.assertEqual(status, "failed")

    def test_progress_is_persisted_and_only_unsatisfied_work_remains_pending(self):
        service = WorkspaceAcceptanceService()
        criteria = [{"criterion_id": "a", "description": "A"}, {"criterion_id": "b", "description": "B"}]
        progress = service.merge_progress(criteria, [{"criterion_id": "a", "status": "passed", "evidence": {"path": "a"}}, {"criterion_id": "b", "status": "failed", "evidence": {"path": "b"}}])
        self.assertEqual(progress[0]["last_status"], "passed")
        self.assertEqual([item["criterion_id"] for item in progress if item["last_status"] != "passed"], ["b"])

    def test_exact_content_requires_real_file_content(self):
        service = WorkspaceAcceptanceService()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            criterion = {"criterion_id": "exact", "evaluator": {"type": "file_exact_content", "path": "proof.txt", "content": "OK"}}
            missing = service.evaluate(root, [criterion])
            (root / "proof.txt").write_text("OK", encoding="utf-8")
            present = service.evaluate(root, [criterion])
        self.assertEqual(missing[0]["status"], "failed")
        self.assertEqual(present[0]["status"], "passed")

    def test_python_syntax_and_deliverable_surface_require_real_artifacts(self):
        service = WorkspaceAcceptanceService()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "broken.py").write_text("def incomplete(\n", encoding="utf-8")
            (root / "index.html").write_text("<html>Placeholder</html>", encoding="utf-8")
            criteria = [
                {"criterion_id": "syntax", "evaluator": {"type": "python_syntax_valid", "path": "broken.py"}},
                {"criterion_id": "surface", "evaluator": {"type": "deliverable_surface", "paths": ["index.html"], "surface_type": "frontend", "min_chars": 100, "required_any": ["login", "dashboard"]}},
            ]
            failed = service.evaluate(root, criteria)
            (root / "broken.py").write_text("def complete():\n    return True\n", encoding="utf-8")
            (root / "index.html").write_text("<nav>Navigation</nav><main><h1>Dashboard</h1><form>Login</form></main>" * 4, encoding="utf-8")
            passed = service.evaluate(root, criteria)
        self.assertEqual([item["status"] for item in failed], ["failed", "failed"])
        self.assertEqual([item["status"] for item in passed], ["passed", "passed"])


    def test_real_module_is_not_placeholder_for_containing_ordinary_words(self):
        service = WorkspaceAcceptanceService()
        # "latest" and "resample" embed placeholder indicators as substrings, and a
        # real screen legitimately renders a `data-testid`. Substring matching made
        # such a file permanently unacceptable, so the contract could never be met.
        real = (
            "import { useEffect, useState } from 'react';\n"
            "export function Dashboard() {\n"
            "  const [latest, setLatest] = useState([]);\n"
            "  useEffect(() => { fetch('/api/dashboard').then((r) => r.json()).then(setLatest); }, []);\n"
            "  return <section data-testid=\"dashboard\">{latest.length} orders resampled</section>;\n"
            "}\n"
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "Dashboard.tsx").write_text(real, encoding="utf-8")
            (root / "Stub.tsx").write_text("export const Stub = () => <div>TODO: build this</div>;\n", encoding="utf-8")
            (root / "Comments.tsx").write_text("// Feature screens mount here.\n/* nothing yet */\n", encoding="utf-8")
            criteria = [
                {"criterion_id": "real", "evaluator": {"type": "deliverable_surface", "path": "Dashboard.tsx", "min_chars": 100, "required_any": ["dashboard"]}},
                {"criterion_id": "stub", "evaluator": {"type": "deliverable_surface", "path": "Stub.tsx"}},
                {"criterion_id": "comments", "evaluator": {"type": "deliverable_surface", "path": "Comments.tsx"}},
            ]
            results = service.evaluate(root, criteria)
        self.assertEqual([item["status"] for item in results], ["passed", "failed", "failed"])

    def test_tiny_stub_vocabulary_still_fails_the_surface_check(self):
        service = WorkspaceAcceptanceService()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "app.js").write_text("const foo = 1;\nexport default foo;\n", encoding="utf-8")
            results = service.evaluate(root, [{"criterion_id": "stub", "evaluator": {"type": "deliverable_surface", "path": "app.js"}}])
        self.assertEqual(results[0]["status"], "failed")
        self.assertEqual(results[0]["evidence"]["reason"], "Placeholder content")

    def test_form_fields_are_not_stubs_for_naming_the_placeholder_attribute(self):
        service = WorkspaceAcceptanceService()
        # `placeholder` is a standard HTML attribute and React prop, so every real
        # screen with a search box or select names it. Condemning the word outright
        # made the surface contract unsatisfiable for a 23KB orders page whose only
        # offence was three finished form fields.
        real = (
            "import { useState } from 'react';\n"
            "export function OrdersPage() {\n"
            "  const [search, setSearch] = useState('');\n"
            "  return (\n"
            "    <section>\n"
            "      <h1>Orders</h1>\n"
            "      <input value={search} onChange={(e) => setSearch(e.target.value)}\n"
            "        placeholder=\"Customer name or order id\" />\n"
            "      <FormSelect label=\"Customer\" placeholder=\"Select a customer\" options={options} />\n"
            "      <button onClick={() => fetch('/api/orders', { method: 'POST' })}>Create</button>\n"
            "    </section>\n"
            "  );\n"
            "}\n"
        )
        prose = "export const OrdersPage = () => <div>Placeholder screen</div>;\n"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "Real.tsx").write_text(real, encoding="utf-8")
            (root / "Prose.tsx").write_text(prose, encoding="utf-8")
            (root / "Comment.tsx").write_text(
                "// placeholder until the real screen lands\nexport const P = () => <div>{rows.length} orders</div>;\n",
                encoding="utf-8",
            )
            criteria = [
                {"criterion_id": "real", "evaluator": {"type": "deliverable_surface", "path": "Real.tsx", "min_chars": 300, "required_any": ["/api/orders"]}},
                {"criterion_id": "prose", "evaluator": {"type": "deliverable_surface", "path": "Prose.tsx"}},
                {"criterion_id": "comment", "evaluator": {"type": "deliverable_surface", "path": "Comment.tsx"}},
            ]
            results = service.evaluate(root, criteria)
        self.assertEqual([item["status"] for item in results], ["passed", "failed", "failed"])

    def test_placeholder_identifier_positions_are_all_read_as_code(self):
        service = WorkspaceAcceptanceService()
        # Each of these is the attribute being used, not unfinished work declared.
        for usage in (
            'placeholder="Search"',
            "placeholder: 'Search'",
            "placeholder?: string",
            "const { placeholder } = props",
            "props.placeholder",
            't("placeholder")',
            "setPlaceholder(value)",
            "renderPlaceholder(row)",
            "<Input placeholder={label} />",
        ):
            with self.subTest(usage=usage):
                self.assertFalse(service._is_placeholder_content(f"export function Screen() {{ return <form>{usage}</form>; }}"))
        for marker in ("// Placeholder for the real screen", "<div>PLACEHOLDER</div>", "<p>Placeholder.</p>"):
            with self.subTest(marker=marker):
                self.assertTrue(service._is_placeholder_content(f"export function Screen() {{ {marker} }}"))

    @staticmethod
    def _react_app(root: Path) -> None:
        """A minimal but real Vite app: entry, shell, and one wired screen."""
        (root / "package.json").write_text('{"name": "app", "private": true}', encoding="utf-8")
        (root / "src" / "pages").mkdir(parents=True)
        (root / "src" / "main.tsx").write_text(
            'import { createRoot } from "react-dom/client";\nimport App from "./App";\n'
            'createRoot(document.getElementById("root")!).render(<App />);\n',
            encoding="utf-8",
        )
        (root / "src" / "App.tsx").write_text(
            'import { useState } from "react";\nimport ProductsPage from "./pages/ProductsPage";\n'
            'export default function App() {\n  const [section] = useState("products");\n'
            '  return <main>{section === "products" ? <ProductsPage /> : null}</main>;\n}\n',
            encoding="utf-8",
        )
        screen = (
            'import { useEffect, useState } from "react";\n'
            "export default function NAME() {\n"
            "  const [rows, setRows] = useState([]);\n"
            '  useEffect(() => { fetch("/api/SLUG").then((r) => r.json()).then(setRows); }, []);\n'
            "  return (<section><h1>NAME</h1><table><tbody>{rows.map((row) => (\n"
            "    <tr key={row.id}><td>{row.name}</td><td>{row.quantity}</td></tr>))}</tbody></table>\n"
            '    <form onSubmit={() => fetch("/api/SLUG", { method: "POST" })}>\n'
            '      <input name="items" /><input name="quantity" /><button>Save</button></form></section>);\n}\n'
        )
        (root / "src" / "pages" / "ProductsPage.tsx").write_text(screen.replace("NAME", "ProductsPage").replace("SLUG", "products"), encoding="utf-8")
        (root / "src" / "pages" / "OrdersPage.tsx").write_text(screen.replace("NAME", "OrdersPage").replace("SLUG", "orders"), encoding="utf-8")

    @staticmethod
    def _barrelled_screen(root: Path) -> None:
        """The production layout: the shell imports its screen through an alias.

        `pages/CustomersPage.tsx` forwards to `pages/CustomerPage.tsx` and holds
        nothing else. It is the path the contract names and the path the application
        imports, so it is load-bearing - not a file written to satisfy a check.
        """
        (root / "src" / "App.tsx").write_text(
            'import { CustomersPage } from "./pages/CustomersPage";\n'
            "export default function App() {\n  return <main><CustomersPage /></main>;\n}\n",
            encoding="utf-8",
        )
        (root / "src" / "pages" / "CustomerPage.tsx").write_text(
            'import { useEffect, useMemo, useState } from "react";\n'
            "const COLUMNS = [\n"
            + "".join(
                f'  {{ key: "{name}", label: "{name.title()}", sortable: true, width: 160 }},\n'
                for name in ("name", "email", "phone", "company", "city", "country", "created", "updated", "status", "owner")
            )
            + "];\n"
            "export function CustomersPage() {\n"
            "  const [rows, setRows] = useState([]);\n"
            '  const [query, setQuery] = useState("");\n'
            '  useEffect(() => { fetch("/api/customers").then((response) => response.json()).then(setRows); }, []);\n'
            "  const shown = useMemo(() => rows.filter((row) =>\n"
            "    row.name.toLowerCase().includes(query.toLowerCase()) ||\n"
            "    row.email.toLowerCase().includes(query.toLowerCase()) ||\n"
            "    row.phone.includes(query)), [rows, query]);\n"
            '  const save = (body) => fetch("/api/customers", { method: "POST", body: JSON.stringify(body) });\n'
            "  return (<section><h1>Customers</h1>\n"
            '    <input aria-label="search customers" value={query} onChange={(event) => setQuery(event.target.value)} />\n'
            "    <table><thead><tr>{COLUMNS.map((column) => (<th key={column.key}>{column.label}</th>))}</tr></thead>\n"
            "    <tbody>{shown.map((row) => (<tr key={row.id}>\n"
            "      <td>{row.name}</td><td>{row.email}</td><td>{row.phone}</td></tr>))}</tbody></table>\n"
            "    <form onSubmit={(event) => { event.preventDefault(); save({ name: query }); }}>\n"
            '      <input name="name" /><input name="email" /><input name="phone" /><button>Save</button></form>\n'
            "  </section>);\n}\n"
            "export default CustomersPage;\n",
            encoding="utf-8",
        )
        (root / "src" / "pages" / "CustomersPage.tsx").write_text(
            'export { default, CustomersPage } from "./CustomerPage";\n', encoding="utf-8",
        )

    def test_a_screen_delivered_behind_a_re_export_is_measured_where_it_lives(self):
        """Defect #63: a re-export has no substance of its own to measure.

        Every symbol an importer receives from a barrel is defined elsewhere, so
        reading the forwarding line to judge a clause about a screen measures the
        wrong file - and measures it as empty, because forwarding is all it does.

        Production evidence 2026-08-21: `task-234c939b0fe9` executed genuinely - 72
        tool uses, 3.59M tokens, all three engineering gates green, eight files
        changed - and failed `customers:screen` (min_chars 1500, required_any
        `/api/customers`) and `customers:search` (contains `search`) because
        `frontend/src/pages/CustomersPage.tsx` was 57 bytes of
        `export { default, CustomersPage } from "./CustomerPage";` while the screen
        those clauses describe sat in the 18,232 bytes of `CustomerPage.tsx` beside it,
        with `/api/customers` present and `search` 27 times over. `App.tsx` imported
        `CustomersPage` through the barrel and rendered it, so the work was delivered,
        wired, and reachable, and acceptance called it absent.
        """
        service = WorkspaceAcceptanceService()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._react_app(root)
            self._barrelled_screen(root)
            barrel_bytes = (root / "src" / "pages" / "CustomersPage.tsx").stat().st_size
            results = service.evaluate(root, [
                {"criterion_id": "customers:screen", "evaluator": {"type": "deliverable_surface", "path": "src/pages/CustomersPage.tsx", "min_chars": 1500, "required_any": ["/api/customers"]}},
                {"criterion_id": "customers:search", "evaluator": {"type": "path_exists_contains", "path": "src/pages/CustomersPage.tsx", "contains": ["search"]}},
            ])
        screen, search = results
        self.assertLess(barrel_bytes, 100, "The contracted file must be the tiny forwarder the defect turned on.")
        self.assertEqual(screen["status"], "passed", "A delivered, wired, reachable screen must satisfy the clause its module satisfies.")
        self.assertEqual(search["status"], "passed", "`search` is in the module the barrel forwards to, 27 times in production.")
        # The receipt names both files, so nothing appears to have been found in a
        # file that does not contain it.
        self.assertEqual(screen["evidence"]["files"], ["src/pages/CustomersPage.tsx"])
        self.assertEqual(screen["evidence"]["measured_files"], ["src/pages/CustomerPage.tsx"])
        self.assertEqual(screen["evidence"]["resolved_through_reexport"], ["src/pages/CustomerPage.tsx"])
        self.assertGreaterEqual(screen["evidence"]["content_length"], 1500)
        self.assertEqual(search["evidence"]["resolved_through_reexport"], ["src/pages/CustomerPage.tsx"])
        # Reachability is still judged on the contracted path, because that is the
        # module the application imports - resolution moves where substance is read,
        # not what counts as wired.
        self.assertEqual(screen["evidence"]["reachability"]["status"], "reachable")

    def test_re_export_resolution_finds_substance_and_never_manufactures_it(self):
        """The resolution moves where a clause is measured; it never lowers the bar.

        Three cases that must not pass. An alias to a module that lacks the substance
        fails on the substance, which is the point: the target has to contain what the
        clause requires, and a forwarder contributes not one character toward it. A
        file with a declaration of its own is measured as itself, because that
        declaration is work the clause was asking about. An aggregator forwarding to
        several modules is measured as itself too, having no single module to be
        measured in. Every ambiguity resolves toward the contracted path.
        """
        service = WorkspaceAcceptanceService()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._react_app(root)
            self._barrelled_screen(root)
            pages = root / "src" / "pages"
            (pages / "Hollow.tsx").write_text("export const Hollow = () => null;\n", encoding="utf-8")
            (pages / "EmptyAlias.tsx").write_text('export * from "./Hollow";\n', encoding="utf-8")
            (pages / "OwnWork.tsx").write_text('export * from "./CustomerPage";\nexport const extra = 1;\n', encoding="utf-8")
            (pages / "Aggregate.tsx").write_text('export * from "./CustomerPage";\nexport * from "./Hollow";\n', encoding="utf-8")
            results = service.evaluate(root, [
                {"criterion_id": "hollow", "evaluator": {"type": "path_exists_contains", "path": "src/pages/EmptyAlias.tsx", "contains": ["/api/customers"]}},
                {"criterion_id": "own", "evaluator": {"type": "path_exists_contains", "path": "src/pages/OwnWork.tsx", "contains": ["/api/customers"]}},
                {"criterion_id": "aggregate", "evaluator": {"type": "path_exists_contains", "path": "src/pages/Aggregate.tsx", "contains": ["/api/customers"]}},
            ])
        hollow, own, aggregate = results
        # The mechanism fired here and the clause still failed, which is the whole
        # argument that this is a resolution and not a relaxation.
        self.assertEqual(hollow["status"], "failed", "Resolving to a module that lacks the substance must still fail.")
        self.assertEqual(hollow["evidence"]["resolved_through_reexport"], ["src/pages/Hollow.tsx"])
        self.assertEqual(own["status"], "failed", "A file with work of its own is the file the clause asked about.")
        self.assertNotIn("resolved_through_reexport", own["evidence"])
        self.assertEqual(aggregate["status"], "failed", "An aggregator has no single module to be measured in.")
        self.assertNotIn("resolved_through_reexport", aggregate["evidence"])

    def test_a_screen_nothing_imports_has_not_delivered_a_surface(self):
        """A surface is what a user can open, so acceptance must walk the graph.

        Production evidence 2026-08-19: NEXA's `OrdersPage.tsx` - 23KB, a complete
        multi-item order workflow against a live `/api/orders` client - satisfied
        every criterion of its requirement while being imported by exactly zero
        files. `App.tsx` rendered dashboard and products only. The requirement stood
        one acceptance away from complete, and the browser step that opens the orders
        screen would have failed outright.
        """
        service = WorkspaceAcceptanceService()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._react_app(root)
            criteria = [
                {"criterion_id": "orders:screen", "evaluator": {"type": "deliverable_surface", "path": "src/pages/OrdersPage.tsx", "min_chars": 300, "required_any": ["/api/orders"]}},
                {"criterion_id": "products:screen", "evaluator": {"type": "deliverable_surface", "path": "src/pages/ProductsPage.tsx", "min_chars": 300, "required_any": ["/api/products"]}},
            ]
            results = service.evaluate(root, criteria)
        orders, products = results
        self.assertEqual(orders["status"], "failed", "An unreachable screen is written, not delivered.")
        self.assertEqual(orders["evidence"]["reachability"]["status"], "unreachable")
        self.assertEqual(orders["evidence"]["reachability"]["entry_points"], ["src/main.tsx"])
        self.assertEqual(products["status"], "passed", "The wired screen is delivered and must still pass.")
        self.assertEqual(products["evidence"]["reachability"]["status"], "reachable")

    def test_reachable_modules_exposes_the_shell_a_repair_must_wire_into(self):
        """The shell is where an orphan surface gets wired, so a repair must see it.

        When `deliverable_surface` fails only because a screen is unreachable, the
        repair TEMM raises can fix it only by importing the screen from a module the
        entry point already reaches (here `src/App.tsx`). `reachable_modules` names
        exactly that graph so the repair's write scope can include it; the orphan
        target itself is absent, because editing it cannot make it reachable.
        """
        service = WorkspaceAcceptanceService()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._react_app(root)
            shell = service.reachable_modules(root, [root / "src" / "pages" / "OrdersPage.tsx"])
        self.assertEqual(
            sorted(shell),
            ["src/App.tsx", "src/main.tsx", "src/pages/ProductsPage.tsx"],
        )
        self.assertIn("src/App.tsx", shell)
        self.assertNotIn("src/pages/OrdersPage.tsx", shell)

    def test_wiring_the_screen_is_what_turns_the_criterion_green(self):
        """The same file, unchanged, passes once the shell renders it.

        Whether a surface is delivered has to hinge on the wiring alone, or the
        repair task TEMM raises from the failure cannot be shown to have fixed it.
        """
        service = WorkspaceAcceptanceService()
        criterion = {"criterion_id": "orders:screen", "evaluator": {"type": "deliverable_surface", "path": "src/pages/OrdersPage.tsx", "min_chars": 300, "required_any": ["/api/orders"]}}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._react_app(root)
            before = service.evaluate(root, [criterion])[0]
            app = root / "src" / "App.tsx"
            app.write_text(
                app.read_text(encoding="utf-8")
                .replace('import ProductsPage from "./pages/ProductsPage";', 'import ProductsPage from "./pages/ProductsPage";\nimport OrdersPage from "./pages/OrdersPage";')
                .replace("<ProductsPage /> : null", "<ProductsPage /> : <OrdersPage />"),
                encoding="utf-8",
            )
            after = service.evaluate(root, [criterion])[0]
        self.assertEqual(before["status"], "failed")
        self.assertEqual(after["status"], "passed")
        self.assertEqual(after["evidence"]["reachability"]["module"], "src/pages/OrdersPage.tsx")

    def test_every_import_form_that_wires_a_screen_is_followed(self):
        """Lazy routes, barrel re-exports, path aliases, and Vite's directory import.

        Each of these is how real applications wire screens. A graph walk that only
        understood `import X from "./X"` would call finished work unreachable and make
        the contract unsatisfiable - the same failure mode as the placeholder pattern
        that condemned every form-bearing screen.
        """
        service = WorkspaceAcceptanceService()
        body = 'export default function S() { return <form><input name="q" placeholder="Search" />{fetch("/api/x")}</form>; }\n' + "// padding for the size floor\n" * 12
        for label, entry in (
            ("dynamic import", 'const Screen = lazy(() => import("./pages/Screen"));\n'),
            ("barrel re-export", 'export * from "./pages";\n'),
            ("path alias", 'import Screen from "@/pages/Screen";\n'),
            ("directory glob", 'const routes = import.meta.glob("./pages/*.tsx");\n'),
        ):
            with self.subTest(label=label):
                with tempfile.TemporaryDirectory() as directory:
                    root = Path(directory)
                    (root / "package.json").write_text('{"name": "app"}', encoding="utf-8")
                    (root / "src" / "pages").mkdir(parents=True)
                    (root / "src" / "main.tsx").write_text(entry, encoding="utf-8")
                    (root / "src" / "pages" / "index.ts").write_text('export { default } from "./Screen";\n', encoding="utf-8")
                    (root / "src" / "pages" / "Screen.tsx").write_text(body, encoding="utf-8")
                    result = service.evaluate(root, [{"criterion_id": "s", "evaluator": {"type": "deliverable_surface", "path": "src/pages/Screen.tsx", "min_chars": 200}}])[0]
                self.assertEqual(result["status"], "passed", f"{label} wires the screen and must be followed")

    def test_python_surfaces_are_reached_through_their_own_import_graph(self):
        """The defect is not specific to one ecosystem, so neither is the fix."""
        service = WorkspaceAcceptanceService()
        body = 'def render(request):\n    return {"rows": fetch("/api/orders")}\n' + "# padding for the size floor\n" * 12
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "pyproject.toml").write_text('[project]\nname = "app"\n', encoding="utf-8")
            (root / "screens").mkdir()
            (root / "screens" / "__init__.py").write_text("", encoding="utf-8")
            (root / "main.py").write_text("from screens import products\n\nproducts.render(None)\n", encoding="utf-8")
            (root / "screens" / "products.py").write_text(body, encoding="utf-8")
            (root / "screens" / "orders.py").write_text(body, encoding="utf-8")
            results = service.evaluate(root, [
                {"criterion_id": "products", "evaluator": {"type": "deliverable_surface", "path": "screens/products.py", "min_chars": 200}},
                {"criterion_id": "orders", "evaluator": {"type": "deliverable_surface", "path": "screens/orders.py", "min_chars": 200}},
            ])
        self.assertEqual([item["status"] for item in results], ["passed", "failed"])
        self.assertEqual(results[1]["evidence"]["reachability"]["status"], "unreachable")

    def test_reachability_is_not_judged_where_the_workspace_cannot_answer_it(self):
        """No entry point, or a candidate that is itself the entry, decides nothing.

        A criterion naming an `index.html`, or a directory of loose files with nothing
        that starts, must be judged exactly as it was before: inventing a verdict from
        a graph that does not exist would fail real deliverables for the shape of the
        workspace around them.
        """
        service = WorkspaceAcceptanceService()
        body = 'export default function S() { return <div>{fetch("/api/x")}</div>; }\n' + "// padding\n" * 12
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "Loose.tsx").write_text(body, encoding="utf-8")
            (root / "index.html").write_text("<!doctype html><html><body><div id=root>dashboard</div></body></html>", encoding="utf-8")
            results = service.evaluate(root, [
                {"criterion_id": "loose", "evaluator": {"type": "deliverable_surface", "path": "Loose.tsx", "min_chars": 200}},
                {"criterion_id": "page", "evaluator": {"type": "deliverable_surface", "path": "index.html", "surface_type": "frontend", "min_chars": 40, "required_any": ["dashboard"]}},
            ])
        self.assertEqual([item["status"] for item in results], ["passed", "passed"])
        self.assertEqual(results[0]["evidence"]["reachability"]["reason"], "No application entry point found")
        self.assertEqual(results[1]["evidence"]["reachability"]["reason"], "No source module among the candidates")

    @staticmethod
    def _express_backend(root: Path) -> None:
        """A backend with a real suite: entry, app, one route, and tests beside them.

        Shaped after the NEXA workspace the defect was found in - `src/index.ts`
        starting `src/app.ts`, and `src/tests/` holding a collected test, a helper it
        imports, and a file nothing loads.
        """
        backend = root / "backend"
        (backend / "src" / "routes").mkdir(parents=True)
        (backend / "src" / "tests").mkdir(parents=True)
        (backend / "node_modules" / "vitest").mkdir(parents=True)
        (backend / "package.json").write_text('{"name": "backend", "private": true}', encoding="utf-8")
        (backend / "src" / "index.ts").write_text('import { app } from "./app";\napp.listen(3000);\n', encoding="utf-8")
        (backend / "src" / "app.ts").write_text(
            'import express from "express";\nimport { orders } from "./routes/orders";\n'
            "export const app = express();\napp.use(\"/api/orders\", orders);\n",
            encoding="utf-8",
        )
        (backend / "src" / "routes" / "orders.ts").write_text(
            'import { Router } from "express";\nexport const orders = Router();\n'
            "orders.post(\"/\", (req, res) => res.json({ total: 0, stock: 17 }));\n" + "// padding\n" * 12,
            encoding="utf-8",
        )
        # A published package ships its own tests; they are not this project's suite.
        (backend / "node_modules" / "vitest" / "self.test.ts").write_text("it(\"works\", () => {});\n", encoding="utf-8")
        (backend / "src" / "tests" / "orders.test.ts").write_text(
            'import { describe, expect, it } from "vitest";\nimport { app } from "../app";\n'
            'import { seedProduct } from "./factory";\n'
            'describe("orders", () => {\n  it("totals the order and decrements stock from 20 to 17", async () => {\n'
            "    const product = await seedProduct({ stock: 20, price: 5 });\n"
            "    const order = await request(app).post(\"/api/orders\").send({ items: [{ id: product.id, quantity: 3 }] });\n"
            "    expect(order.body.total).toBe(15);\n    expect(order.body.stock).toBe(17);\n  });\n});\n"
            + "// padding\n" * 12,
            encoding="utf-8",
        )
        (backend / "src" / "tests" / "factory.ts").write_text(
            'import { app } from "../app";\nexport async function seedProduct(input: { stock: number; price: number }) {\n'
            "  return { id: \"p1\", ...input, stock: input.stock };\n}\n" + "// padding\n" * 12,
            encoding="utf-8",
        )
        (backend / "src" / "tests" / "notes.ts").write_text(
            "export const NOTES = \"scratch nobody loads\";\n" + "// padding\n" * 30, encoding="utf-8",
        )
        (backend / "src" / "routes" / "inventory.ts").write_text(
            'import { Router } from "express";\nexport const inventory = Router();\n'
            "inventory.get(\"/\", (req, res) => res.json({ stock: 17 }));\n" + "// padding\n" * 12,
            encoding="utf-8",
        )

    def _surface(self, root: Path, path_value: str, **extra):
        """Evaluate one reachability-bearing `deliverable_surface` over this path."""
        evaluator = {"type": "deliverable_surface", "path": path_value, "min_chars": 200, **extra}
        return WorkspaceAcceptanceService().evaluate(root, [{"criterion_id": path_value, "evaluator": evaluator}])[0]

    def test_a_test_the_runner_runs_has_delivered_its_proof(self):
        """The runner is an entry point, so a test is judged by the graph that loads it.

        Production evidence 2026-08-21, attempt-18a944ee9c04: a 347-second, 2.08M-token
        run wrote `backend/src/tests/orders.test.ts` - 12886 characters proving an order
        totals correctly and takes stock from 20 to 17 - and the criterion failed on
        reachability alone, because the walk began at `backend/src/index.ts` and
        `backend/src/app.ts` and no application imports its own tests. Stated as
        something an executor could satisfy, the criterion asked for production code to
        import a test file. It was unsatisfiable by construction, and each attempt at it
        cost another run of that size.
        """
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._express_backend(root)
            proof = self._surface(root, "backend/src/tests/orders.test.ts", required_any=["stock"])
        reach = proof["evidence"]["reachability"]
        self.assertEqual(proof["status"], "passed", "A test the suite runs is delivered work.")
        self.assertEqual(reach["status"], "reachable")
        self.assertEqual(reach["entry_kind"], "test_runner", "Nothing in the application imports it, and nothing should.")
        self.assertEqual(reach["module"], "backend/src/tests/orders.test.ts")
        self.assertEqual(reach["entry_points"], ["backend/src/tests/orders.test.ts"], "A dependency's own suite is not this project's.")

    def test_a_test_helper_is_reached_through_the_test_that_imports_it(self):
        """Beside the tests is not the same as loaded: one of them has to import it."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._express_backend(root)
            helper = self._surface(root, "backend/src/tests/factory.ts")
            unused = self._surface(root, "backend/src/tests/notes.ts")
        self.assertEqual(helper["status"], "passed")
        self.assertEqual(helper["evidence"]["reachability"]["entry_kind"], "test_runner")
        self.assertEqual(unused["status"], "failed", "A file in the tests directory that no test loads is not run.")
        self.assertEqual(unused["evidence"]["reachability"]["status"], "unreachable")

    def test_a_suite_on_disk_does_not_make_orphaned_application_code_reachable(self):
        """The relaxation is for tests only; defect #23 stands for everything else."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._express_backend(root)
            orphan = self._surface(root, "backend/src/routes/inventory.ts")
            wired = self._surface(root, "backend/src/routes/orders.ts")
        reach = orphan["evidence"]["reachability"]
        self.assertEqual(orphan["status"], "failed", "A route no application starts is still not delivered.")
        self.assertEqual(reach["status"], "unreachable")
        self.assertEqual(reach["entry_points"], ["backend/src/index.ts", "backend/src/app.ts"], "The runner was not asked about application code.")
        self.assertEqual(wired["status"], "passed")
        self.assertEqual(wired["evidence"]["reachability"]["entry_kind"], "application")

    def test_the_wiring_scope_for_a_test_surface_is_the_suite_that_would_load_it(self):
        """A repair wires a helper in from a test, and a collected test needs no wiring."""
        service = WorkspaceAcceptanceService()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._express_backend(root)
            helper_scope = service.reachable_modules(root, [root / "backend" / "src" / "tests" / "notes.ts"])
            collected_scope = service.reachable_modules(root, [root / "backend" / "src" / "tests" / "orders.test.ts"])
        application_shell = ["backend/src/app.ts", "backend/src/index.ts", "backend/src/routes/orders.ts"]
        self.assertIn("backend/src/tests/orders.test.ts", helper_scope, "The import edge can only come from a test the runner collects.")
        self.assertIn("backend/src/tests/factory.ts", helper_scope)
        self.assertNotIn("backend/src/tests/notes.ts", helper_scope, "Editing the orphan cannot make the orphan reachable.")
        self.assertEqual(sorted(collected_scope), application_shell, "A collected test is already an entry point, so it widens nothing.")

    def test_an_author_can_state_that_a_surface_is_not_reached_by_import(self):
        """`require_reachable: false` for artifacts that are wired some other way."""
        service = WorkspaceAcceptanceService()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._react_app(root)
            evaluator = {"type": "deliverable_surface", "path": "src/pages/OrdersPage.tsx", "min_chars": 300, "required_any": ["/api/orders"]}
            opted_out = service.evaluate(root, [{"criterion_id": "o", "evaluator": {**evaluator, "require_reachable": False}}])[0]
        self.assertEqual(opted_out["status"], "passed")
        self.assertNotIn("reachability", opted_out["evidence"])


if __name__ == "__main__":
    unittest.main()
