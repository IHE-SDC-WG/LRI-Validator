from __future__ import annotations

import re
from html.parser import HTMLParser

from tests.support import ROOT


VOID_ELEMENTS = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}


class DocumentAudit(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.ids: list[str] = []
        self.external_attributes: list[tuple[str, str, str]] = []
        self.buttons_without_type: list[str] = []
        self.stack: list[str] = []
        self.nesting_errors: list[str] = []
        self.doctype = ""

    def handle_decl(self, decl: str) -> None:
        self.doctype = decl

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if attributes.get("id"):
            self.ids.append(attributes["id"] or "")
        for name in ("src", "href", "action"):
            if attributes.get(name):
                self.external_attributes.append((tag, name, attributes[name] or ""))
        if tag == "button" and not attributes.get("type"):
            self.buttons_without_type.append(attributes.get("id") or "unnamed")
        if tag not in VOID_ELEMENTS:
            self.stack.append(tag)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        if tag not in VOID_ELEMENTS:
            self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        if not self.stack or self.stack[-1] != tag:
            self.nesting_errors.append(tag)
            return
        self.stack.pop()


def test_generated_html_structure_and_local_only_contract() -> None:
    html = (ROOT / "dist" / "naaccr-lri-validator.html").read_text(encoding="utf-8")
    audit = DocumentAudit()
    audit.feed(html)
    audit.close()

    assert audit.doctype.lower() == "doctype html"
    assert not audit.stack
    assert not audit.nesting_errors
    assert len(audit.ids) == len(set(audit.ids))
    assert not audit.external_attributes
    assert not audit.buttons_without_type
    assert html.count("<script") == html.count("</script>") == 4
    assert max(map(len, html.splitlines())) < 1000
    assert "innerHTML" not in html


def test_application_dom_references_exist() -> None:
    html = (ROOT / "dist" / "naaccr-lri-validator.html").read_text(encoding="utf-8")
    app = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
    ids = set(re.findall(r'\bid="([^"]+)"', html))
    references = set(re.findall(r'\bbyId\("([^"]+)"\)', app))
    assert references <= ids


def test_outbound_review_follows_registry_check_button() -> None:
    html = (ROOT / "dist" / "naaccr-lri-validator.html").read_text(encoding="utf-8")
    button = html.index('id="run-content"')
    review = html.index('id="outbound-review-heading"')
    disclosure = html.index('id="content-disclosure"')
    assert button < review < disclosure
