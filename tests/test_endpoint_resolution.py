"""Defect #73: an endpoint criterion measured a literal string, not a request.

`deliverable_surface.required_any` means "this surface talks to that endpoint" and was
measured as "this file's text contains that string". Every frontend that factors its
base URL out breaks that equivalence, and it breaks in both directions at once.

Production evidence, NEXA project-23a514f0c426. The false negative:
`frontend/src/api/client.ts` holds `API_BASE = import.meta.env.VITE_API_URL ?? "/api"`
and composes `fetch(`${API_BASE}${path}`)`, so call sites name only tails - `"/auth/me"`,
`"/auth/login"`. The literal `/api/auth/me` exists nowhere in `frontend/src`, so no
screen can hold it without hardcoding a string it never uses. attempt-a267d4d0addd ran
342s over 52 tool uses, created `LoginPage.tsx` and `AuthProvider.tsx` reaching those
endpoints correctly through the shared client, touched every path its own run-focus
named, and failed both clauses on `matched: []`. The false positive: the one screen that
passed this family, `OrdersPage.tsx`, passed on a doc comment - "reuses the shared API
client for /api/orders" - while calling `api.listOrders()` like every other screen.
Working code failed the clause; prose passed it.

One fault, one reading: a clause is satisfied by the surface's own code, or by a module
its own import closure reaches, and comments count for nothing on either route. These
tests pin both faces, and - more importantly - pin the ways the reading must still say
no, because a match that cannot fail measures nothing either.
"""

import tempfile
import unittest
from pathlib import Path

from core.ai_fleet.services.workspace_acceptance import WorkspaceAcceptanceService

# A real client: base from the environment with a same-origin fallback, one composed
# fetch, and call sites that name only tails. This is the shape the defect was found on.
CLIENT = """const API_BASE = import.meta.env.VITE_API_URL ?? "/api";

export async function request(path, init) {
  const response = await fetch(`${API_BASE}${path}`, init);
  if (!response.ok) {
    throw new Error("request failed");
  }
  return await response.json();
}

export const api = {
  listActivities: (query) => request(`/activities${query ? `?${query}` : ""}`),
  login: (body) => request("/auth/login", { method: "POST", body }),
  currentUser: () => request("/auth/me"),
  listOrders: () => request("/orders"),
};
"""

SCREEN = """import { useEffect, useState } from "react";
import { api } from "../api/client";

export function ActivityPage() {
  const [items, setItems] = useState([]);
  useEffect(() => {
    api.listActivities("").then(setItems);
  }, []);
  return (
    <section>
      <h1>Activity</h1>
      <table>
        <tbody>
          {items.map((item) => (
            <tr key={item.id}>
              <td>{item.actor}</td>
              <td>{item.action}</td>
              <td>{item.entity}</td>
              <td>{item.createdAt}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}
"""


# The same screen with its client import removed. Fixtures about *which* module a
# closure reaches need bulk content that does not itself reach the client, or the walk
# under test is short-circuited and the test passes for the wrong reason.
BODY = SCREEN.replace('import { api } from "../api/client";\n', "").replace(
    'api.listActivities("").then(setItems);', "Promise.resolve([]).then(setItems);"
)


class EndpointResolutionTests(unittest.TestCase):
    def setUp(self):
        self.service = WorkspaceAcceptanceService()
        self.root = Path(tempfile.mkdtemp(prefix="ai-fleet-endpoint-"))

    def _write(self, relative: str, content: str) -> Path:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def _evaluate(self, relative: str, required_any: list[str], min_chars: int = 1, reachable: bool = False) -> dict:
        """One criterion, with reachability off unless a test is about reachability.

        Reachability is a separate gate with its own tests; leaving it on here would mean
        every fixture had to build an entry-point graph to say anything about clauses.
        """
        criterion = {
            "criterion_id": "surface",
            "evaluator": {
                "type": "deliverable_surface",
                "path": relative,
                "min_chars": min_chars,
                "required_any": required_any,
                "require_reachable": reachable,
            },
        }
        return self.service.evaluate(self.root, [criterion])[0]

    # --- the false negative the defect was found on -------------------------------

    def test_a_screen_that_reaches_the_endpoint_through_its_client_satisfies_the_clause(self):
        """The reproduction: attempt-a267d4d0addd's shape, one hop from screen to client."""
        self._write("frontend/src/api/client.ts", CLIENT)
        self._write("frontend/src/pages/ActivityPage.tsx", SCREEN)

        result = self._evaluate("frontend/src/pages/ActivityPage.tsx", ["/api/activities"])

        self.assertEqual(result["status"], "passed")
        resolution = result["evidence"]["required_any_resolution"]
        self.assertEqual(result["evidence"]["matched"], ["/api/activities"])
        self.assertEqual(resolution["unresolved"], [])
        self.assertEqual(
            resolution["grounds"],
            [{
                "clause": "/api/activities",
                "form": "composed",
                "scope": "import_closure",
                "module": "frontend/src/api/client.ts",
                "base": "/api",
                "tail": "/activities",
            }],
            "A receipt has to say how the clause was answered, not only that it was.",
        )

    def test_the_clause_resolves_through_a_context_provider_two_hops_out(self):
        """`LoginPage` -> `AuthProvider` -> `client`, which is how auth screens are built.

        A screen reaching its API through a hook or a provider is the common case, not an
        exotic one, so a one-hop-only closure would leave the defect in place for exactly
        the two criteria it was found on.
        """
        self._write("frontend/src/api/client.ts", CLIENT)
        self._write("frontend/src/auth/AuthProvider.tsx",
                    'import { api } from "../api/client";\nexport const useAuth = () => api;\n')
        self._write("frontend/src/pages/LoginPage.tsx",
                    'import { useAuth } from "../auth/AuthProvider";\nexport function LoginPage() { return useAuth(); }\n')

        result = self._evaluate("frontend/src/pages/LoginPage.tsx", ["/api/auth/login"])

        self.assertEqual(result["status"], "passed")
        ground = result["evidence"]["required_any_resolution"]["grounds"][0]
        self.assertEqual(ground["module"], "frontend/src/api/client.ts")
        self.assertEqual((ground["base"], ground["tail"]), ("/api", "/auth/login"))

    def test_a_client_that_writes_the_path_whole_is_read_as_a_literal_not_a_composition(self):
        """Not every client factors the base out, and the reading must not require it."""
        self._write("frontend/src/api/client.ts",
                    'export const load = () => fetch("/api/activities").then((r) => r.json());\n')
        self._write("frontend/src/pages/ActivityPage.tsx", SCREEN.replace("api.listActivities", "load"))

        result = self._evaluate("frontend/src/pages/ActivityPage.tsx", ["/api/activities"])

        self.assertEqual(result["status"], "passed")
        ground = result["evidence"]["required_any_resolution"]["grounds"][0]
        self.assertEqual(ground["form"], "literal")
        self.assertEqual(ground["scope"], "import_closure")

    def test_a_literal_in_the_surfaces_own_code_still_resolves_without_walking_anywhere(self):
        """The pre-existing path, unchanged - and reported as `surface`, not a closure."""
        self._write("backend/src/tests/acceptance.test.ts",
                    'it("creates an order", async () => {\n  await request(app).post("/api/orders").send({});\n});\n')

        result = self._evaluate("backend/src/tests/acceptance.test.ts", ["/api/orders"])

        self.assertEqual(result["status"], "passed")
        resolution = result["evidence"]["required_any_resolution"]
        self.assertEqual(resolution["scope"], "surface")
        self.assertEqual(resolution["grounds"], [{"clause": "/api/orders", "form": "literal", "scope": "surface"}])
        self.assertNotIn("closure_modules", resolution, "Nothing was walked, so nothing should be claimed about a closure.")

    # --- the false positive, the same fault seen from the other side ---------------

    def test_a_doc_comment_naming_the_endpoint_does_not_satisfy_the_clause(self):
        """`OrdersPage.tsx` passed this family on line 9 of its header comment.

        The screen called `api.listOrders()` like every other screen; the only occurrence
        of the literal in the file was prose about the file. Prose is not a request.
        """
        self._write("frontend/src/pages/OrdersPage.tsx",
                    "/**\n * The page reuses the shared API client for /api/orders and /api/customers.\n */\n"
                    "export function OrdersPage() {\n  return null;\n}\n")

        result = self._evaluate("frontend/src/pages/OrdersPage.tsx", ["/api/orders"])

        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["evidence"]["matched"], [])

    def test_a_comment_inside_a_closure_module_does_not_satisfy_it_either(self):
        """Otherwise the fix would trade a comment on the surface for one a hop away."""
        self._write("frontend/src/api/client.ts",
                    'const API_BASE = "/api";\n// this client will eventually call /api/activities\nexport const api = {};\n')
        self._write("frontend/src/pages/ActivityPage.tsx", SCREEN)

        result = self._evaluate("frontend/src/pages/ActivityPage.tsx", ["/api/activities"])

        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["evidence"]["required_any_resolution"]["unresolved"], ["/api/activities"])

    def test_substance_is_still_sized_on_the_file_as_written(self):
        """Comments are stripped for clause matching only.

        `min_chars` asks whether a real file was authored, and a licence header or a
        documented module is authored content. Stripping there would fail files for being
        documented, which is a different and worse defect.
        """
        commented = "/**\n" + (" * documentation line\n" * 40) + " */\n" + CLIENT
        self._write("frontend/src/api/client.ts", commented)
        self._write("frontend/src/pages/ActivityPage.tsx", SCREEN)

        result = self._evaluate("frontend/src/pages/ActivityPage.tsx", ["/api/activities"])
        surface = self._evaluate("frontend/src/api/client.ts", ["/api/activities"])

        self.assertEqual(result["status"], "passed")
        self.assertEqual(surface["evidence"]["content_length"], len(commented))

    # --- the ways it must still say no --------------------------------------------

    def test_a_short_tail_cannot_be_read_out_of_a_longer_word(self):
        """`/me` must not be found inside `"/members"`.

        This delimiter is what makes inferring a tail safe at all. Without it the split
        degenerates into substring matching with extra steps, and any short endpoint
        would be satisfied by an unrelated longer one.
        """
        self._write("frontend/src/api/client.ts",
                    'const API_BASE = "/api";\nexport const listMembers = () => fetch(API_BASE + "/members");\n')
        self._write("frontend/src/pages/TeamPage.tsx",
                    'import { listMembers } from "../api/client";\nexport const TeamPage = () => listMembers();\n')

        self.assertEqual(self._evaluate("frontend/src/pages/TeamPage.tsx", ["/api/me"])["status"], "failed")

        # Positive control in the same shape, so the test proves a delimiter rule and not
        # a client the reading simply cannot read.
        self._write("frontend/src/api/client.ts",
                    'const API_BASE = "/api";\nexport const listMembers = () => fetch(API_BASE + "/me");\n')
        self.assertEqual(self._evaluate("frontend/src/pages/TeamPage.tsx", ["/api/me"])["status"], "passed")

    def test_a_clause_that_is_not_a_request_path_is_never_answered_from_the_closure(self):
        """`shell:surface` requires `route` in `App.tsx`, and means App.tsx.

        A bare word is a statement about the contracted file. Resolving it outward would
        pass a shell with no routing because something it imports mentions a route, which
        is the false positive this defect is about, reintroduced one hop away. The
        measured fault is entirely in request paths and the widening stops there.
        """
        self._write("frontend/src/nav/Shell.tsx",
                    "export const menu = [];\nexport function route(name) { return name; }\n")
        self._write("frontend/src/App.tsx", 'import { menu } from "./nav/Shell";\n' + BODY)
        self.assertNotIn("route", (self.root / "frontend/src/App.tsx").read_text(encoding="utf-8"),
                         "The surface must be free of the word, or the test proves nothing about the closure.")

        result = self._evaluate("frontend/src/App.tsx", ["route"])

        self.assertEqual(result["status"], "failed", "App.tsx has no routing of its own; the import must not stand in for it.")
        self.assertEqual(result["evidence"]["required_any_resolution"]["unresolved"], ["route"])

    def test_a_surface_that_imports_no_client_resolves_nothing(self):
        self._write("frontend/src/api/client.ts", CLIENT)
        self._write("frontend/src/pages/StaticPage.tsx",
                    "export function StaticPage() {\n  return <p>About this product</p>;\n}\n")

        result = self._evaluate("frontend/src/pages/StaticPage.tsx", ["/api/activities"])

        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["evidence"]["required_any_resolution"]["closure_modules"], 0)

    def test_a_stub_that_imports_the_client_still_fails_on_substance(self):
        """The clause resolving must not rescue a file with nothing in it.

        This is the fix's most dangerous failure mode: a two-line component that imports
        the client would inherit every endpoint the client speaks. `min_chars` is what
        stops it, so the test asserts the clause resolved *and* the criterion failed.
        """
        self._write("frontend/src/api/client.ts", CLIENT)
        self._write("frontend/src/pages/ActivityPage.tsx",
                    'import { api } from "../api/client";\nexport const ActivityPage = () => null;\n')

        result = self._evaluate("frontend/src/pages/ActivityPage.tsx", ["/api/activities"], min_chars=900)

        self.assertEqual(result["evidence"]["matched"], ["/api/activities"])
        self.assertEqual(result["status"], "failed")
        self.assertLess(result["evidence"]["content_length"], 900)

    def test_a_base_that_exists_only_in_the_environment_leaves_the_clause_unresolved(self):
        """With no literal to read the base from, the composition cannot be verified.

        Ambiguity resolves against the clause: the reading declines rather than guessing
        that `VITE_API_URL` happens to be `/api`.
        """
        self._write("frontend/src/api/client.ts",
                    "const API_BASE = import.meta.env.VITE_API_URL;\n"
                    'export const listOrders = () => fetch(API_BASE + "/orders");\n')
        self._write("frontend/src/pages/OrdersPage.tsx",
                    'import { listOrders } from "../api/client";\nexport const OrdersPage = () => listOrders();\n')

        self.assertEqual(self._evaluate("frontend/src/pages/OrdersPage.tsx", ["/api/orders"])["status"], "failed")

    def test_an_absolute_base_url_is_not_mistaken_for_a_comment(self):
        """`//` after a colon is a scheme.

        Stripping from it would delete the rest of the line and the base literal with it,
        failing a client whose code plainly satisfies the clause - the same false negative
        the fix exists to remove, reintroduced by the comment stripping it depends on.
        """
        self._write("frontend/src/api/client.ts",
                    'const API_BASE = "https://api.example.com/api";  // configured per environment\n'
                    'export const listOrders = () => fetch(API_BASE + "/orders");\n')
        self._write("frontend/src/pages/OrdersPage.tsx",
                    'import { listOrders } from "../api/client";\nexport const OrdersPage = () => listOrders();\n')

        self.assertEqual(self._evaluate("frontend/src/pages/OrdersPage.tsx", ["/api/orders"])["status"], "passed")

    def test_reachability_still_decides_a_surface_no_user_can_open(self):
        """The clause and the wiring are separate questions and both still get asked.

        A resolved endpoint says the screen would work if it were mounted. It is not
        evidence that anything mounts it, and the fix must not quietly answer the second
        question with the first.
        """
        self._write("frontend/src/api/client.ts", CLIENT)
        self._write("frontend/package.json", '{ "name": "frontend", "private": true }\n')
        self._write("frontend/src/main.tsx", 'import { App } from "./App";\nrender(<App />);\n')
        self._write("frontend/src/App.tsx", "export function App() {\n  return <main>shell</main>;\n}\n")
        self._write("frontend/src/pages/OrphanPage.tsx", SCREEN)

        result = self._evaluate("frontend/src/pages/OrphanPage.tsx", ["/api/activities"], reachable=True)

        self.assertEqual(result["evidence"]["matched"], ["/api/activities"], "The clause resolves...")
        self.assertEqual(result["status"], "failed", "...and the criterion still fails, on reachability.")
        self.assertEqual(result["evidence"]["reachability"]["status"], "unreachable")

    def test_a_missing_surface_resolves_nothing_and_reports_the_missing_file(self):
        self._write("frontend/src/api/client.ts", CLIENT)

        result = self._evaluate("frontend/src/pages/NeverWritten.tsx", ["/api/activities"])

        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["evidence"]["error"], "File not found or not a file")
        self.assertNotIn("required_any_resolution", result["evidence"])

    def test_an_unreadable_closure_module_contributes_no_evidence_either_way(self):
        """An undecodable module fails a clause only it could have answered."""
        self._write("frontend/src/pages/ActivityPage.tsx", SCREEN)
        (self.root / "frontend/src/api").mkdir(parents=True, exist_ok=True)
        (self.root / "frontend/src/api/client.ts").write_bytes(b'const A = "/api";\n\xff\xfe fetch("/activities")\n')

        result = self._evaluate("frontend/src/pages/ActivityPage.tsx", ["/api/activities"])

        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["evidence"]["required_any_resolution"]["unresolved"], ["/api/activities"])

    # --- bounds ------------------------------------------------------------------

    def test_the_closure_stops_at_the_depth_limit(self):
        """Three hops out is a client behind a provider behind a hook; four is a stranger.

        Both sides of the boundary are asserted, because a depth limit that never binds
        and one that binds too early look the same from a single passing test.
        """
        self._write("frontend/src/api/client.ts", CLIENT)
        for name, target in [("b", "../api/client"), ("c", "./b"), ("d", "./c"), ("e", "./d")]:
            self._write(f"frontend/src/chain/{name}.ts", f'export * from "{target}";\n')

        self._write("frontend/src/pages/AtLimit.tsx", 'import "../chain/c";\n' + BODY)
        self.assertEqual(self._evaluate("frontend/src/pages/AtLimit.tsx", ["/api/activities"])["status"], "passed")

        self._write("frontend/src/pages/PastLimit.tsx", 'import "../chain/e";\n' + BODY)
        beyond = self._evaluate("frontend/src/pages/PastLimit.tsx", ["/api/activities"])
        self.assertEqual(beyond["status"], "failed")
        self.assertEqual(beyond["evidence"]["required_any_resolution"]["closure_depth_limit"],
                         self.service.ENDPOINT_CLOSURE_MAX_DEPTH)

    def test_the_closure_is_bounded_by_module_count(self):
        """Receipts are persisted and evaluation runs on every dispatch."""
        cap = self.service.ENDPOINT_CLOSURE_MAX_MODULES
        imports = []
        for index in range(cap + 50):
            self._write(f"frontend/src/widgets/w{index:03d}.ts", f"export const w{index} = {index};\n")
            imports.append(f'import "../widgets/w{index:03d}";')
        self._write("frontend/src/pages/WidePage.tsx", "\n".join(imports) + "\n" + SCREEN)

        result = self._evaluate("frontend/src/pages/WidePage.tsx", ["/api/activities"])

        self.assertLessEqual(result["evidence"]["required_any_resolution"]["closure_modules"], cap)


class CommentStrippingIsSharedTests(unittest.TestCase):
    """The helper the clause reading and the re-export split now both use."""

    def test_block_and_line_comments_go_and_code_stays(self):
        stripped = WorkspaceAcceptanceService._without_comments(
            "/* licence */\nconst a = 1; // note\nconst b = 2;\n"
        )
        self.assertNotIn("licence", stripped)
        self.assertNotIn("note", stripped)
        self.assertIn("const a = 1;", stripped)
        self.assertIn("const b = 2;", stripped)

    def test_a_url_scheme_survives_but_a_comment_after_it_does_not(self):
        stripped = WorkspaceAcceptanceService._without_comments('const u = "https://host/api"; // note\n')
        self.assertIn('"https://host/api"', stripped)
        self.assertNotIn("note", stripped)

    def test_a_comment_containing_a_url_is_still_a_comment(self):
        stripped = WorkspaceAcceptanceService._without_comments("// see http://example.com/api/orders\ncode();\n")
        self.assertNotIn("/api/orders", stripped)
        self.assertIn("code();", stripped)


if __name__ == "__main__":
    unittest.main()
