# backend/tests/unit/test_standalone_bundler.py
from __future__ import annotations

from backend.design.standalone_bundler import StandaloneBundler


class TestStandaloneBundler:
    def test_bundle_injects_css_into_head(self):
        html = (
            "<!DOCTYPE html><html><head><title>Test</title>"
            "</head><body>Hello</body></html>"
        )
        css = ":root { --bg: #fff; } body { background: var(--bg); }"
        result = StandaloneBundler.bundle(html, css)
        assert ":root { --bg: #fff; }" in result
        assert "<style>" in result
        assert "</style>" in result

    def test_bundle_preserves_existing_content(self):
        html = (
            "<!DOCTYPE html><html><head><title>My Page</title>"
            "</head><body><h1>Hello</h1></body></html>"
        )
        result = StandaloneBundler.bundle(html, "")
        assert "<title>My Page</title>" in result
        assert "<h1>Hello</h1>" in result

    def test_bundle_handles_html_without_head(self):
        html = "<html><body>Simple</body></html>"
        css = "body { color: red; }"
        result = StandaloneBundler.bundle(html, css)
        assert "body { color: red; }" in result

    def test_bundle_with_empty_css(self):
        html = "<html><head></head><body>Test</body></html>"
        result = StandaloneBundler.bundle(html, "")
        assert "Test" in result

    def test_bundle_with_template_assets(self):
        html = "<html><head></head><body>Content</body></html>"
        css = ":root { --primary: blue; }"
        assets = {
            "animations.css": (
                "@keyframes fade { from { opacity: 0; } "
                "to { opacity: 1; } }"
            ),
        }
        result = StandaloneBundler.bundle(html, css, assets)
        assert "@keyframes fade" in result
        assert ":root { --primary: blue; }" in result
