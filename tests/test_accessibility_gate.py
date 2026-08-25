import unittest

from core.ai_fleet.services.accessibility_gate import AccessibilityGateService


class AccessibilityGateTests(unittest.TestCase):
    def test_fixture_findings_and_manual_limitations_are_explicit(self):
        result = AccessibilityGateService().check("<html><body><img src='x'><button></button><input></body></html>")
        rules = {item["rule"] for item in result["findings"]}
        self.assertTrue({"html_lang", "image_alt", "button_name", "form_label", "heading_structure", "main_landmark"} <= rules)
        self.assertFalse(result["automated_passed"])
        self.assertFalse(result["full_accessibility_claim"])
        self.assertEqual({item["rule"] for item in result["manual_required"]}, {"color_contrast", "keyboard_navigation", "screen_reader", "rtl_visual_order"})

    def test_configurable_safe_fixture_passes_automated_subset_only(self):
        html = "<html lang='en' dir='ltr'><body><main><h1>Title</h1><img src='x' alt=''><label for='q'>Query</label><input id='q'><button aria-label='Close'></button></main></body></html>"
        result = AccessibilityGateService().check(html)
        self.assertTrue(result["automated_passed"])
        self.assertEqual(result["findings"], [])
        self.assertTrue(result["manual_required"])

    def test_duplicate_ids_unlabelled_controls_heading_skips_and_invalid_direction_fail(self):
        html = "<html lang='en' dir='sideways'><body><main><h1>Title</h1><h3>Skip</h3><input id='same'><select id='same'></select></main></body></html>"
        result = AccessibilityGateService().check(html)
        rules = {item["rule"] for item in result["findings"]}
        self.assertTrue({"html_dir", "duplicate_id", "form_label", "heading_structure"} <= rules)
        self.assertFalse(result["automated_passed"])


if __name__ == "__main__":
    unittest.main()
