from dataclasses import dataclass
from typing import Any, Dict, Optional

import httpx


@dataclass(frozen=True)
class Project:
    id: str
    name: str
    slug: str
    project_type: str
    lifecycle_status: str
    revision: int


@dataclass(frozen=True)
class Run:
    id: str
    status: str
    prompt: str
    project_id: Optional[str]
    cost_provenance: str


class AiFleetSdkError(RuntimeError):
    def __init__(self, status_code: int, code: str, message: str):
        super().__init__(message)
        self.status_code = status_code
        self.code = code


class AiFleetValidationError(ValueError):
    """A call that cannot be made truthfully, refused locally before any request.

    This carries no status code on purpose: nothing was sent, so there is no server
    verdict to report. It subclasses `ValueError` because that is already this client's
    contract for local misuse - an out-of-range timeout and a non-`/api` path both raise
    it - and it adds `code` so a caller such as the CLI can render a structured error
    without parsing the message.
    """

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


GOAL_REQUIRED_MESSAGE = "A TEMM project needs an explicit goal describing what you want accomplished."


def require_goal(value: Optional[str]) -> str:
    """The single place that decides whether a project carries explicit intent.

    A TEMM project is the record of something a person wants accomplished, and every
    later stage - blueprint, requirements, plan, acceptance - is derived from it. The
    client used to default the goal to an empty string, so a caller who simply omitted it
    sent blank intent and got the backend's generic `validation_failed`; that reads as an
    SDK bug rather than as the missing goal it is. Refused here instead, by name, without
    a request. Nothing substitutes a goal on the caller's behalf: inventing one would
    fabricate the intent the whole project is supposed to record.
    """
    goal = (value or "").strip()
    if not goal:
        raise AiFleetValidationError("goal_required", GOAL_REQUIRED_MESSAGE)
    return goal


class AiFleetClient:
    def __init__(self, base_url: str = "http://127.0.0.1:8787", transport: httpx.AsyncBaseTransport | None = None, timeout_seconds: float = 30):
        if not 0.1 <= timeout_seconds <= 300:
            raise ValueError("timeout_seconds must be between 0.1 and 300.")
        self.client = httpx.AsyncClient(base_url=base_url, transport=transport, timeout=timeout_seconds)
        self.domain_version: Optional[str] = None

    async def __aenter__(self): return self
    async def __aexit__(self, *_): await self.close()
    async def close(self): await self.client.aclose()

    async def negotiate(self, required_major: int = 1) -> Dict[str, Any]:
        data = await self._request("GET", "/api/fleet/domain-contract")
        version = data["domain_schema_version"]
        if int(version.split(".")[0]) != required_major:
            raise AiFleetSdkError(409, "incompatible_schema", f"Domain schema {version} is incompatible.")
        self.domain_version = version
        return data

    async def list_projects(self): return [self._project(item) for item in await self._request("GET", "/api/projects")]
    async def create_project(self, name: str, slug: str, project_type: str, goal: str = "", owner: str = "local_owner", *, purpose: Optional[str] = None):
        """Create a project from an explicit goal.

        `goal` is the product's word for the intent; `purpose` is the field the backend
        persists it under, and is kept as a keyword alias so callers written against the
        earlier signature keep working. Either one must carry real text.
        """
        intent = require_goal(goal or purpose)
        return self._project(await self._request("POST", "/api/projects", json={"name": name, "slug": slug, "project_type": project_type, "purpose": intent, "owner": owner}))
    async def get_run(self, run_id: str):
        item = await self._request("GET", f"/api/runs/{run_id}")
        return Run(item["id"], item["status"], item["prompt"], item.get("project_id"), item["cost_provenance"])
    async def cancel_run(self, run_id: str): return await self._request("POST", f"/api/runs/{run_id}/cancel")
    async def fleet_overview(self): return await self._request("GET", "/api/fleet/overview")
    async def request(self, method: str, path: str, **kwargs):
        if not path.startswith("/api/"): raise ValueError("SDK request path must start with /api/.")
        return await self._request(method, path, **kwargs)

    async def _request(self, method: str, path: str, **kwargs):
        try: response = await self.client.request(method, path, **kwargs)
        except httpx.TimeoutException as exc: raise AiFleetSdkError(408, "request_timeout", "TEMM request timed out.") from exc
        except httpx.RequestError as exc: raise AiFleetSdkError(503, "connection_failed", "Could not connect to TEMM.") from exc
        if response.is_error:
            try: data = response.json()
            except ValueError: data = {}
            error = data.get("error") or data.get("detail") or {}
            message = error.get("message", str(error)) if isinstance(error, dict) else str(error)
            code = error.get("code", "http_error") if isinstance(error, dict) else "http_error"
            raise AiFleetSdkError(response.status_code, code, message)
        try: return response.json()
        except ValueError as exc: raise AiFleetSdkError(502, "invalid_response", "TEMM returned invalid JSON.") from exc

    def _project(self, item): return Project(item["id"], item["name"], item["slug"], item["project_type"], item["lifecycle_status"], item["revision"])
