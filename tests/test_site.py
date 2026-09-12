import json
import re
import shutil
import subprocess
from html.parser import HTMLParser
from pathlib import Path

import pytest

SITE = Path(__file__).resolve().parent.parent / "site"


class Collector(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids, self.stack, self.errors = set(), [], []
        self.void = {"meta", "link", "img", "input", "br", "hr", "source", "path"}

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if "id" in a:
            if a["id"] in self.ids:
                self.errors.append(f"duplicate id {a['id']}")
            self.ids.add(a["id"])
        if tag == "img" and "alt" not in a:
            self.errors.append("img without alt")
        if tag not in self.void:
            self.stack.append(tag)

    def handle_endtag(self, tag):
        if tag in self.void:
            return
        if not self.stack or self.stack[-1] != tag:
            self.errors.append(f"mismatched </{tag}>")
        else:
            self.stack.pop()


def parse(name):
    c = Collector()
    c.feed((SITE / name).read_text())
    return c


def test_html_is_well_formed():
    for page in ("index.html", "legal.html"):
        c = parse(page)
        assert not c.errors, (page, c.errors)
        assert not c.stack, (page, c.stack)


def test_every_id_used_by_app_js_exists():
    ids = parse("index.html").ids
    js = (SITE / "assets" / "app.js").read_text()
    used = set(re.findall(r'\$\("([\w-]+)"\)', js))
    assert used and used <= ids, used - ids


def test_js_syntax_with_node():
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")
    subprocess.run([node, "--check", str(SITE / "assets" / "app.js")], check=True)


def test_css_braces_balanced():
    css = (SITE / "assets" / "style.css").read_text()
    assert css.count("{") == css.count("}")


def _lum(h):
    r, g, b = (int(h[i:i + 2], 16) / 255 for i in (1, 3, 5))
    f = lambda c: c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4  # noqa: E731
    return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b)


def _ratio(a, b):
    la, lb = sorted((_lum(a), _lum(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def test_wcag_aa_contrast_for_palette_and_every_family_accent():
    css = (SITE / "assets" / "style.css").read_text()
    tok = dict(re.findall(r"--([\w-]+):\s*(#[0-9a-fA-F]{6})", css))
    for fg in ("text", "muted", "accent", "ok", "bad", "warn"):
        for bg in ("ink", "panel", "panel-2"):
            assert _ratio(tok[fg], tok[bg]) >= 4.5, (fg, bg, _ratio(tok[fg], tok[bg]))
    from anchor.config import load_profile
    for fam in load_profile().families:
        for bg in ("ink", "panel", "panel-2"):
            assert _ratio(fam.accent, tok[bg]) >= 4.5, (fam.id, bg)
        assert _ratio("#0a0a0b", fam.accent) >= 4.5, f"button text on {fam.id} accent"


def test_site_data_files_valid():
    cat = json.loads((SITE / "data" / "catalog.json").read_text())
    assert cat["artist"]["name"] == "ANCHOR" and isinstance(cat["drops"], list)
    json.loads((SITE / "data" / "status.json").read_text())
    json.loads((SITE / "vercel.json").read_text())
    for rel in ("favicon.svg", "og.jpg", "assets/hero-default.jpg", "assets/fonts/anton-400.woff2",
                "assets/fonts/jbmono-400.woff2", "assets/fonts/jbmono-700.woff2", "robots.txt", "sitemap.xml"):
        assert (SITE / rel).exists(), rel
