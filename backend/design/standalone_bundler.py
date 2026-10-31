# backend/design/standalone_bundler.py
"""Bundle HTML + CSS + assets into a self-contained HTML file."""
from __future__ import annotations

import re
<<<<<<< HEAD
from typing import List, Optional
=======
from typing import Optional
>>>>>>> origin/main


class StandaloneBundler:
    """Inline CSS and assets into a self-contained HTML document."""

    @staticmethod
    def bundle(
        html: str,
        css: str,
        assets: Optional[dict[str, str]] = None,
    ) -> str:
        """Bundle HTML with design system CSS and optional template assets.

        Returns self-contained HTML string with all CSS inlined.
        """
<<<<<<< HEAD
        all_css_parts: List[str] = []
=======
        all_css_parts: list[str] = []
>>>>>>> origin/main
        if css:
            all_css_parts.append(css)
        if assets:
            for filename, content in assets.items():
                if filename.endswith(".css"):
                    all_css_parts.append(content)

        combined_css = "\n\n".join(all_css_parts)

        if not combined_css:
            return html

        style_block = f"<style>\n{combined_css}\n</style>"

        # Inject before </head>
        if "</head>" in html:
            return html.replace("</head>", f"{style_block}\n</head>")

        # Inject after <head...>
        head_match = re.search(r"<head[^>]*>", html)
        if head_match:
            insert_pos = head_match.end()
            return html[:insert_pos] + f"\n{style_block}" + html[insert_pos:]

        # Fallback: inject at the beginning
        return f"{style_block}\n{html}"
