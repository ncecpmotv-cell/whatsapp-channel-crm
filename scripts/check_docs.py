#!/usr/bin/env python3
"""Validate the documentation contract. Runs in CI (see .github/workflows/ci.yml).

Rules (docs/README.md):
  * every docs/features/NNNN-*.md has non-empty Why / How / Verify / Limits
  * every feature page is linked from docs/features/README.md
  * every R-NN referenced by a feature page exists in ROADMAP.md
  * every path in a page's **Files:** line exists in the repository
  * every markdown link in ROADMAP.md resolves
"""
from __future__ import annotations

import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FEATURES = os.path.join(ROOT, "docs", "features")
HEADINGS = ("## Why", "## How", "## Verify", "## Limits")
LINK_RE = re.compile(r"\]\(([^)]+)\)")


def fail(message: str, errors: list[str]) -> None:
    errors.append(message)


def section(text: str, heading: str) -> str:
    start = text.find(heading)
    if start < 0:
        return ""
    rest = text[start + len(heading):]
    end = rest.find("\n## ")
    return (rest if end < 0 else rest[:end]).strip()


def main() -> int:
    errors: list[str] = []
    index_path = os.path.join(FEATURES, "README.md")
    index = open(index_path, encoding="utf-8").read() if os.path.exists(index_path) else ""
    roadmap_path = os.path.join(ROOT, "ROADMAP.md")
    roadmap = open(roadmap_path, encoding="utf-8").read() if os.path.exists(roadmap_path) else ""
    if not roadmap:
        fail("ROADMAP.md is missing", errors)

    pages = sorted(
        name for name in os.listdir(FEATURES)
        if re.fullmatch(r"\d{4}-[a-z0-9-]+\.md", name) and not name.startswith("0000")
    )
    if not pages:
        fail("no feature pages found in docs/features", errors)

    for name in pages:
        path = os.path.join(FEATURES, name)
        text = open(path, encoding="utf-8").read()
        for heading in HEADINGS:
            if not section(text, heading):
                fail(f"{name}: missing or empty '{heading}'", errors)
        if name not in index:
            fail(f"{name}: not linked from docs/features/README.md", errors)
        for ref in set(re.findall(r"\bR-\d{2}\b", text)):
            if ref not in roadmap:
                fail(f"{name}: roadmap id {ref} is not in ROADMAP.md", errors)
        files_line = re.search(r"^- \*\*Files:\*\*(.+)$", text, re.MULTILINE)
        if files_line:
            for token in re.findall(r"`([^`]+)`", files_line.group(1)):
                for candidate in token.split(","):
                    candidate = candidate.strip().strip("`")
                    if candidate and not os.path.exists(os.path.join(ROOT, candidate)):
                        fail(f"{name}: Files: path '{candidate}' does not exist", errors)

    for target in LINK_RE.findall(roadmap):
        if target.startswith(("http://", "https://", "#")):
            continue
        if not os.path.exists(os.path.join(ROOT, target.split("#")[0])):
            fail(f"ROADMAP.md: broken link '{target}'", errors)

    if errors:
        print("documentation check failed:")
        for err in errors:
            print(f"  - {err}")
        return 1
    print(f"documentation check passed ({len(pages)} feature pages)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
