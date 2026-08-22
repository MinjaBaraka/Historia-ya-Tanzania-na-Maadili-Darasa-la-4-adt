#!/usr/bin/env python3
"""Generate natural Rehema narration for every exported Zoezi.

The visible textbook text is deliberately left unchanged.  Only the spoken
Each Zoezi heading and each numbered question gets a natural spoken form, for
example:

    Zoezi namba moja.
    Swali la kwanza. Eleza matendo yanayoashiria kubaguliwa kwa mtoto.

Azure Speech's ``sw-TZ-RehemaNeural`` voice is used so the cue and the
question are recorded as one natural utterance.
"""

from __future__ import annotations

import argparse
import html
import json
import os
import re
import sys
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


VOICE = "sw-TZ-RehemaNeural"
NUMBER_ONLY = re.compile(r"^\s*\d+\.\s*$")
NUMBERED_QUESTION = re.compile(r"^\s*\d+\.\s+(.+)$", re.S)
EXERCISE = re.compile(r"^Zoezi (?:namba|la) (\d+)|^Zoezi la jumla$", re.I)
OTHER_ACTIVITY = re.compile(r"^Kazi ya kufanya namba \d+$", re.I)
QUESTION_START = re.compile(
    r"^(?:Eleza|Andika|Orodhesha|Bainisha|Fafanua|Taja|Ainisha|Chora|Jadili|"
    r"Toa|Oanisha|Je\b|Ni\b|Hatua\b|Kuna\b|Unawezaje\b|Waulize\b)",
    re.I,
)
ORDINALS = {
    1: "kwanza", 2: "pili", 3: "tatu", 4: "nne", 5: "tano", 6: "sita",
    7: "saba", 8: "nane", 9: "tisa", 10: "kumi",
}
CARDINALS = {
    1: "moja", 2: "mbili", 3: "tatu", 4: "nne", 5: "tano",
    6: "sita", 7: "saba", 8: "nane", 9: "tisa", 10: "kumi",
}


@dataclass
class TextNode:
    text_id: str
    text: str


class DataIdParser(HTMLParser):
    """Collect text-bearing data-id elements in document order."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.stack: list[tuple[str | None, list[str]]] = []
        self.nodes: list[TextNode] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.stack.append((dict(attrs).get("data-id"), []))

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        # Images have a data-id but no visible text; their descriptions are not
        # exercise questions and are intentionally ignored.
        pass

    def handle_data(self, data: str) -> None:
        for _, chunks in self.stack:
            chunks.append(data)

    def handle_endtag(self, tag: str) -> None:
        if not self.stack:
            return
        text_id, chunks = self.stack.pop()
        if text_id:
            self.nodes.append(TextNode(text_id, " ".join("".join(chunks).split())))


def text_nodes(page: Path, translations: dict[str, str]) -> list[TextNode]:
    parser = DataIdParser()
    parser.feed(page.read_text(encoding="utf-8"))
    # Nested data-id elements duplicate their parents in the parser.  Keep the
    # leaf IDs, which are the units the reader can play independently.
    seen: set[str] = set()
    result: list[TextNode] = []
    for node in parser.nodes:
        if node.text_id in seen:
            continue
        seen.add(node.text_id)
        text = translations.get(node.text_id, node.text)
        if text.strip():
            result.append(TextNode(node.text_id, text.strip()))
    return result


def spoken_question(number: int, question: str) -> str:
    ordinal = ORDINALS.get(number, str(number))
    return f"Swali la {ordinal}. {question}"


def is_numbered_question(text: str) -> bool:
    """Exclude numbered explanatory lists such as the table on page 56."""
    return bool(QUESTION_START.match(text.strip()))


def all_numbered_questions(
    root: Path, page_filter: str | None = None, easy_read: bool = False
) -> tuple[list[tuple[str, str]], set[str]]:
    """Return every question and the standalone number tokens to suppress.

    The reader queues every ``data-id`` with an audio mapping.  A number in a
    separate span must therefore have *no* mapping; the following question
    audio carries the spoken ordinal instead.
    """
    translations = json.loads(
        (root / "content/i18n/sw-TZ/texts.json").read_text(encoding="utf-8")
    )
    suffix = "_easy_read" if easy_read else ""
    questions: list[tuple[str, str]] = []
    number_tokens: set[str] = set()
    for page in sorted(root.glob("pg*_sec001.html")):
        if page_filter and page.stem != page_filter:
            continue
        nodes = text_nodes(page, translations)
        for index, node in enumerate(nodes):
            text_id = f"{node.text_id}{suffix}"
            text = translations.get(text_id, node.text).strip()
            inline = NUMBERED_QUESTION.fullmatch(text)
            if inline and is_numbered_question(inline.group(1)):
                number = int(text.split(".", 1)[0])
                questions.append((text_id, spoken_question(number, inline.group(1))))
                continue
            if not NUMBER_ONLY.fullmatch(node.text) or index + 1 >= len(nodes):
                continue
            following = nodes[index + 1]
            following_id = f"{following.text_id}{suffix}"
            following_text = translations.get(following_id, following.text).strip()
            # In this export, a standalone numeral is used only as the visual
            # marker for an activity question. Its following text may be a
            # question sentence, an imperative, or a short task prompt, so do
            # not infer the role solely from the first word.
            number = int(node.text.rstrip(". "))
            questions.append((following_id, spoken_question(number, following_text)))
            number_tokens.add(text_id)
    return list(dict.fromkeys(questions)), number_tokens


def apply_question_accessibility(
    root: Path, page_filter: str | None = None
) -> int:
    """Keep visual numerals out of the accessibility reading stream.

    A numbered question can be split between a numeral element and a question
    element, or it can be held in one element. In both cases the visual text
    remains unchanged, while the screen-reader-only alternative starts with
    the natural spoken cue (``Swali la kwanza``). This mirrors the Rehema
    audio and prevents assistive technology from announcing the raw numeral
    as a separate item.
    """
    questions, number_tokens = all_numbered_questions(root, page_filter)
    spoken_by_id = dict(questions)
    changed = 0

    def replace_element(source: str, text_id: str, spoken: str | None) -> str:
        escaped_id = re.escape(text_id)
        pattern = re.compile(
            rf'(?P<open><(?P<tag>[A-Za-z][\w:-]*)(?P<attrs>[^>]*\bdata-id="{escaped_id}"[^>]*)>)'
            rf'(?P<body>.*?)</(?P=tag)>',
            re.S,
        )

        def replacement(match: re.Match[str]) -> str:
            attrs = match.group("attrs")
            if 'aria-hidden="true"' not in attrs:
                attrs += ' aria-hidden="true"'
            element = f'<{match.group("tag")}{attrs}>{match.group("body")}</{match.group("tag")}>'
            if spoken is None:
                return element
            marker = f'data-question-narration-for="{text_id}"'
            if marker in source:
                return element
            return (
                f'{element}<span class="sr-only" {marker}>'
                f'{html.escape(spoken)}</span>'
            )

        return pattern.sub(replacement, source, count=1)

    for page in sorted(root.glob("pg*_sec001.html")):
        if page_filter and page.stem != page_filter:
            continue
        source = page.read_text(encoding="utf-8")
        updated = source
        # Hide the independent visual numeral first, then add one complete
        # spoken alternative for the question itself.
        for text_id in number_tokens:
            if text_id.startswith(f"{page.stem[:-7]}_"):
                updated = replace_element(updated, text_id, None)
        for text_id, spoken in spoken_by_id.items():
            if text_id.startswith(f"{page.stem[:-7]}_"):
                updated = replace_element(updated, text_id, spoken)
        if updated != source:
            page.write_text(updated, encoding="utf-8")
            changed += 1
    return changed


def spoken_heading(title: str) -> str:
    match = EXERCISE.fullmatch(title.strip())
    if not match:
        raise ValueError(f"Not an exercise title: {title}")
    if match.group(1) is None:
        return "Zoezi la jumla."
    number = int(match.group(1))
    return f"Zoezi namba {CARDINALS.get(number, str(number))}."


def spoken_segments(
    root: Path, page_filter: str | None = None, easy_read: bool = False
) -> list[tuple[str, str]]:
    translations = json.loads(
        (root / "content/i18n/sw-TZ/texts.json").read_text(encoding="utf-8")
    )
    suffix = "_easy_read" if easy_read else ""
    segments: list[tuple[str, str]] = []
    for page in sorted(root.glob("pg*_sec001.html")):
        if page_filter and page.stem != page_filter:
            continue
        exercise: str | None = None
        nodes = text_nodes(page, translations)
        for index, node in enumerate(nodes):
            text_id = f"{node.text_id}{suffix}"
            spoken_text = translations.get(text_id, node.text)
            if EXERCISE.fullmatch(spoken_text):
                segments.append((text_id, spoken_heading(spoken_text)))
                exercise = node.text.lower()
                continue
            # A "Kazi ya kufanya" can appear after an exercise on the same
            # exported page and has its own numbered list.  It is not a
            # "Zoezi", so it must not inherit the preceding exercise cue.
            if OTHER_ACTIVITY.fullmatch(node.text):
                exercise = None
                continue
            if exercise is None:
                continue
            match = NUMBERED_QUESTION.fullmatch(spoken_text)
            if match:
                number = int(spoken_text.split(".", 1)[0])
                segments.append((text_id, spoken_question(number, match.group(1))))
                continue
            if NUMBER_ONLY.fullmatch(node.text) and index + 1 < len(nodes):
                following = nodes[index + 1]
                if not NUMBER_ONLY.fullmatch(following.text) and not EXERCISE.fullmatch(following.text):
                    number = int(node.text.rstrip(". "))
                    following_id = f"{following.text_id}{suffix}"
                    following_text = translations.get(following_id, following.text)
                    segments.append(
                        (following_id, spoken_question(number, following_text))
                    )
    # Some pages reuse structural wrappers, so retain the first spoken value
    # for each text ID while preserving reading order.
    return list(dict.fromkeys(segments))


def synthesize_azure(text: str, destination: Path, key: str, region: str) -> None:
    ssml = (
        '<speak version="1.0" xml:lang="sw-TZ">'
        f'<voice name="{VOICE}">{html.escape(text)}</voice></speak>'
    )
    request = Request(
        f"https://{region}.tts.speech.microsoft.com/cognitiveservices/v1",
        data=ssml.encode("utf-8"),
        headers={
            "Ocp-Apim-Subscription-Key": key,
            "Content-Type": "application/ssml+xml",
            "X-Microsoft-OutputFormat": "audio-24khz-48kbitrate-mono-mp3",
            "User-Agent": "adt-exercise-audio-generator",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=60) as response:
            audio = response.read()
    except HTTPError as error:
        raise RuntimeError(f"Azure Speech rejected the request ({error.code}).") from error
    except URLError as error:
        raise RuntimeError(f"Could not reach Azure Speech: {error.reason}") from error
    if not audio:
        raise RuntimeError("Azure Speech returned an empty audio response.")
    destination.write_bytes(audio)


async def synthesize_edge(text: str, destination: Path) -> None:
    try:
        import edge_tts
    except ImportError as error:
        raise RuntimeError(
            "edge-tts is required for keyless Rehema narration."
        ) from error
    await edge_tts.Communicate(text, VOICE).save(str(destination))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", nargs="?", default=".")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--page",
        help="Section ID to regenerate, for example pg012_sec001. Defaults to the full book.",
    )
    parser.add_argument(
        "--easy-read",
        action="store_true",
        help="Regenerate Easy Read variants in addition to standard narration.",
    )
    parser.add_argument(
        "--all-numbered-questions",
        action="store_true",
        help="Include numbered questions in every activity type and suppress standalone number narration.",
    )
    parser.add_argument(
        "--finalize-only",
        action="store_true",
        help="Apply mappings and accessibility changes without contacting a speech service.",
    )
    parser.add_argument("--region", default=os.getenv("SPEECH_REGION"))
    parser.add_argument("--key", default=os.getenv("SPEECH_KEY"))
    parser.add_argument(
        "--provider", choices=("edge", "azure"), default="edge",
        help="Use Microsoft Edge Read Aloud (no key) or Azure Speech.",
    )
    parser.add_argument(
        "--concurrency", type=int, default=8,
        help="Maximum simultaneous Edge Read Aloud requests.",
    )
    args = parser.parse_args()

    root = Path(args.root).resolve()
    segments = spoken_segments(root, args.page)
    if args.easy_read:
        segments += spoken_segments(root, args.page, easy_read=True)
    suppressed_tokens: set[str] = set()
    if args.all_numbered_questions:
        all_questions, standard_tokens = all_numbered_questions(root, args.page)
        segments += all_questions
        suppressed_tokens.update(standard_tokens)
        if args.easy_read:
            easy_questions, easy_tokens = all_numbered_questions(
                root, args.page, easy_read=True
            )
            segments += easy_questions
            suppressed_tokens.update(easy_tokens)
    # A page can lack an Easy Read mapping. Keep the standard segment and
    # discard only duplicate IDs while preserving the PDF reading order.
    segments = list(dict.fromkeys(segments))
    if not segments:
        print("No Zoezi narration found.", file=sys.stderr)
        return 1
    for text_id, spoken in segments:
        print(f"{text_id}: {spoken}")
    if args.dry_run:
        print(f"\nWould regenerate {len(segments)} files with {VOICE}.")
        if suppressed_tokens:
            print(f"Would suppress {len(suppressed_tokens)} standalone number tokens.")
            print("Would add screen-reader narration that starts with 'Swali la …'.")
        return 0
    if args.finalize_only:
        if not args.all_numbered_questions:
            print("--finalize-only requires --all-numbered-questions.", file=sys.stderr)
            return 2
        i18n = root / "content/i18n/sw-TZ"
        mappings = json.loads((i18n / "audios.json").read_text(encoding="utf-8"))
        audio_dir = i18n / "audio"
        for text_id in suppressed_tokens:
            filename = mappings.pop(text_id, None)
            if filename and (audio_dir / filename).exists():
                (audio_dir / filename).unlink()
        for text_id, _ in segments:
            mappings.setdefault(text_id, f"{text_id}.mp3")
        (i18n / "audios.json").write_text(
            json.dumps(mappings, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        pages_changed = apply_question_accessibility(root, args.page)
        print(
            f"Suppressed {len(suppressed_tokens)} standalone number tokens and "
            f"updated {pages_changed} page(s)."
        )
        return 0
    if args.provider == "azure" and (not args.key or not args.region):
        print(
            "SPEECH_KEY and SPEECH_REGION are required to create Rehema audio. "
            "Run again with --dry-run to inspect the affected questions.",
            file=sys.stderr,
        )
        return 2

    i18n = root / "content/i18n/sw-TZ"
    mappings = json.loads((i18n / "audios.json").read_text(encoding="utf-8"))
    audio_dir = i18n / "audio"
    for text_id in suppressed_tokens:
        filename = mappings.pop(text_id, None)
        if filename:
            audio_path = audio_dir / filename
            if audio_path.exists():
                audio_path.unlink()
    for text_id, _ in segments:
        mappings.setdefault(text_id, f"{text_id}.mp3")
    if args.provider == "edge":
        import asyncio

        async def generate_all() -> None:
            limiter = asyncio.Semaphore(max(1, args.concurrency))

            async def generate(position: int, text_id: str, spoken: str) -> None:
                async with limiter:
                    print(f"[{position}/{len(segments)}] {text_id}", flush=True)
                    await synthesize_edge(spoken, audio_dir / mappings[text_id])

            await asyncio.gather(
                *(generate(position, text_id, spoken) for position, (text_id, spoken) in enumerate(segments, 1))
            )

        asyncio.run(generate_all())
    else:
        for position, (text_id, spoken) in enumerate(segments, 1):
            print(f"[{position}/{len(segments)}] {text_id}")
            synthesize_azure(spoken, audio_dir / mappings[text_id], args.key, args.region)
    (i18n / "audios.json").write_text(
        json.dumps(mappings, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    if args.all_numbered_questions:
        pages_changed = apply_question_accessibility(root, args.page)
        print(f"Updated accessibility narration on {pages_changed} page(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
