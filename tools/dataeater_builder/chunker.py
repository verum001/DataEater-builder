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


@dataclass
class Chunk:
    """One small piece of a document, with enough information to cite it."""

    text: str
    page_start: int
    page_end: int
    section: str = ""
    source_id: str = ""
    chunk_id: str = ""


def looks_like_heading(line: str) -> bool:
    """Is this line probably a chapter title?

    We are guessing, and a wrong guess only affects the small grey label
    next to a search result, so a simple rule is enough. Trying to be clever
    here would add bugs without adding value.
    """
    stripped = line.strip()

    if not stripped or len(stripped) > 90:
        return False

    words = stripped.split()
    if len(words) > 14:
        return False

    # "3.1 Fuel Pressure Testing"  or  "4. Routine Service"
    if words[0][:1].isdigit() and len(words[0]) <= 8 and any(c in words[0] for c in ".)-"):
        return True

    # "P0087 FUEL RAIL PRESSURE TOO LOW"  (shouting)
    if stripped.isupper() and any(c.isalpha() for c in stripped):
        return True

    # "Fuel Pressure Testing"  (Title Case, short, no ending punctuation)
    if stripped.istitle() and not stripped.endswith("."):
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

    pieces: List[str] = []
    current = ""

    # Keep the sentence terminator with the sentence it belongs to.
    for part in paragraph.replace("\n", " ").split(". "):
        sentence = part if part.endswith(".") else part + "."
        if current and len(current) + len(sentence) + 1 > max_chars:
            pieces.append(current.strip())
            current = sentence
        else:
            current = (current + " " + sentence).strip()

    if current:
        pieces.append(current.strip())

    return [p for p in pieces if p]


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
                    source_id=source_id,
                    chunk_id="c%03d" % counter,
                )
            )
            counter += 1

        buffer = []
        buffer_pages = []

    for page in pages:
        blocks = split_paragraphs(page.text)

        for block in blocks:
            lines = [ln for ln in block.split("\n") if ln.strip()]

            # A short block that looks like a title becomes the new section
            # name, and it starts a new chunk so a heading is never buried
            # in the middle of a long chunk.
            if lines and len(block) < 120 and looks_like_heading(lines[0]):
                if lines[0].strip() != current_section:
                    flush()
                    current_section = lines[0].strip()
                continue

            for piece in split_long_paragraph(block, max_chars):
                if buffer and sum(len(p) for p in buffer) + len(piece) > target_chars:
                    flush()

                buffer.append(piece)
                buffer_pages.append(page.number)

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
        if merged and len(merged[-1].text) < minimum_chars:
            previous = merged[-1]
            previous.text = previous.text + "\n\n" + chunk.text
            previous.page_end = max(previous.page_end, chunk.page_end)
        else:
            merged.append(chunk)

    return merged