"""Paid vocabulary and schema stay inside the paid package and its tests."""

import re
from pathlib import Path
from backend.paid import caps


def test_paid_code_stays_in_its_folder():
    root = Path(__file__).resolve().parents[2]
    excluded = [root / path for path in ("backend/paid", "backend/tests/paid", "backend/static")]
    # The HTTP cache header is not a plan name. Bare title-case names
    # and either quote style for the lower-case plan literals are forbidden.
    pattern = re.compile(
        r"\bPro\b|(?<!Access-Control-)\bMax\b|[\"'](?:pro|max)[\"']|(?i:stripe)|"
        + "|".join(re.escape(name) for name in caps.COLUMNS)
    )
    hits = []
    for folder in ("backend", "scripts"):
        for path in (root / folder).rglob("*"):
            if not path.is_file() or path == Path(__file__).resolve():
                continue
            if any(path.is_relative_to(parent) for parent in excluded) or "__pycache__" in path.parts:
                continue
            try:
                content = path.read_text()
            except UnicodeDecodeError:
                continue
            for number, line in enumerate(content.splitlines(), 1):
                if pattern.search(line):
                    hits.append(f"{path.relative_to(root)}:{number}")
    assert not hits, "Paid code outside its folder: " + ", ".join(hits)
