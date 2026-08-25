from typing import Any, Dict, List


class ResponsiveDesignGateService:
    def assess(self, viewports: List[Dict[str, Any]], asset_findings: List[Dict[str, Any]], font_findings: List[Dict[str, Any]]):
        findings = []
        widths = set()
        for view in viewports:
            viewport_width = int(view.get("viewport_width", 0))
            scroll_width = int(view.get("scroll_width", 0))
            widths.add(viewport_width)
            evidence = {"scroll_width": scroll_width, "viewport_width": viewport_width, "screenshot_id": view.get("screenshot_id")}
            if scroll_width > viewport_width:
                findings.append({"rule": "horizontal_overflow", "severity": "high", "viewport": view.get("name"), "evidence": evidence, "automated": True})
            if view.get("offenders"):
                findings.append({"rule": "uncontained_element_overflow", "severity": "high", "viewport": view.get("name"), "evidence": {**evidence, "offenders": view["offenders"][:20]}, "automated": True})
            if view.get("mainVisible") is False:
                findings.append({"rule": "main_content_hidden", "severity": "critical", "viewport": view.get("name"), "evidence": evidence, "automated": True})
            if view.get("navigation_control_found") is False:
                findings.append({"rule": "navigation_control_missing", "severity": "high", "viewport": view.get("name"), "evidence": evidence, "automated": True})
            expected_language = view.get("expected_language")
            if expected_language and (view.get("document_lang") != expected_language or view.get("document_dir") != ("rtl" if expected_language == "ar" else "ltr")):
                findings.append({"rule": "document_direction_mismatch", "severity": "high", "viewport": view.get("name"), "evidence": {**evidence, "expected_language": expected_language, "document_lang": view.get("document_lang"), "document_dir": view.get("document_dir")}, "automated": True})
            if not view.get("screenshot_id"):
                findings.append({"rule": "screenshot_evidence_missing", "severity": "medium", "viewport": view.get("name"), "evidence": evidence, "automated": True})
        required = {390, 768, 1024, 1440}
        missing = sorted(required - widths)
        if missing:
            findings.append({"rule": "supported_viewport_missing", "severity": "high", "evidence": {"missing_widths": missing}, "automated": True})
        findings.extend({**item, "automated": True} for item in asset_findings + font_findings)
        manual = [
            {"rule": "visual_hierarchy", "severity": "manual_required"},
            {"rule": "aesthetic_quality", "severity": "manual_required"},
            {"rule": "interaction_coherence", "severity": "manual_required"},
        ]
        return {"findings": findings, "manual_required": manual, "passed_automated": not any(item.get("severity") in {"high", "critical"} for item in findings), "visual_judgment_completed": False, "measured_viewports": sorted(widths), "gate_version": "1.1"}


responsive_design_gate_service = ResponsiveDesignGateService()
