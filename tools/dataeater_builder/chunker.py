"""Turning extracted document text into small pieces ("chunks").

This is the heart of the builder, and it is deliberately free of any
third-party library, so it can be tested on its own in a second.

WHY CHUNK AT ALL?
    A language model cannot read a 400 page manual. It can only be given a
    few hundred words at a time. Chunking is how a big manual becomes
    something the AI can actually use.

WHY NOT CUT A PAGE INTO FIXED BLOCKS OF CHARACTERS?
    Because that would cut sentences, and half the time it would cut a
    table row in half, or separate a fault code from its description.
    This module therefore cuts only at paragraph boundaries and keeps whole
    paragraphs together wherever it can.

PAGE NUMBERS ARE NEVER GUESSED
    Every chunk records the exact page range it came from, taken from the
    extractor. The application later prints that page number to the user as
    a citation. A wrong page number is worse than no page number.
"""

import re
from dataclasses import dataclass, field
from typing import List, Optional

# How long we aim for one chunk. Roughly 150-200 words of English, which
# is small enough for a 1B-parameter model to actually use.
DEFAULT_TARGET_CHARS = 700

# A chunk may grow a little beyond the target when a single paragraph is
# longer than the target, but never past this.
DEFAULT_MAX_CHARS = 1200


@dataclass
class Page:
    """One page of a document, as produced by an extractor."""

    number: int          # 1-based page number in the original document
    text: str
    section_paths: dict = field(default_factory=dict)
    default_section_path: str = ""


@dataclass
class Chunk:
    """One small piece of a document, with enough information to cite it."""

    text: str
    page_start: int
    page_end: int
    section: str = ""
    source_id: str = ""
    chunk_id: str = ""
    search_context: str = ""


def looks_like_heading(line: str) -> bool:
    """Is this line probably a chapter title?

    We are guessing, and a wrong guess only affects the small grey label
    next to a search result, so a simple rule is enough. Trying to be clever
    here would add bugs without adding value.
    """
    stripped = line.strip()

    if not stripped or len(stripped) > 90 or not any(c.isalpha() for c in stripped):
        return False

    if any(symbol in stripped for symbol in "=×÷Ω") or stripped.lower() in {"if", "then", "where:", "where", "equation 1", "equation 2"}:
        return False
    words = stripped.split()
    if len(words) > 14:
        return False

    # "3.1 Fuel Pressure Testing"  or  "4. Routine Service"
    if words[0][:1].isdigit() and len(words[0]) <= 8 and any(c in words[0] for c in ".)-"):
        return True

    # "P0087 FUEL RAIL PRESSURE TOO LOW"  (shouting)
    if stripped.isupper() and sum(c.isalpha() for c in stripped) >= 4:
        return True

    # "Fuel Pressure Testing"  (Title Case, short, no ending punctuation)
    title_words = re.findall(r"[^\W\d_]+(?:[’'][^\W\d_]+)?", stripped, re.UNICODE)
    if (title_words and all(word[0].isupper() and word[1:].islower() for word in title_words)
            and not stripped.endswith((".", ":")) and not any(c.isdigit() for c in stripped)
            and (len(title_words) >= 2 or len(stripped) >= 5)):
        return True

    return False


def split_paragraphs(page_text: str) -> List[str]:
    """Split one page into paragraphs, dropping empty ones."""
    parts = page_text.replace("\r\n", "\n").replace("\r", "\n").split("\n\n")
    return [p.strip() for p in parts if p.strip()]


def split_long_paragraph(paragraph: str, max_chars: int) -> List[str]:
    """Break one oversized paragraph at sentence boundaries.

    Only used when a single paragraph is longer than a whole chunk, which
    happens with badly formatted PDFs. Cutting at a full stop is much safer
    than cutting at an arbitrary character.
    """
    if len(paragraph) <= max_chars:
        return [paragraph]

    if max_chars <= 0:
        raise ValueError("max_chars must be positive")
    # Preserve punctuation, decimal values and line/table boundaries. Oversized
    # sentences are retained as a unit: silent truncation would lose warnings.
    units = re.split(r"(?<=[.!?])\s+(?=[A-Z])|\n", paragraph)
    pieces: List[str] = []
    current = ""
    for unit in units:
        if not unit.strip():
            continue
        if current and len(current) + len(unit) + 1 > max_chars:
            pieces.append(current)
            current = ""
        current = current + ("\n" if current else "") + unit
    if current:
        pieces.append(current)
    return pieces


def chunk_pages(
    pages: List[Page],
    target_chars: int = DEFAULT_TARGET_CHARS,
    max_chars: int = DEFAULT_MAX_CHARS,
    source_id: str = "",
    start_number: int = 1,
) -> List[Chunk]:
    """Split a whole document into chunks.

    Walks the pages in order, keeps the current chapter heading, and packs
    whole paragraphs into chunks until the target size is reached.
    """
    chunks: List[Chunk] = []
    current_section = ""
    current_context = ""
    counter = start_number

    buffer: List[str] = []
    buffer_pages: List[int] = []

    def flush() -> None:
        """Turn whatever has been collected into one chunk."""
        nonlocal buffer, buffer_pages, counter
        if not buffer:
            return

        text = "\n\n".join(buffer).strip()
        if text:
            chunks.append(
                Chunk(
                    text=text,
                    page_start=min(buffer_pages),
                    page_end=max(buffer_pages),
                    section=current_section,
                    search_context=current_context,
                    source_id=source_id,
                    chunk_id="c%03d" % counter,
                )
            )
            counter += 1

        buffer = []
        buffer_pages = []

    def add_block(block: str, page_number: int) -> None:
        for piece in split_long_paragraph(block, max_chars):
            if buffer and sum(len(p) for p in buffer) + len(piece) + 2 * len(buffer) > target_chars:
                flush()
            buffer.append(piece)
            buffer_pages.append(page_number)

    for page in pages:
        flush()
        if page.default_section_path:
            current_context = page.default_section_path
            current_section = current_context.split(" > ")[-1]
        for block in split_paragraphs(page.text):
            segment: List[str] = []
            # Plain PDF exports often have no empty line around a heading.
            # Recognise conservative text headings without treating equations
            # or short variables as chapters. Every line remains in the body.
            for line in block.split("\n"):
                normalized = " ".join(line.split())
                if normalized in page.section_paths or (not page.section_paths and not page.default_section_path and looks_like_heading(line)):
                    if segment:
                        add_block("\n".join(segment), page.number)
                    flush()
                    current_section = line.strip()
                    current_context = page.section_paths.get(normalized, current_context)
                    segment = [line]
                else:
                    segment.append(line)
            if segment:
                add_block("\n".join(segment), page.number)

    flush()

    return chunks


def merge_short_chunks(chunks: List[Chunk], minimum_chars: int = 200) -> List[Chunk]:
    """Join runs of very small chunks.

    A database where every chunk is one sentence is bad for both search and
    for the AI: the AI needs enough surrounding words to understand the
    answer, and short fragments match too many searches.
    """
    merged: List[Chunk] = []

    for chunk in chunks:
        if (merged and len(merged[-1].text) < minimum_chars
                and merged[-1].source_id == chunk.source_id
                and merged[-1].section == chunk.section
                and merged[-1].search_context == chunk.search_context
                and merged[-1].page_end == chunk.page_start
                and len(merged[-1].text) + len(chunk.text) + 2 <= DEFAULT_MAX_CHARS):
            previous = merged[-1]
            previous.text = previous.text + "\n\n" + chunk.text
            previous.page_end = max(previous.page_end, chunk.page_end)
        else:
            merged.append(chunk)

    return merged