from collections import Counter
from html.parser import HTMLParser


class _MarkupAudit(HTMLParser):
    def __init__(self):
        super().__init__()
        self.html_attrs = {}
        self.ids = []
        self.images = []
        self.controls = []
        self.buttons = []
        self.labels_for = set()
        self.headings = []
        self.landmarks = set()
        self.stack = []

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        self.stack.append({"tag": tag, "attrs": attributes, "text": []})
        if tag == "html": self.html_attrs = attributes
        if attributes.get("id"): self.ids.append(attributes["id"])
        if tag == "img": self.images.append(attributes)
        if tag in {"input", "select", "textarea"}: self.controls.append((tag, attributes))
        if tag == "button": self.buttons.append(self.stack[-1])
        if tag == "label" and attributes.get("for"): self.labels_for.add(attributes["for"])
        if tag in {"h1", "h2", "h3", "h4", "h5", "h6"}: self.headings.append(int(tag[1]))
        if tag in {"main", "nav", "header", "footer", "aside"}: self.landmarks.add(tag)
        role = attributes.get("role")
        if role in {"main", "navigation", "banner", "contentinfo", "complementary"}: self.landmarks.add(role)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)

    def handle_data(self, data):
        for item in self.stack:
            item["text"].append(data)

    def handle_endtag(self, tag):
        for index in range(len(self.stack) - 1, -1, -1):
            item = self.stack[index]
            if item["tag"] == tag:
                self.stack.pop(index)
                break


class AccessibilityGateService:
    def check(self, html: str, enabled: list[str] | None = None):
        enabled = set(enabled or ["lang", "dir", "image_alt", "form_labels", "button_names", "heading", "landmarks", "duplicate_ids"])
        parser = _MarkupAudit()
        parser.feed(html)
        findings = []
        if "lang" in enabled and not parser.html_attrs.get("lang"):
            findings.append(self._finding("html_lang", "medium", "missing_lang_attribute"))
        if "dir" in enabled and parser.html_attrs.get("dir", "ltr") not in {"ltr", "rtl"}:
            findings.append(self._finding("html_dir", "medium", "invalid_direction"))
        if "image_alt" in enabled:
            for attributes in parser.images:
                if "alt" not in attributes:
                    findings.append(self._finding("image_alt", "high", "img_without_alt"))
        if "form_labels" in enabled:
            for tag, attributes in parser.controls:
                if tag == "input" and attributes.get("type", "text").lower() in {"hidden", "submit", "button", "reset"}:
                    continue
                control_id = attributes.get("id")
                labelled = attributes.get("aria-label") or attributes.get("aria-labelledby") or attributes.get("title") or control_id and control_id in parser.labels_for
                if not labelled:
                    findings.append(self._finding("form_label", "high", f"{tag}_without_accessible_name"))
        if "button_names" in enabled:
            for button in parser.buttons:
                attributes = button["attrs"]
                text = "".join(button["text"]).strip()
                if not text and not attributes.get("aria-label") and not attributes.get("aria-labelledby") and not attributes.get("title"):
                    findings.append(self._finding("button_name", "high", "button_without_name"))
        if "heading" in enabled:
            if 1 not in parser.headings:
                findings.append(self._finding("heading_structure", "medium", "h1_missing"))
            for previous, current in zip(parser.headings, parser.headings[1:]):
                if current > previous + 1:
                    findings.append(self._finding("heading_structure", "medium", "heading_level_skipped"))
                    break
        if "landmarks" in enabled and not ({"main", "main"} & parser.landmarks):
            findings.append(self._finding("main_landmark", "medium", "main_landmark_missing"))
        if "duplicate_ids" in enabled:
            duplicates = sorted(item for item, count in Counter(parser.ids).items() if count > 1)
            if duplicates:
                findings.append({**self._finding("duplicate_id", "high", "duplicate_document_ids"), "ids": duplicates})
        manual = [
            {"rule": "color_contrast", "severity": "manual_required", "reason": "Static markup cannot verify rendered contrast across themes and states."},
            {"rule": "keyboard_navigation", "severity": "manual_required", "reason": "Requires browser interaction across complete workflows and dialogs."},
            {"rule": "screen_reader", "severity": "manual_required", "reason": "Requires assistive technology review."},
            {"rule": "rtl_visual_order", "severity": "manual_required", "reason": "Requires rendered Arabic workflow review."},
        ]
        return {"findings": findings, "manual_required": manual, "automated_passed": not any(item["severity"] == "high" for item in findings), "full_accessibility_claim": False, "limitations": "Static checks do not replace browser and assistive-technology testing.", "gate_version": "1.1"}

    def _finding(self, rule, severity, evidence):
        return {"rule": rule, "severity": severity, "evidence": evidence, "automated": True}


accessibility_gate_service = AccessibilityGateService()
