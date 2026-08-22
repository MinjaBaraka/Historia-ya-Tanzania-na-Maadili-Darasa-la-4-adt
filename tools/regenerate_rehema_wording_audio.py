#!/usr/bin/env python3
"""Regenerate Rehema MP3s for text entries matching a wording correction."""

from __future__ import annotations

import argparse
import asyncio
import json
import subprocess
import tempfile
from pathlib import Path

import edge_tts


VOICE = "sw-TZ-RehemaNeural"


def valid_mp3(path: Path) -> bool:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", str(path)],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode == 0 and bool(result.stdout.strip())


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", nargs="?", default=".")
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--limit", type=int, default=8)
    parser.add_argument("--concurrency", type=int, default=4)
    args = parser.parse_args()

    root = Path(args.root).resolve()
    i18n = root / "content/i18n/sw-TZ"
    texts = json.loads((i18n / "texts.json").read_text(encoding="utf-8"))
    mappings = json.loads((i18n / "audios.json").read_text(encoding="utf-8"))
    all_items = [
        (text_id, mappings[text_id], text)
        for text_id, text in texts.items()
        if "kinawasilisha" in text.casefold() and text_id in mappings
    ]
    items = all_items[args.offset : args.offset + args.limit]
    if not items:
        print("No matching narration items in this batch.")
        return 0

    with tempfile.TemporaryDirectory(prefix="adt-rehema-wording-") as tmp:
        staged = Path(tmp)
        semaphore = asyncio.Semaphore(max(1, args.concurrency))

        async def generate(text_id: str, filename: str, text: str) -> None:
            async with semaphore:
                target = staged / filename
                for attempt in range(3):
                    try:
                        await asyncio.wait_for(
                            edge_tts.Communicate(text, VOICE).save(str(target)),
                            timeout=30,
                        )
                        break
                    except Exception:
                        target.unlink(missing_ok=True)
                        if attempt == 2:
                            raise
                        await asyncio.sleep(2 * (attempt + 1))
                if not target.is_file() or target.stat().st_size < 512:
                    raise RuntimeError(f"Empty narration returned for {text_id}")

        await asyncio.gather(*(generate(*item) for item in items))
        invalid = [filename for _, filename, _ in items if not valid_mp3(staged / filename)]
        if invalid:
            raise RuntimeError(f"Invalid narration files: {', '.join(invalid)}")
        for _, filename, _ in items:
            (staged / filename).replace(i18n / "audio" / filename)

    print(f"Regenerated {len(items)} of {len(all_items)} Rehema narration files.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
