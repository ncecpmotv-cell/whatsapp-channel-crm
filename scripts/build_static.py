#!/usr/bin/env python3
"""Regenerate the stylesheet and the .gz twins of local static assets.

Run after editing ui.CSS or static/app.js, then commit the results so the
phone can serve pre-compressed files instead of compressing per request.
"""
import gzip
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "bridge"))

import ui  # noqa: E402

STATIC = os.path.join(ROOT, "bridge", "static")

path = ui.write_stylesheet(STATIC)
print(f"css  {os.path.getsize(path):>6}B  {path}")

for name in ("app.js", "app.css"):
    src = os.path.join(STATIC, name)
    if not os.path.exists(src):
        continue
    with open(src, "rb") as fh:
        data = fh.read()
    with open(src + ".gz", "wb") as fh:
        fh.write(gzip.compress(data, 9))
    print(f"gz   {os.path.getsize(src + '.gz'):>6}B  {name}.gz")
