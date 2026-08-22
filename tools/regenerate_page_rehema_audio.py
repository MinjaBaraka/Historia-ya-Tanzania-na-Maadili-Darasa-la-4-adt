#!/usr/bin/env python3
"""Replace every mapped narration for one page with Rehema Natural sw-TZ audio."""

import argparse
import asyncio
import json
import subprocess
import tempfile
from pathlib import Path

import edge_tts


VOICE = "sw-TZ-RehemaNeural"


def valid(path: Path) -> bool:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", str(path)],
        capture_output=True, text=True, check=False,
    )
    return result.returncode == 0 and bool(result.stdout.strip())


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("page_id", help="Page prefix, for example pg080")
    args = parser.parse_args()

    root = Path(".").resolve()
    i18n = root / "content/i18n/sw-TZ"
    audio_dir = i18n / "audio"
    texts = json.loads((i18n / "texts.json").read_text(encoding="utf-8"))
    audios = json.loads((i18n / "audios.json").read_text(encoding="utf-8"))
    items = [(key, texts[key]) for key in sorted(audios) if key.startswith(f"{args.page_id}_") and key in texts]
    if not items:
        raise SystemExit(f"No mapped text was found for {args.page_id}.")

    old_filenames = {key: audios[key] for key, _ in items}
    for key, _ in items:
        audios[key] = f"{key}_rehema.mp3"

    with tempfile.TemporaryDirectory(prefix=f"adt-{args.page_id}-rehema-") as directory:
        staged = Path(directory)
        semaphore = asyncio.Semaphore(2)

        async def generate(key: str, speech: str) -> None:
            target = staged / audios[key]
            async with semaphore:
                await edge_tts.Communicate(speech, VOICE).save(str(target))

        await asyncio.gather(*(generate(*item) for item in items))
        invalid = [audios[key] for key, _ in items if not valid(staged / audios[key])]
        if invalid:
            raise RuntimeError(f"Invalid audio: {', '.join(invalid)}")
        for key, _ in items:
            (staged / audios[key]).replace(audio_dir / audios[key])

    for filename in old_filenames.values():
        if filename not in audios.values():
            (audio_dir / filename).unlink(missing_ok=True)
    (i18n / "audios.json").write_text(json.dumps(audios, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Replaced {len(items)} {args.page_id} narrations with Rehema Natural sw-TZ audio.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
