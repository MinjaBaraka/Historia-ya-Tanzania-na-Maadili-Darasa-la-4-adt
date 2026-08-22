#!/usr/bin/env python3
"""Remove duplicate read-aloud sources from an exported ADT book.

The reader queues *every* mapped ``data-id`` below ``#content``.  Therefore a
visually hidden duplicate label, or a decorative ``aria-hidden`` image that
still has a data-id, creates a second spoken item.  This utility removes the
duplicate HTML source and then removes its text/audio mappings only when the
ID is unused everywhere in the exported book.
"""

from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path


# These captions merely repeat the section heading immediately before them;
# retain the heading narration and leave the visual caption on screen.
SEMANTIC_DUPLICATE_CAPTIONS = {"pg162_n0021", "pg163_n0020"}

# Decorative activity icons are visual cues only; their task heading and
# instruction already provide the narration.  They must never enter the
# read-aloud queue.
EXCLUDED_NARRATION_IDS = {
    "pg008_im001",
    "pg011_im001",
    "pg011_im002",
    "pg013_im001",
    "pg017_im001",
    "pg018_im001",
    "pg021_im001",
    "pg021_im002",
    "pg024_im001",
    "pg036_im001",
    "pg044_im001",
    "pg044_im002",
    "pg049_im001",
    "pg061_im001",
    "pg064_im001",
    "pg064_im002",
    "pg083_im001",
    "pg089_im001",
    "pg091_im001",
    "pg098_im001",
    "pg103_im001",
    "pg104_im001",
    "pg107_im001",
    "pg119_im001",
    "pg121_im001",
    "pg129_im001",
    "pg143_im001",
    "pg144_im001",
    "pg148_im001",
    "pg153_im001",
    "pg153_im002",
    "pg154_im001",
    "pg166_im001",
}


@dataclass(frozen=True)
class Node:
    tag: str
    attrs: dict[str, str]

    @property
    def text_id(self) -> str:
        return self.attrs["data-id"]

    @property
    def decorative(self) -> bool:
        return self.tag == "img" and (
            self.attrs.get("aria-hidden") == "true"
            or self.attrs.get("role") == "presentation"
        )

    @property
    def hidden(self) -> bool:
        classes = set(self.attrs.get("class", "").split())
        return self.attrs.get("aria-hidden") == "true" or bool(
            {"hidden", "sr-only"} & classes
        )


class DataIdParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.nodes: list[Node] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {name: value or "" for name, value in attrs}
        if "data-id" in values:
            self.nodes.append(Node(tag, values))


def page_nodes(path: Path) -> list[Node]:
    parser = DataIdParser()
    parser.feed(path.read_text(encoding="utf-8"))
    return parser.nodes


def remove_data_id(source: str, text_id: str, *, mark_hidden: bool = False) -> str:
    pattern = re.compile(
        rf"<(?P<tag>[A-Za-z][\w:-]*)(?P<attrs>[^>]*?)\sdata-id=\"{re.escape(text_id)}\"(?P<tail>[^>]*)>",
        re.S,
    )

    def replacement(match: re.Match[str]) -> str:
        attrs = f"{match.group('attrs')}{match.group('tail')}"
        if mark_hidden and 'aria-hidden="true"' not in attrs:
            attrs += ' aria-hidden="true"'
        return f"<{match.group('tag')}{attrs}>"

    return pattern.sub(replacement, source)


def write_json(path: Path, data: dict[str, str]) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", nargs="?", default=".")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    i18n = root / "content/i18n/sw-TZ"
    texts_path = i18n / "texts.json"
    audios_path = i18n / "audios.json"
    texts: dict[str, str] = json.loads(texts_path.read_text(encoding="utf-8"))
    audios: dict[str, str] = json.loads(audios_path.read_text(encoding="utf-8"))
    removals: dict[Path, set[str]] = defaultdict(set)
    hidden_removals: dict[Path, set[str]] = defaultdict(set)

    for page in sorted(root.glob("pg*_sec*.html")):
        nodes = page_nodes(page)
        by_id: dict[str, list[Node]] = defaultdict(list)
        by_text: dict[str, list[Node]] = defaultdict(list)
        for node in nodes:
            by_id[node.text_id].append(node)
            value = texts.get(node.text_id, "").strip().casefold()
            if value:
                by_text[value].append(node)

        # Decorative images cannot be a narration item.  If the same image ID
        # is also used by a non-decorative image, retain that one source only.
        for node in nodes:
            if node.decorative:
                removals[page].add(node.text_id)
            if node.text_id in SEMANTIC_DUPLICATE_CAPTIONS:
                removals[page].add(node.text_id)
            if node.text_id in EXCLUDED_NARRATION_IDS:
                removals[page].add(node.text_id)

        # A hidden copy of a visible label is an actual duplicate source.  Do
        # not remove hidden question text: its ID has a natural question cue.
        # The explicit data-question-narration marker is the distinction.
        source = page.read_text(encoding="utf-8")
        question_ids = set(
            re.findall(r'data-question-narration-for="([^"]+)"', source)
        )
        for copies in by_text.values():
            ids = {node.text_id for node in copies}
            if len(ids) < 2:
                continue
            visible_ids = {node.text_id for node in copies if not node.hidden}
            for node in copies:
                if (
                    node.hidden
                    and node.text_id not in question_ids
                    and visible_ids - {node.text_id}
                ):
                    removals[page].add(node.text_id)
                    hidden_removals[page].add(node.text_id)

        # If one ID occurs in more than one element, retain exactly one
        # non-decorative source.  The remaining occurrences receive no ID and
        # therefore cannot be queued a second time.
        for text_id, copies in by_id.items():
            if len(copies) > 1:
                removals[page].add(text_id)

    if args.check:
        count = sum(len(ids) for ids in removals.values())
        print(f"Duplicate narration sources found: {count}")
        for page, ids in sorted(removals.items()):
            print(f"  {page.name}: {', '.join(sorted(ids))}")
        return 1 if count else 0

    changed_pages = 0
    for page, ids in removals.items():
        source = page.read_text(encoding="utf-8")
        updated = source
        nodes = page_nodes(page)
        counts = defaultdict(int)
        for node in nodes:
            counts[node.text_id] += 1
        for text_id in ids:
            if counts[text_id] > 1:
                # Remove only decorative occurrences.  A non-decorative image
                # remains the single valid image-description narration source.
                pattern = re.compile(
                    rf"<(?P<tag>img)(?P<attrs>[^>]*\sdata-id=\"{re.escape(text_id)}\"[^>]*)>",
                    re.S,
                )
                def image_replacement(match: re.Match[str]) -> str:
                    attrs = match.group("attrs")
                    if 'aria-hidden="true"' not in attrs and 'role="presentation"' not in attrs:
                        return match.group(0)
                    attrs = re.sub(r'\sdata-id="[^"]+"', "", attrs)
                    return f"<img{attrs}>"
                updated = pattern.sub(image_replacement, updated)
            else:
                updated = remove_data_id(
                    updated, text_id, mark_hidden=text_id in hidden_removals[page]
                )
        if updated != source:
            page.write_text(updated, encoding="utf-8")
            changed_pages += 1

    # An ID is removed from the JSON only when it is no longer referenced by
    # any page.  This also deletes both standard and Easy Read audio files.
    referenced = set()
    for page in root.glob("pg*_sec*.html"):
        referenced.update(node.text_id for node in page_nodes(page))
    removed_ids = set().union(*removals.values()) if removals else set()
    pruned = []
    for text_id in sorted(removed_ids):
        if text_id in referenced:
            continue
        for key in (text_id, f"{text_id}_easy_read"):
            filename = audios.pop(key, None)
            texts.pop(key, None)
            if filename:
                (i18n / "audio" / filename).unlink(missing_ok=True)
                pruned.append(key)
    write_json(texts_path, texts)
    write_json(audios_path, audios)
    print(f"Updated pages: {changed_pages}")
    print(f"Removed duplicate text/audio mappings: {len(pruned)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
