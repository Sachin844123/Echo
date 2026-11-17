"""Synthetic TEST DATA only; these checks are not retrieval evaluation."""

import pytest

from app.processing.chunking import Segment, iter_chunks, token_spans
from app.processing.text import clean_text


def test_cleaning_unicode_newlines_and_controls():
    assert clean_text("  TEST\tDATA\r\ne\u0301\x00\f\r\n\r\n end  ") == "TEST DATA\né\n\nend"


def test_chunk_coverage_exact_offsets_overlap_and_no_duplicate_tail():
    text = " ".join(f"fixture{i}" for i in range(1000))
    chunks = list(iter_chunks([Segment(text, 0)], 350, 60))
    assert [chunk["token_count"] for chunk in chunks] == [350, 350, 350, 130]
    assert [chunk["chunk_index"] for chunk in chunks] == list(range(4))
    assert chunks[0]["start_offset"] == 0
    assert chunks[-1]["end_offset"] == len(text)
    for chunk in chunks:
        assert text[chunk["start_offset"]:chunk["end_offset"]] == chunk["chunk_text"]
    for left, right in zip(chunks, chunks[1:]):
        assert left["chunk_text"].split()[-60:] == right["chunk_text"].split()[:60]
    assert len(list(iter_chunks([Segment("word " * 350, 0)], 350, 60))) == 1


def test_chunks_span_streaming_records_but_not_pages_or_headings():
    segments = [Segment("one two", 0, 1, "TEST A"), Segment("three four", 9, 1, "TEST A"),
                Segment("five six", 21, 2, "TEST A"), Segment("seven eight", 31, 2, "TEST B")]
    chunks = list(iter_chunks(segments, 350, 60))
    assert [chunk["chunk_text"] for chunk in chunks] == ["one two\n\nthree four", "five six", "seven eight"]
    assert [(chunk["page_number"], chunk["heading"]) for chunk in chunks] == [(1, "TEST A"), (2, "TEST A"), (2, "TEST B")]


def test_unbroken_words_and_unicode_have_bounded_tokens():
    text = "x" * 40000 + " 世界 हिन्दी."
    spans = list(token_spans(text))
    assert all(end - start <= 32 for start, end in spans)
    chunks = list(iter_chunks([Segment(text, 0)], 350, 60))
    assert max(chunk["token_count"] for chunk in chunks) <= 350
    assert chunks[-1]["end_offset"] == len(text)


@pytest.mark.parametrize("size,overlap", [(0, 0), (10, 10), (10, -1)])
def test_invalid_chunk_settings(size, overlap):
    with pytest.raises(ValueError):
        list(iter_chunks([], size, overlap))
