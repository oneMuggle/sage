from __future__ import annotations

import pytest

from backend.design.artifact_parser import ArtifactParser
from backend.design.errors import DesignGenerationError


class TestArtifactParser:
    def test_parse_simple_artifact(self):
        llm_output = """Some preamble text.
<artifact identifier="my-page" type="text/html" title="My Page">
<!DOCTYPE html>
<html><head><title>Test</title></head><body><h1>Hello</h1></body></html>
</artifact>
Some postamble."""
        result = ArtifactParser.parse(llm_output)
        assert result.identifier == "my-page"
        assert result.type == "text/html"
        assert result.title == "My Page"
        assert "<!DOCTYPE html>" in result.html_content
        assert "<h1>Hello</h1>" in result.html_content

    def test_parse_artifact_with_attributes(self):
        llm_output = (
            '<artifact identifier="dashboard" type="text/html"'
            ' title="Dashboard View">\n<html></html>\n</artifact>'
        )
        result = ArtifactParser.parse(llm_output)
        assert result.identifier == "dashboard"
        assert result.title == "Dashboard View"

    def test_no_artifact_tag_raises(self):
        with pytest.raises(DesignGenerationError, match="No <artifact>"):
            ArtifactParser.parse(
                "Just plain text, no artifact tags here."
            )

    def test_unclosed_artifact_tag_raises(self):
        with pytest.raises(DesignGenerationError, match="Unclosed"):
            ArtifactParser.parse(
                '<artifact identifier="x" type="text/html" title="X">'
                "\n<html></html>"
            )

    def test_multiple_artifacts_returns_first(self):
        llm_output = """
<artifact identifier="first" type="text/html" title="First">
<html>first</html>
</artifact>
<artifact identifier="second" type="text/html" title="Second">
<html>second</html>
</artifact>
"""
        result = ArtifactParser.parse(llm_output)
        assert result.identifier == "first"

    def test_parse_strips_leading_trailing_whitespace(self):
        llm_output = (
            '<artifact identifier="x" type="text/html" title="X">'
            "\n   <html>  </html>   \n</artifact>"
        )
        result = ArtifactParser.parse(llm_output)
        assert result.html_content.strip() == "<html>  </html>"

    def test_parse_realistic_html_content(self):
        llm_output = """<artifact identifier="landing" type="text/html" title="SaaS Landing">
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>SaaS Landing Page</title>
  <style>
    :root { --primary: #6366f1; }
    body { font-family: system-ui; margin: 0; }
    .hero { padding: 4rem 2rem; text-align: center; }
  </style>
</head>
<body>
  <section class="hero">
    <h1>Build faster with our platform</h1>
    <p>The all-in-one solution for modern teams.</p>
    <button>Get Started</button>
  </section>
</body>
</html>
</artifact>"""
        result = ArtifactParser.parse(llm_output)
        assert "<!DOCTYPE html>" in result.html_content
        assert "--primary: #6366f1" in result.html_content
        assert "Get Started" in result.html_content
