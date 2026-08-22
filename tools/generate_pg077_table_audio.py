#!/usr/bin/env python3
"""Generate the requested column-major Rehema narration for pg077's matching table."""

import asyncio
import json
import subprocess
import tempfile
from pathlib import Path

import edge_tts


VOICE = "sw-TZ-RehemaNeural"
ITEMS = (
    ("pg077_table_headers", "Vichwa vya jedwali: Sehemu A, Jibu, Sehemu B."),
    ("pg077_table_sehemu_a_1", "Sehemu A. Namba ya kirumi ya kwanza. Jua."),
    ("pg077_table_sehemu_a_2", "Sehemu A. Namba ya kirumi ya pili. Mafuta ya minyonyo."),
    ("pg077_table_sehemu_a_3", "Sehemu A. Namba ya kirumi ya tatu. Moto."),
    ("pg077_table_sehemu_a_4", "Sehemu A. Namba ya kirumi ya nne. Chumvi."),
    ("pg077_table_sehemu_a_5", "Sehemu A. Namba ya kirumi ya tano. Moshi."),
    ("pg077_table_sehemu_b_1", "Sehemu B. Herufi a. Kubanika, kuchoma, kuchemsha na kukausha."),
    ("pg077_table_sehemu_b_2", "Sehemu B. Herufi b. Kupaka na kunyunyizia."),
    ("pg077_table_sehemu_b_3", "Sehemu B. Herufi c. Kupaka."),
    ("pg077_table_sehemu_b_4", "Sehemu B. Herufi d. Kukausha."),
    ("pg077_table_sehemu_b_5", "Sehemu B. Herufi e. Kuanika na kukausha."),
)
LEGACY_IDS = (
    "pg077_n0018", "pg077_n0020", "pg077_n0022", "pg077_n0025", "pg077_n0029",
    "pg077_n0032", "pg077_n0036", "pg077_n0039", "pg077_n0043", "pg077_n0046",
    "pg077_n0050", "pg077_n0053", "pg077_n0057",
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
    audio_dir = i18n / "audio"
    texts = json.loads((i18n / "texts.json").read_text(encoding="utf-8"))
    audios = json.loads((i18n / "audios.json").read_text(encoding="utf-8"))
    retired_files = []

    for text_id in LEGACY_IDS:
        for key in (text_id, f"{text_id}_easy_read"):
            filename = audios.pop(key, None)
            if filename:
                retired_files.append(filename)

    for text_id, speech in ITEMS:
        texts[text_id] = speech
        audios[text_id] = f"{text_id}_rehema_column.mp3"

    with tempfile.TemporaryDirectory(prefix="adt-pg077-table-") as directory:
        staged = Path(directory)
        semaphore = asyncio.Semaphore(2)

        async def make(text_id: str, speech: str) -> None:
            target = staged / audios[text_id]
            async with semaphore:
                await edge_tts.Communicate(speech, VOICE).save(str(target))

        await asyncio.gather(*(make(*item) for item in ITEMS))
        invalid = [audios[text_id] for text_id, _ in ITEMS if not valid(staged / audios[text_id])]
        if invalid:
            raise RuntimeError(f"Invalid audio: {', '.join(invalid)}")
        for text_id, _ in ITEMS:
            (staged / audios[text_id]).replace(audio_dir / audios[text_id])

    for filename in retired_files:
        (audio_dir / filename).unlink(missing_ok=True)
    (i18n / "texts.json").write_text(json.dumps(texts, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (i18n / "audios.json").write_text(json.dumps(audios, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Generated {len(ITEMS)} Rehema table narrations in header, Sehemu A, Sehemu B order.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
