"""Bounded lexical-token windows. No embedding tokenizer/model is loaded in M2."""

import json
import re
from collections import deque
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from itertools import islice
from pathlib import Path

TOKEN = re.compile(r"\w+|[^\w\s]", re.UNICODE)


@dataclass(frozen=True)
class Segment:
    text: str
    start: int
    page_number: int | None = None
    heading: str | None = None


def read_segments(path: Path) -> Iterator[Segment]:
    offset = 0
    with path.open("r", encoding="utf-8") as stream:
        for line in stream:
            record = json.loads(line)
            yield Segment(record["text"], offset, record["page_number"], record["heading"])
            offset += len(record["text"]) + 2  # Segments join with two newlines.


def token_spans(text: str) -> Iterator[tuple[int, int]]:
    for match in TOKEN.finditer(text):
        # Bound pathological unbroken words and whitespace-free scripts.
        for start in range(match.start(), match.end(), 32):
            yield start, min(start + 32, match.end())


def iter_chunks(segments: Iterable[Segment], size: int = 350, overlap: int = 60) -> Iterator[dict]:
    if size < 1 or not 0 <= overlap < size:
        raise ValueError("require 0 <= overlap < size")
    buffer = ""
    base = 0
    metadata = None
    index = 0
    window = deque()

    def result(spans, page_heading):
        start, end = spans[0][0], spans[-1][1]
        return {
            "chunk_index": index, "chunk_text": buffer[start - base:end - base], "token_count": len(spans),
            "page_number": page_heading[0], "heading": page_heading[1],
            "start_offset": start, "end_offset": end,
        }

    for segment in segments:
        current = (segment.page_number, segment.heading)
        if metadata != current and buffer:
            if window:
                yield result(list(window), metadata)
                index += 1
            window.clear()
            buffer = ""
        if not buffer:
            base = segment.start
        else:
            buffer += "\n\n"
        buffer += segment.text
        metadata = current
        for start, end in token_spans(segment.text):
            window.append((segment.start + start, segment.start + end))
            if len(window) > size:
                yield result(list(islice(window, size)), metadata)
                index += 1
                for _ in range(size - overlap):
                    window.popleft()
        # Trim only once per segment, avoiding quadratic copying for long paragraphs.
        if window:
            advance = window[0][0] - base
            buffer = buffer[advance:]
            base += advance
    if window:
        yield result(list(window), metadata)
