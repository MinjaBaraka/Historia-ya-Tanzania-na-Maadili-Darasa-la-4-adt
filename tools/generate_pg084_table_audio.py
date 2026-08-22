#!/usr/bin/env python3
"""Generate pg084 table audio: headers, full Sehemu A, then full Sehemu B."""

import asyncio
import json
import subprocess
import tempfile
from pathlib import Path

import edge_tts


VOICE = "sw-TZ-RehemaNeural"
ITEMS = (
    ("pg084_table_headers", "Vichwa vya jedwali: Sehemu A, Jibu, Sehemu B."),
    ("pg084_table_sehemu_a_1", "Sehemu A. Namba ya kirumi ya kwanza. Sayansi na teknolojia za asili."),
    ("pg084_table_sehemu_a_2", "Sehemu A. Namba ya kirumi ya pili. Ufinyanzi."),
    ("pg084_table_sehemu_a_3", "Sehemu A. Namba ya kirumi ya tatu. Zana za chuma."),
    ("pg084_table_sehemu_a_4", "Sehemu A. Namba ya kirumi ya nne. Sayansi na teknolojia ya asili ya uhifadhi vitu."),
    ("pg084_table_sehemu_a_5", "Sehemu A. Namba ya kirumi ya tano. Ususi."),
    ("pg084_table_sehemu_b_1", "Sehemu B. Herufi a. Matumizi ya moto, moshi, jua au mafuta."),
    ("pg084_table_sehemu_b_2", "Sehemu B. Herufi b. Uboreshaji wa zana za kilimo, mifugo na uvuvi."),
    ("pg084_table_sehemu_b_3", "Sehemu B. Herufi c. Vyungu, mitungi na bakuli."),
    ("pg084_table_sehemu_b_4", "Sehemu B. Herufi d. Ukindu, makuti, matenga na madema."),
    ("pg084_table_sehemu_b_5", "Sehemu B. Herufi e. Matumizi ya maarifa na ujuzi wa asili na rasilimali asilia katika maendeleo."),
)
LEGACY_IDS = (
    "pg084_n0009", "pg084_n0011", "pg084_n0013", "pg084_n0016", "pg084_n0019",
    "pg084_n0022", "pg084_n0025", "pg084_n0028", "pg084_n0031", "pg084_n0034",
    "pg084_n0037", "pg084_n0040", "pg084_n0043",
)


def valid(path: Path) -> bool:
    return subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", str(path)],
        capture_output=True, text=True, check=False,
    ).returncode == 0


async def main() -> int:
    root = Path(".").resolve()
    i18n = root / "content/i18n/sw-TZ"
    audio_dir = i18n / "audio"
    texts = json.loads((i18n / "texts.json").read_text(encoding="utf-8"))
    audios = json.loads((i18n / "audios.json").read_text(encoding="utf-8"))
    retired = []
    for text_id in LEGACY_IDS:
        for key in (text_id, f"{text_id}_easy_read"):
            filename = audios.pop(key, None)
            if filename:
                retired.append(filename)
    for text_id, text in ITEMS:
        texts[text_id] = text
        audios[text_id] = f"{text_id}_rehema_column.mp3"

    with tempfile.TemporaryDirectory(prefix="adt-pg084-table-") as directory:
        staged = Path(directory)
        semaphore = asyncio.Semaphore(2)
        async def make(text_id: str, speech: str) -> None:
            async with semaphore:
                await edge_tts.Communicate(speech, VOICE).save(str(staged / audios[text_id]))
        await asyncio.gather(*(make(*item) for item in ITEMS))
        invalid = [audios[key] for key, _ in ITEMS if not valid(staged / audios[key])]
        if invalid:
            raise RuntimeError(f"Invalid audio: {', '.join(invalid)}")
        for key, _ in ITEMS:
            (staged / audios[key]).replace(audio_dir / audios[key])
    for filename in retired:
        (audio_dir / filename).unlink(missing_ok=True)
    (i18n / "texts.json").write_text(json.dumps(texts, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (i18n / "audios.json").write_text(json.dumps(audios, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Generated {len(ITEMS)} Rehema table narrations in column order.")


if __name__ == "__main__":
    asyncio.run(main())
