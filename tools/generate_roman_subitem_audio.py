#!/usr/bin/env python3
"""Create Rehema narration for Roman-numeral sub-items without changing text."""

from __future__ import annotations

import argparse
import asyncio
import html
import json
import re
import subprocess
import tempfile
from html.parser import HTMLParser
from pathlib import Path

import edge_tts


VOICE = "sw-TZ-RehemaNeural"
ROMAN_ORDINALS = {
    "i": "kwanza", "ii": "pili", "iii": "tatu", "iv": "nne", "v": "tano",
    "vi": "sita", "vii": "saba", "viii": "nane", "ix": "tisa", "x": "kumi",
}
ROMAN_PREFIX = re.compile(
    r"^\s*\((viii|vii|vi|iv|ix|iii|ii|i|v|x)\)\s*(.*)$", re.I | re.S
)


class IdParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.ids: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if values.get("data-id"):
            self.ids.append(values["data-id"])


def page_ids(path: Path) -> list[str]:
    parser = IdParser()
    parser.feed(path.read_text(encoding="utf-8"))
    return parser.ids


def valid_mp3(path: Path) -> bool:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", str(path)],
        capture_output=True, text=True, check=False,
    )
    return result.returncode == 0 and bool(result.stdout.strip())


def add_aria_narration(source: str, text_id: str, spoken: str | None) -> str:
    pattern = re.compile(
        rf'(?P<open><(?P<tag>[A-Za-z][\w:-]*)(?P<attrs>[^>]*\bdata-id="{re.escape(text_id)}"[^>]*)>)'
        rf'(?P<body>.*?)</(?P=tag)>', re.S,
    )
    marker = f'data-roman-narration-for="{text_id}"'
    if spoken is not None and marker in source:
        return re.sub(
            rf'(<span class="sr-only" {re.escape(marker)}>).*?</span>',
            rf'\1{html.escape(spoken)}</span>',
            source,
            count=1,
            flags=re.S,
        )

    def replace(match: re.Match[str]) -> str:
        attrs = match.group("attrs")
        if 'aria-hidden="true"' not in attrs:
            attrs += ' aria-hidden="true"'
        element = f'<{match.group("tag")}{attrs}>{match.group("body")}</{match.group("tag")}>'
        if spoken is None:
            return element
        return f'{element}<span class="sr-only" {marker}>{spoken}</span>'

    updated = pattern.sub(replace, source, count=1)
    if spoken is None:
        updated = re.sub(
            rf'<span class="sr-only" {re.escape(marker)}>.*?</span>',
            "",
            updated,
            count=1,
            flags=re.S,
        )
    return updated


def build_items(root: Path, texts: dict[str, str]) -> tuple[list[tuple[str, str]], set[str], dict[Path, list[tuple[str, str | None]]]]:
    items: list[tuple[str, str]] = []
    number_only: set[str] = set()
    accessibility: dict[Path, list[tuple[str, str | None]]] = {}
    for page in sorted(root.glob("pg*_sec*.html")):
        ids = page_ids(page)
        for index, text_id in enumerate(ids):
            match = ROMAN_PREFIX.match(texts.get(text_id, ""))
            if not match:
                continue
            ordinal = ROMAN_ORDINALS[match.group(1).casefold()]
            body = match.group(2).strip()
            target_id = text_id
            if not body:
                if index + 1 >= len(ids):
                    raise RuntimeError(f"Roman numeral without following item: {text_id}")
                number_only.add(text_id)
                target_id = ids[index + 1]
                body = texts.get(target_id, "").strip()
            spoken = f"Namba ya kirumi ya {ordinal}. {body}"
            items.append((target_id, spoken))
            accessibility.setdefault(page, []).append((text_id, spoken if target_id == text_id else None))
            if target_id != text_id:
                accessibility[page].append((target_id, spoken))
    return list(dict.fromkeys(items)), number_only, accessibility


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", nargs="?", default=".")
    parser.add_argument("--concurrency", type=int, default=2)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--finalize-only", action="store_true")
    args = parser.parse_args()
    root = Path(args.root).resolve()
    i18n = root / "content/i18n/sw-TZ"
    texts_path, audios_path = i18n / "texts.json", i18n / "audios.json"
    texts = json.loads(texts_path.read_text(encoding="utf-8"))
    audios = json.loads(audios_path.read_text(encoding="utf-8"))
    standard, number_only, accessibility = build_items(root, texts)

    # Both standard and Easy Read narration begin with the same natural label.
    work: list[tuple[str, str]] = []
    for target_id, spoken in standard:
        work.append((target_id, spoken))
        easy_id = f"{target_id}_easy_read"
        easy_text = texts.get(easy_id)
        if easy_text is not None:
            match = ROMAN_PREFIX.match(easy_text)
            easy_body = (match.group(2) if match else easy_text).strip()
            work.append((easy_id, re.sub(r"\.\s*.*$", f". {easy_body}", spoken, count=1)))
    selected = work[args.offset : args.offset + args.limit if args.limit else None]

    # Standalone visual Roman tokens must not have their own queue entry.
    for text_id in number_only:
        for key in (text_id, f"{text_id}_easy_read"):
            filename = audios.pop(key, None)
            if filename:
                (i18n / "audio" / filename).unlink(missing_ok=True)

    for page, entries in accessibility.items():
        source = page.read_text(encoding="utf-8")
        updated = source
        for text_id, spoken in entries:
            updated = add_aria_narration(updated, text_id, spoken)
        if updated != source:
            page.write_text(updated, encoding="utf-8")

    if not args.finalize_only:
        with tempfile.TemporaryDirectory(prefix="adt-rehema-roman-") as tmp:
            staged = Path(tmp)
            semaphore = asyncio.Semaphore(max(1, args.concurrency))

            async def generate(text_id: str, spoken: str) -> None:
                filename = audios.get(text_id)
                if not filename:
                    raise RuntimeError(f"Missing audio mapping for {text_id}")
                target = staged / filename
                async with semaphore:
                    for attempt in range(3):
                        try:
                            await asyncio.wait_for(edge_tts.Communicate(spoken, VOICE).save(str(target)), timeout=30)
                            break
                        except Exception:
                            target.unlink(missing_ok=True)
                            if attempt == 2:
                                raise
                            await asyncio.sleep(2 * (attempt + 1))
                if not target.is_file() or target.stat().st_size < 512:
                    raise RuntimeError(f"Empty narration for {text_id}")

            await asyncio.gather(*(generate(*item) for item in selected))
            invalid = [audios[text_id] for text_id, _ in selected if not valid_mp3(staged / audios[text_id])]
            if invalid:
                raise RuntimeError(f"Invalid narration: {', '.join(invalid)}")
            for text_id, _ in selected:
                (staged / audios[text_id]).replace(i18n / "audio" / audios[text_id])

    audios_path.write_text(json.dumps(audios, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Roman sub-items: {len(standard)}; regenerated Rehema files: {len(selected)} of {len(work)}; suppressed numeral mappings: {len(number_only) * 2}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
