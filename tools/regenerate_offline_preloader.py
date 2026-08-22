#!/usr/bin/env python3
"""Refresh embedded ADT resources inside the generated offline preloader."""

from __future__ import annotations

import json
import re
from pathlib import Path


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    destination = root / "assets/offline-preloader.js"
    source = destination.read_text(encoding="utf-8")
    match = re.search(r"var INLINE = (\{.*?\});\n  var BASE_DIR", source, re.S)
    if not match:
        raise RuntimeError("Could not locate INLINE resources in offline-preloader.js")
    inline = json.loads(match.group(1))
    # Small post-export correction layers are loaded by every page.  Preserve
    # them in the offline bundle when they are present in the book root.
    for key in (
        "./assets/activity-layout-fixes.css",
        "./assets/activity-layout-fixes.js",
    ):
        if (root / key.removeprefix("./")).exists():
            inline.setdefault(key, "")
    refreshed = {}
    for key in inline:
        # Cache-busted browser URLs still map to the same local asset.
        path = root / key.removeprefix("./").split("?", 1)[0]
        if not path.exists():
            continue
        if path.suffix == ".json":
            refreshed[key] = json.loads(path.read_text(encoding="utf-8"))
        else:
            refreshed[key] = path.read_text(encoding="utf-8")
    payload = json.dumps(refreshed, ensure_ascii=False, separators=(",", ":"))
    updated = source[: match.start(1)] + payload + source[match.end(1) :]
    destination.write_text(updated, encoding="utf-8")
    print(f"Refreshed {len(refreshed)} offline resources")


if __name__ == "__main__":
    main()
