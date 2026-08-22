#!/usr/bin/env python3
"""Repair missing image descriptions and read-aloud mappings/files."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import tempfile
from pathlib import Path


IMAGE_DESCRIPTIONS = {
    "pg140_im001": "Mchoro wa mwanafunzi akifikiri.",
    "pg079_im001": "Mchoro wa mwanafunzi akifikiri.",
    "pg063_im001": "Mchoro wa mwanafunzi akifikiri.",
    "pg108_im001": "Mchoro wa mwanafunzi akizungumza.",
    "pg033_im003": "Kisanduku cha Kazi ya kufanya namba 7 kinachoelekeza kuwauliza wazazi au walezi kuhusu mbinu zilizotumika kutoa elimu katika jamii inayowazunguka kabla ya ukoloni.",
    "pg041_im001": "Mchoro wa mwanafunzi akifikiri.",
    "pg033_im001": "Mchoro wa mwanafunzi akizungumza.",
    "pg036_im001": "Mchoro wa mwanafunzi akizungumza.",
    "pg045_im001": "Mchoro wa mwanafunzi akiandika.",
    "pg086_im001": "Mchoro wa mwanafunzi akifikiri.",
    "pg137_im001": "Mchoro wa mwanafunzi akisoma kitabu.",
    "pg064_im001": "Mchoro wa mwanafunzi akifikiri.",
}


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def save(path: Path, value) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def update_image_alts(root: Path) -> None:
    for path in root.glob("pg*.html"):
        source = path.read_text(encoding="utf-8")
        updated = source
        for data_id, description in IMAGE_DESCRIPTIONS.items():
            if f'data-id="{data_id}"' not in updated:
                continue
            pattern = re.compile(
                rf'(<img\b(?=[^>]*data-id="{re.escape(data_id)}")[^>]*\balt=")[^"]*(")',
                re.I,
            )
            updated = pattern.sub(lambda match: match.group(1) + description + match.group(2), updated)
        if updated != source:
            path.write_text(updated, encoding="utf-8")


def referenced_text_ids(root: Path) -> set[str]:
    result: set[str] = set()
    for path in list(root.glob("pg*.html")) + list(root.glob("qz*.html")) + [root / "index.html"]:
        result.update(re.findall(r'data-id="([^"]+)"', path.read_text(encoding="utf-8")))
    return result


def generate_audio(audio_dir: Path, text_id: str, text: str, voice: str) -> None:
    destination = audio_dir / f"{text_id}.mp3"
    if destination.exists():
        return
    with tempfile.TemporaryDirectory(prefix="adt-tts-") as temporary:
        aiff = Path(temporary) / f"{text_id}.aiff"
        subprocess.run(["say", "-v", voice, "-o", str(aiff), text], check=True)
        subprocess.run(
            [
                "ffmpeg", "-loglevel", "error", "-y", "-i", str(aiff),
                "-codec:a", "libmp3lame", "-q:a", "5", str(destination),
            ],
            check=True,
        )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", nargs="?", default=".")
    parser.add_argument("--generate-audio", action="store_true")
    parser.add_argument("--voice", default="Aman")
    args = parser.parse_args()
    root = Path(args.root).resolve()
    i18n = root / "content/i18n/sw-TZ"
    text_path = i18n / "texts.json"
    audio_path = i18n / "audios.json"
    texts = load(text_path)
    audios = load(audio_path)

    texts.update(IMAGE_DESCRIPTIONS)
    update_image_alts(root)
    ids = referenced_text_ids(root)
    repaired: list[str] = []
    for text_id in sorted(ids):
        if re.fullmatch(r"qz\d+", text_id) or text_id not in texts:
            continue
        if text_id not in audios:
            audios[text_id] = f"{text_id}.mp3"
            repaired.append(text_id)

    save(text_path, texts)
    save(audio_path, audios)

    if args.generate_audio:
        audio_dir = i18n / "audio"
        for position, text_id in enumerate(repaired, 1):
            print(f"[{position}/{len(repaired)}] {text_id}")
            generate_audio(audio_dir, text_id, texts[text_id], args.voice)
    print(f"Repaired descriptions: {len(IMAGE_DESCRIPTIONS)}")
    print(f"Repaired audio mappings: {len(repaired)}")


if __name__ == "__main__":
    main()
