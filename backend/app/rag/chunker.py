"""Markdown-aware chunker for the RAG index.

Splits at H1/H2 boundaries first (mirrors the section-split pattern from
Anthropic-course/005_hybrid.ipynb), then within long sections uses a
~target_tokens sliding window with overlap. Chunk IDs hash
(rel_path, start_line, end_line, content) so unchanged input always produces
the same IDs (re-index diffs stay surgical) while an in-place edit — e.g. a
post's score line drifting between crawls — yields a new ID and re-embeds.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

DEFAULT_TARGET_TOKENS = 400
DEFAULT_OVERLAP_TOKENS = 60

_H1 = re.compile(r"^# (.+)")
_H2 = re.compile(r"^## (.+)")


@dataclass(frozen=True)
class Chunk:
    """One retrievable passage. start_line / end_line are 1-indexed, inclusive."""

    chunk_id: str
    path: str
    heading_path: tuple[str, ...]
    start_line: int
    end_line: int
    content: str
    tokens_est: int


def chunk_markdown(
    rel_path: str,
    text: str,
    *,
    target_tokens: int = DEFAULT_TARGET_TOKENS,
    overlap_tokens: int = DEFAULT_OVERLAP_TOKENS,
) -> list[Chunk]:
    """Chunk a markdown document into stable, overlapping passages."""
    if not text.strip():
        return []
    lines = text.splitlines()
    sections = _split_by_h1_h2(lines)
    out: list[Chunk] = []
    for heading_path, sec_start, sec_lines in sections:
        out.extend(
            _chunk_section(
                rel_path=rel_path,
                heading_path=heading_path,
                sec_start_line=sec_start,
                sec_lines=sec_lines,
                target_tokens=target_tokens,
                overlap_tokens=overlap_tokens,
            )
        )
    return out


def _split_by_h1_h2(
    lines: list[str],
) -> list[tuple[tuple[str, ...], int, list[str]]]:
    sections: list[tuple[tuple[str, ...], int, list[str]]] = []
    current_h1: str | None = None
    current_heading: tuple[str, ...] = ()
    section_start = 1
    section_lines: list[str] = []

    def flush() -> None:
        if section_lines:
            sections.append((current_heading, section_start, list(section_lines)))

    for i, line in enumerate(lines, start=1):
        h1 = _H1.match(line)
        h2 = _H2.match(line)
        if h1 or h2:
            flush()
            section_lines = [line]
            section_start = i
            if h1:
                current_h1 = h1.group(1).strip()
                current_heading = (current_h1,)
            else:
                title = h2.group(1).strip()
                current_heading = (current_h1, title) if current_h1 else (title,)
        else:
            section_lines.append(line)
    flush()
    return sections


def _estimate_tokens(line: str) -> int:
    # Crude ~4 chars/token estimate; floor of 1 so empty lines still count
    # toward the budget (newlines do consume tokens at the model boundary).
    return max(1, len(line) // 4)


def _chunk_section(
    *,
    rel_path: str,
    heading_path: tuple[str, ...],
    sec_start_line: int,
    sec_lines: list[str],
    target_tokens: int,
    overlap_tokens: int,
) -> list[Chunk]:
    if not sec_lines:
        return []
    per_line = [_estimate_tokens(line) for line in sec_lines]
    total = sum(per_line)

    if total <= target_tokens:
        return [
            _make_chunk(
                rel_path=rel_path,
                heading_path=heading_path,
                start_line=sec_start_line,
                end_line=sec_start_line + len(sec_lines) - 1,
                content="\n".join(sec_lines),
                tokens_est=total,
            )
        ]

    chunks: list[Chunk] = []
    i = 0
    n = len(sec_lines)
    while i < n:
        token_acc = 0
        j = i
        while j < n and token_acc < target_tokens:
            token_acc += per_line[j]
            j += 1
        chunks.append(
            _make_chunk(
                rel_path=rel_path,
                heading_path=heading_path,
                start_line=sec_start_line + i,
                end_line=sec_start_line + j - 1,
                content="\n".join(sec_lines[i:j]),
                tokens_est=token_acc,
            )
        )
        if j >= n:
            break
        back = 0
        k = j - 1
        while k > i and back < overlap_tokens:
            back += per_line[k]
            k -= 1
        new_i = k + 1
        if new_i <= i:
            new_i = i + 1
        i = new_i
    return chunks


def _make_chunk(
    *,
    rel_path: str,
    heading_path: tuple[str, ...],
    start_line: int,
    end_line: int,
    content: str,
    tokens_est: int,
) -> Chunk:
    raw = f"{rel_path}:{start_line}-{end_line}:{content}"
    chunk_id = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]
    return Chunk(
        chunk_id=chunk_id,
        path=rel_path,
        heading_path=tuple(heading_path),
        start_line=start_line,
        end_line=end_line,
        content=content,
        tokens_est=tokens_est,
    )
