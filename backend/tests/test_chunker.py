"""Unit tests: markdown-aware chunker."""
from app.rag.chunker import chunk_markdown

DOC = """# Title post
metadata line

body paragraph one

## Top comments
- u/a: first comment
- u/b: second comment
"""


def test_splits_on_h1_and_h2():
    chunks = chunk_markdown("t3_x", DOC)
    assert len(chunks) == 2
    assert chunks[0].heading_path == ("Title post",)
    assert chunks[1].heading_path == ("Title post", "Top comments")
    assert chunks[0].content.startswith("# Title post")
    assert "second comment" in chunks[1].content


def test_long_section_splits_with_overlap():
    long_body = "# Big\n" + "\n".join(f"line {i} " + "word " * 20 for i in range(200))
    chunks = chunk_markdown("t3_y", long_body, target_tokens=100, overlap_tokens=20)
    assert len(chunks) > 3
    # windows overlap: each chunk (after the first) starts before the previous ended
    for prev, cur in zip(chunks, chunks[1:]):
        assert cur.start_line <= prev.end_line
    # every chunk stays under a sane multiple of the target
    assert all(c.tokens_est <= 200 for c in chunks)


def test_chunk_ids_are_stable():
    a = [c.chunk_id for c in chunk_markdown("t3_z", DOC)]
    b = [c.chunk_id for c in chunk_markdown("t3_z", DOC)]
    assert a == b
    # ids depend on the path — a different post yields different ids
    c = [c.chunk_id for c in chunk_markdown("t3_other", DOC)]
    assert a != c


def test_empty_and_whitespace_input():
    assert chunk_markdown("t3_e", "") == []
    assert chunk_markdown("t3_e", "   \n \n") == []


def test_line_ranges_cover_document():
    chunks = chunk_markdown("t3_x", DOC)
    assert chunks[0].start_line == 1
    assert chunks[-1].end_line == len(DOC.splitlines())
