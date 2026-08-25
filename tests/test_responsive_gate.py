import unittest

from core.ai_fleet.services.responsive_gate import ResponsiveDesignGateService


class ResponsiveGateTests(unittest.TestCase):
    def test_measured_overflow_and_visual_limits_are_separate(self):
        result = ResponsiveDesignGateService().assess([{"name": "mobile", "viewport_width": 390, "scroll_width": 420, "screenshot_id": "shot-1", "mainVisible": True, "navigation_control_found": True}], [{"rule": "missing_asset", "severity": "high", "evidence": {}}], [{"rule": "font_missing", "severity": "medium", "evidence": {}}])
        self.assertFalse(result["passed_automated"])
        self.assertFalse(result["visual_judgment_completed"])
        self.assertEqual(result["findings"][0]["evidence"]["screenshot_id"], "shot-1")
        self.assertEqual(len(result["manual_required"]), 3)

    def test_supported_viewports_with_visible_routes_pass_automated_gate_only(self):
        views = [{"name": str(width), "viewport_width": width, "scroll_width": width, "screenshot_id": f"{width}.png", "mainVisible": True, "navigation_control_found": True, "expected_language": "ar", "document_lang": "ar", "document_dir": "rtl", "offenders": []} for width in (390, 768, 1024, 1440)]
        result = ResponsiveDesignGateService().assess(views, [], [])
        self.assertTrue(result["passed_automated"])
        self.assertEqual(result["measured_viewports"], [390, 768, 1024, 1440])
        self.assertFalse(result["visual_judgment_completed"])

    def test_wrong_rtl_direction_fails(self):
        views = [{"name": str(width), "viewport_width": width, "scroll_width": width, "screenshot_id": f"{width}.png", "mainVisible": True, "navigation_control_found": True, "expected_language": "ar", "document_lang": "ar", "document_dir": "ltr", "offenders": []} for width in (390, 768, 1024, 1440)]
        result = ResponsiveDesignGateService().assess(views, [], [])
        self.assertIn("document_direction_mismatch", {item["rule"] for item in result["findings"]})
        self.assertFalse(result["passed_automated"])

    def test_missing_navigation_and_uncontained_element_fail(self):
        views = [{"name": str(width), "viewport_width": width, "scroll_width": width, "screenshot_id": f"{width}.png", "mainVisible": True, "navigation_control_found": width != 390, "offenders": [{"tag": "DIV"}] if width == 768 else []} for width in (390, 768, 1024, 1440)]
        result = ResponsiveDesignGateService().assess(views, [], [])
        rules = {item["rule"] for item in result["findings"]}
        self.assertTrue({"navigation_control_missing", "uncontained_element_overflow"} <= rules)
        self.assertFalse(result["passed_automated"])


if __name__ == "__main__":
    unittest.main()
