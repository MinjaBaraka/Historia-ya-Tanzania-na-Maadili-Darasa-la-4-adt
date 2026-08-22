#!/usr/bin/env python3
"""Collapse ADT section fragments that belong to the same printed source page.

The first section file remains the canonical reading-order entry. Continuation
sections are embedded into it, retained as standalone fallback files, and made
to redirect old direct links to their anchored location on the canonical page.
"""

from __future__ import annotations

import html
import json
import re
from collections import OrderedDict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PAGES_PATH = ROOT / "content/pages.json"
TOC_PATH = ROOT / "content/toc.json"
START = "<!-- BOOK_MERGED_FRAGMENTS_START -->"
END = "<!-- BOOK_MERGED_FRAGMENTS_END -->"

SECTION_RE = re.compile(r"<section\b[\s\S]*?</section>", re.IGNORECASE)
GROUP_RE = re.compile(r"(pg\d+)_sec\d+\.html$")
ANSWER_SCRIPT_RE = re.compile(
    r"\s*<script\s+type=\"text/javascript\">\s*"
    r"window\.correctAnswers\s*=\s*JSON\.parse\('(.*?)'\);\s*"
    r"</script>\s*",
    re.DOTALL,
)


def add_class(tag: str, *names: str) -> str:
    match = re.search(r'class="([^"]*)"', tag)
    if match:
        classes = match.group(1).split()
        for name in names:
            if name not in classes:
                classes.append(name)
        return tag[: match.start(1)] + " ".join(classes) + tag[match.end(1) :]
    insertion = " class=\"" + " ".join(names) + "\""
    return tag[:-1] + insertion + ">"


def prepare_section(section: str, section_id: str, position: str) -> str:
    opening = re.match(r"<section\b[^>]*>", section, re.IGNORECASE)
    if not opening:
        raise ValueError(f"Missing opening section for {section_id}")
    tag = add_class(opening.group(0), "book-page-fragment", f"book-page-fragment--{position}")
    if not re.search(r'\sid="[^"]+"', tag):
        tag = tag[:-1] + f' id="{section_id}">'
    return tag + section[opening.end() :]


def content_with_merge_class(source: str) -> str:
    match = re.search(r"<div\b[^>]*\bid=\"content\"[^>]*>", source, re.IGNORECASE)
    if not match:
        raise ValueError("Missing #content")
    tag = add_class(match.group(0), "book-merged-content")
    return source[: match.start()] + tag + source[match.end() :]


def parse_answers(source: str) -> dict[str, object]:
    answers: dict[str, object] = {}
    for encoded in re.findall(r"window\.correctAnswers\s*=\s*JSON\.parse\('(.*?)'\)", source, re.DOTALL):
        values = json.loads(html.unescape(encoded))
        for key, value in values.items():
            if key in answers and answers[key] not in (value, "", None) and value not in ("", None):
                raise ValueError(f"Conflicting answer key for {key}")
            if key not in answers or answers[key] in ("", None):
                answers[key] = value
    return answers


def add_redirect(source: str, target: str) -> str:
    source = re.sub(
        r"\s*<meta\s+name=\"book-canonical-page\"[^>]*>\s*",
        "\n",
        source,
        flags=re.IGNORECASE,
    )
    source = re.sub(
        r"\s*<script\s+data-book-page-redirect>[\s\S]*?</script>\s*",
        "\n",
        source,
        flags=re.IGNORECASE,
    )
    marker = (
        f'    <meta name="book-canonical-page" content="{target}">\n'
        f'    <script data-book-page-redirect>window.location.replace("{target}");</script>\n'
    )
    return source.replace("</head>", marker + "</head>", 1)


def main() -> None:
    pages = json.loads(PAGES_PATH.read_text(encoding="utf-8"))
    canonical_by_group: OrderedDict[str, dict] = OrderedDict()
    for entry in pages:
        match = GROUP_RE.match(entry["href"])
        if match:
            canonical_by_group.setdefault(match.group(1), entry)

    groups: OrderedDict[str, list[dict]] = OrderedDict()
    for group, canonical in canonical_by_group.items():
        files = sorted(
            ROOT.glob(f"{group}_sec*.html"),
            key=lambda path: int(re.search(r"_sec(\d+)\.html$", path.name).group(1)),
        )
        groups[group] = [
            {
                "href": path.name,
                "section_id": path.stem,
                "page_number": canonical.get("page_number"),
            }
            for path in files
        ]

    continuation_to_target: dict[str, str] = {}
    removed_hrefs: set[str] = set()
    merged_groups = 0

    for entries in groups.values():
        if len(entries) < 2:
            continue
        merged_groups += 1
        canonical_entry = entries[0]
        canonical_path = ROOT / canonical_entry["href"]
        canonical_source = canonical_path.read_text(encoding="utf-8")
        canonical_source = re.sub(
            re.escape(START) + r"[\s\S]*?" + re.escape(END),
            "",
            canonical_source,
        )

        first_match = SECTION_RE.search(canonical_source)
        if not first_match:
            raise ValueError(f"Missing section in {canonical_path.name}")

        all_sources = [canonical_source]
        fragments: list[str] = []
        first_section = prepare_section(first_match.group(0), canonical_entry["section_id"], "first")

        for continuation in entries[1:]:
            continuation_path = ROOT / continuation["href"]
            continuation_source = continuation_path.read_text(encoding="utf-8")
            section_match = SECTION_RE.search(continuation_source)
            if not section_match:
                raise ValueError(f"Missing section in {continuation_path.name}")
            fragments.append(
                prepare_section(section_match.group(0), continuation["section_id"], "continuation")
            )
            all_sources.append(continuation_source)
            target = f'{canonical_entry["href"]}#{continuation["section_id"]}'
            continuation_to_target[continuation["href"]] = target
            removed_hrefs.add(continuation["href"])
            continuation_path.write_text(add_redirect(continuation_source, target), encoding="utf-8")

        merged_markup = "\n" + START + "\n" + "\n".join(fragments) + "\n" + END
        canonical_source = (
            canonical_source[: first_match.start()]
            + first_section
            + merged_markup
            + canonical_source[first_match.end() :]
        )
        canonical_source = content_with_merge_class(canonical_source)

        answers: dict[str, object] = {}
        for source in all_sources:
            answers.update(parse_answers(source))
        canonical_source = ANSWER_SCRIPT_RE.sub("\n", canonical_source)
        if answers:
            payload = json.dumps(answers, ensure_ascii=False, separators=(",", ":"))
            script = (
                "\n    <script type=\"text/javascript\">\n"
                f"        window.correctAnswers = JSON.parse('{payload}');\n"
                "    </script>\n"
            )
            canonical_source = canonical_source.replace(
                '    <div class="relative z-50" id="interface-container"></div>',
                script + '    <div class="relative z-50" id="interface-container"></div>',
                1,
            )
        canonical_path.write_text(canonical_source, encoding="utf-8")

    collapsed_pages = [entry for entry in pages if entry["href"] not in removed_hrefs]
    PAGES_PATH.write_text(
        json.dumps(collapsed_pages, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    for position, entry in enumerate(collapsed_pages, 1):
        path = ROOT / entry["href"]
        source = path.read_text(encoding="utf-8")
        source, count = re.subn(
            r'(<meta\s+name="page-section-id"\s+content=")\d+("\s*/?>)',
            rf"\g<1>{position}\2",
            source,
            count=1,
            flags=re.IGNORECASE,
        )
        if count != 1:
            raise ValueError(f"Missing page-section-id in {entry['href']}")
        path.write_text(source, encoding="utf-8")

    toc = json.loads(TOC_PATH.read_text(encoding="utf-8"))
    for item in toc:
        if item.get("href") in continuation_to_target:
            item["href"] = continuation_to_target[item["href"]]
    TOC_PATH.write_text(json.dumps(toc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(
        f"Merged {merged_groups} source-page groups; "
        f"collapsed {len(removed_hrefs)} continuation entries; "
        f"reading order now has {len(collapsed_pages)} entries."
    )


if __name__ == "__main__":
    main()
