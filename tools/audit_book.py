#!/usr/bin/env python3
"""Validate the ADT spine, i18n references, assets, and activity contracts."""

from __future__ import annotations

import argparse
import html
import json
import re
import sys
from collections import Counter
from pathlib import Path


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", nargs="?", default=".")
    args = parser.parse_args()
    root = Path(args.root).resolve()
    pages = load_json(root / "content/pages.json")
    texts = load_json(root / "content/i18n/sw-TZ/texts.json")
    audios = load_json(root / "content/i18n/sw-TZ/audios.json")
    issues: list[str] = []
    section_ids: set[str] = set()
    section_types: Counter[str] = Counter()

    for position, entry in enumerate(pages, 1):
        href = entry["href"]
        path = root / href
        if not path.exists():
            issues.append(f"missing file: {href}")
            continue
        source = path.read_text(encoding="utf-8")
        title = re.search(r'<meta name="title-id" content="([^"]+)"', source)
        index = re.search(r'<meta name="page-section-id" content="(\d+)"', source)
        if not title or title.group(1) != entry["section_id"]:
            issues.append(f"title-id mismatch: {href}")
        if not index or int(index.group(1)) != position:
            issues.append(f"page-section-id mismatch: {href} expected {position}")
        if entry["section_id"] in section_ids:
            issues.append(f"duplicate section_id: {entry['section_id']}")
        section_ids.add(entry["section_id"])

        section_type = re.search(r'data-section-type="([^"]+)"', source)
        if section_type:
            section_types[section_type.group(1)] += 1

        for data_id in dict.fromkeys(re.findall(r'data-id="([^"]+)"', source)):
            if re.fullmatch(r"qz\d+", data_id):
                continue
            if data_id not in texts:
                issues.append(f"missing text id: {href} -> {data_id}")
            number_only = bool(re.fullmatch(r"\s*\d+\.\s*", texts.get(data_id, "")))
            number_hidden = bool(re.search(
                rf'<[^>]+data-id="{re.escape(data_id)}"[^>]+aria-hidden="true"', source
            ))
            if data_id not in audios and not (number_only and number_hidden):
                issues.append(f"missing audio mapping: {href} -> {data_id}")
            elif data_id in audios and not (root / "content/i18n/sw-TZ/audio" / audios[data_id]).exists():
                issues.append(f"missing audio file: {href} -> {audios[data_id]}")

        for src in re.findall(r'<img[^>]+src="([^"]+)"', source):
            if not (root / src).exists():
                issues.append(f"missing image: {href} -> {src}")

        if href.startswith("qz"):
            answer_block = re.search(
                r'<script type="application/json" id="quiz-correct-answers">\s*(\{.*?\})\s*</script>',
                source,
                re.S,
            )
            explanation_block = re.search(
                r'<script type="application/json" id="quiz-explanations">\s*(\{.*?\})\s*</script>',
                source,
                re.S,
            )
            section_answers = re.search(r"data-correct-answers='([^']+)'", source)
            window_answers = re.search(
                r"window\.correctAnswers\s*=\s*JSON\.parse\('(.*?)'\)", source
            )
            try:
                copies = [
                    json.loads(answer_block.group(1)),
                    json.loads(html.unescape(section_answers.group(1))),
                    json.loads(window_answers.group(1)),
                ]
                if not copies[0] == copies[1] == copies[2]:
                    raise ValueError("answer copies differ")
                explanations = json.loads(explanation_block.group(1))
                if set(explanations) != set(copies[0]):
                    raise ValueError("explanation keys differ")
            except Exception as error:  # noqa: BLE001 - audit must report malformed files
                issues.append(f"quiz contract error: {href} -> {error}")

        if "https://fonts.googleapis.com" in source or "https://fonts.gstatic.com" in source:
            issues.append(f"external font dependency: {href}")
        if "./assets/book-theme.css" not in source:
            issues.append(f"missing shared theme: {href}")
        if "./assets/book-activities.js" not in source:
            issues.append(f"missing activity enhancements: {href}")

    print(f"Manifest entries: {len(pages)}")
    print("Section types:")
    for name, count in section_types.most_common():
        print(f"  {name}: {count}")
    if issues:
        print(f"Issues: {len(issues)}")
        for issue in issues:
            print(f"  - {issue}")
        return 1
    print("Issues: 0")
    return 0


if __name__ == "__main__":
    sys.exit(main())
