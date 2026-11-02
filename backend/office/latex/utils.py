"""Small shared helpers for the LaTeX parser."""

from __future__ import annotations

import re
from typing import List


def split_keywords(value: str) -> List[str]:
    return [part.strip() for part in re.split(r"[,;，；]", value) if part.strip()]
