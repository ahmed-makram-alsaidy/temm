from typing import Any, Dict, List


class AssetAcquisitionPolicy:
    def plan(self, project_assets: List[Dict[str, Any]], library_assets: List[Dict[str, Any]], source_candidates: List[Dict[str, Any]], generation_available: bool) -> Dict[str, Any]:
        usable = lambda item: item.get("state") == "ready" and item.get("license_approved") is True
        project = next((item for item in project_assets if usable(item)), None)
        if project:
            return self._result("use_project_asset", project, False, "project_asset_available")
        library = next((item for item in library_assets if usable(item)), None)
        if library:
            return self._result("reuse_library_asset", library, False, "approved_library_asset_available")
        for candidate in source_candidates:
            if candidate.get("paid") or candidate.get("license_state") in {None, "unknown", "pending"}:
                return self._result("approval_required", candidate, True, "paid_or_license_approval_required")
            if candidate.get("license_state") == "approved":
                return self._result("acquire_from_source", candidate, True, "approved_source_candidate")
        if generation_available:
            return self._result("generate_asset", None, True, "no_approved_existing_asset")
        return self._result("unresolved", None, False, "no_acquisition_path_available")

    def _result(self, action: str, candidate: Dict[str, Any] | None, approval: bool, reason: str) -> Dict[str, Any]:
        return {"action": action, "candidate": candidate, "approval_required": approval, "reason": reason, "policy_order": ["project", "library", "source", "generation"], "policy_version": "1.0"}


asset_acquisition_policy = AssetAcquisitionPolicy()
