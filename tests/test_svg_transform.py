import unittest

from core.ai_fleet.services.svg_transform import SvgTransformService


class SvgTransformTests(unittest.TestCase):
    def test_malicious_elements_attributes_and_external_refs_are_removed(self):
        content = '''<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" onload="evil()"><script>alert(1)</script><foreignObject><div>bad</div></foreignObject><image xlink:href="https://evil.example/a.png"/><a href="javascript:evil()"><rect width="1"/></a><rect style="background:url(https://evil.example/x)"/></svg>'''
        result = SvgTransformService().sanitize(content)
        output = result["content"].lower()
        self.assertNotIn("script", output)
        self.assertNotIn("foreignobject", output)
        self.assertNotIn("onload", output)
        self.assertNotIn("evil.example", output)
        self.assertNotIn("javascript", output)
        self.assertTrue(result["sanitized"])
        self.assertGreaterEqual(result["report"]["external_references_removed"], 2)

    def test_safe_internal_reference_is_preserved(self):
        content = '<svg xmlns="http://www.w3.org/2000/svg"><defs><linearGradient id="g"/></defs><rect fill="url(#g)" width="10" height="10"/></svg>'
        result = SvgTransformService().sanitize(content)
        self.assertIn("url(#g)", result["content"])
        self.assertFalse(result["sanitized"])

    def test_doctype_entity_malformed_and_non_svg_are_rejected(self):
        for content in ['<!DOCTYPE svg><svg/>', '<!ENTITY x "y"><svg/>', '<svg>', '<html/>']:
            with self.assertRaises(Exception):
                SvgTransformService().sanitize(content)


if __name__ == "__main__":
    unittest.main()
