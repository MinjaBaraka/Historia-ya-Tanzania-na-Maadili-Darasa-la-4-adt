#!/usr/bin/env python3
"""Regenerate pg056 table-cell narration in row-major order with headings."""

import asyncio
import json
import subprocess
import tempfile
from pathlib import Path

import edge_tts

VOICE = "sw-TZ-RehemaNeural"
COLUMNS = (
    ("Zama za Mawe za Kale", ("pg056_n0017", "pg056_n0020", "pg056_n0022", "pg056_n0024")),
    ("Zama za Mawe za Kati", ("pg056_n0030", "pg056_n0032", "pg056_n0035", "pg056_n0038")),
    ("Zama za Mawe za Mwisho", ("pg056_n0042", "pg056_n0044", "pg056_n0046", "pg056_n0049")),
)


def valid(path: Path) -> bool:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", str(path)],
        capture_output=True, text=True, check=False,
    )
    return result.returncode == 0 and bool(result.stdout.strip())


async def main() -> int:
    root = Path(".").resolve()
    i18n = root / "content/i18n/sw-TZ"
    texts = json.loads((i18n / "texts.json").read_text(encoding="utf-8"))
    audios = json.loads((i18n / "audios.json").read_text(encoding="utf-8"))
    original_audios = dict(audios)
    items = []
    for row in range(4):
        for heading, cells in COLUMNS:
            text_id = cells[row]
            for key in (text_id, f"{text_id}_easy_read"):
                if key in audios and key in texts:
                    # A distinct filename prevents an already-open reader from
                    # serving the previous MP3 from its browser cache.
                    audios[key] = f"{key}_rehema_table.mp3"
                    items.append((key, f"{heading}. {texts[key]}"))
    async with asyncio.timeout(180):
        with tempfile.TemporaryDirectory(prefix="adt-pg056-table-") as directory:
            staged = Path(directory)
            semaphore = asyncio.Semaphore(2)
            async def make(text_id: str, speech: str) -> None:
                target = staged / audios[text_id]
                async with semaphore:
                    for attempt in range(3):
                        try:
                            await asyncio.wait_for(edge_tts.Communicate(speech, VOICE).save(str(target)), timeout=30)
                            return
                        except Exception:
                            target.unlink(missing_ok=True)
                            if attempt == 2:
                                raise
                            await asyncio.sleep(2 * (attempt + 1))
            await asyncio.gather(*(make(*item) for item in items))
            invalid = [audios[text_id] for text_id, _ in items if not valid(staged / audios[text_id])]
            if invalid:
                raise RuntimeError(f"Invalid audio: {', '.join(invalid)}")
            for text_id, _ in items:
                (staged / audios[text_id]).replace(i18n / "audio" / audios[text_id])
    for text_id, _ in items:
        old_filename = original_audios.get(text_id)
        if old_filename and old_filename != audios[text_id]:
            (i18n / "audio" / old_filename).unlink(missing_ok=True)
    (i18n / "audios.json").write_text(
        json.dumps(audios, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"Regenerated {len(items)} Rehema table-cell narrations in row-major order.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
