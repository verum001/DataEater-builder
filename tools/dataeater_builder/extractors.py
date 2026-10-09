"""Getting plain text out of the files a database owner supplies.

Three input types are supported, in order of how much trouble they cause:

  .txt   trivial
  .md    trivial
  .pdf   usually fine, BUT sometimes the PDF is only a photograph of a
         page, with no text in it at all. Those need OCR first.

THE IMPORTANT PART: TELLING THE USER WHEN A PDF IS A PHOTOGRAPH
    If a PDF contains only images, extraction quietly produces almost no
    text and the resulting database looks empty. The user then blames the
    tool. So this module measures what it found and reports plainly:

        "This PDF looks like a scan: average 76 characters per page.
         Run it through OCRmyPDF first."

That single warning prevents the most common way a database build fails.

Extracted text is returned page by page so that page numbers stay exact.
A wrong page number would become a wrong citation in the app.
"""

import os
from dataclasses import dataclass, field
from typing import List, Optional

from .chunker import Page

SUPPORTED_EXTENSIONS = (".txt", ".md", ".markdown", ".pdf")

# If a page has fewer characters than this on average, the PDF is almost
# certainly a scan (photographs of pages) and has no text layer at all.
SCANNED_PAGE_CHARACTER_LIMIT = 200


@dataclass
class ExtractedDocument:
    """Everything we managed to get out of one source file."""

    path: str
    title: str
    pages: List[Page] = field(default_factory=list)
    needs_ocr: bool = False
    warning: str = ""
    total_pages: int = 0
    blank_pages: int = 0

    @property
    def character_count(self) -> int:
        return sum(len(page.text) for page in self.pages)

    @property
    def average_characters_per_page(self) -> int:
        if not self.pages:
            return 0
        return self.character_count // len(self.pages)


# A page carrying less than this is treated as blank. Manuals often print a
# copyright line or a page number on otherwise empty pages.
MIN_USEFUL_PAGE_CHARACTERS = 100


def choose_title(path: str, metadata_title: str) -> str:
    """Pick the most useful title.

    PDF metadata titles are unreliable. Real examples from the test files:

        'IN1-4GB'   <- a document code, useless to a person
        'Kobelco RK250 5'  <- a real title

    So a short title made only of letters, digits, dashes and spaces is
    treated as a code and the file name is used instead.
    """
    candidate = (metadata_title or "").strip()

    if candidate and len(candidate) > 6 and not candidate.isupper():
        return candidate

    return _title_from_path(path)


def is_supported(path: str) -> bool:
    return os.path.splitext(path)[1].lower() in SUPPORTED_EXTENSIONS


def clean_text(text: str) -> str:
    """Tidy up text without destroying its meaning.

    Deliberately conservative. We collapse runaway whitespace and strip
    control characters, but we never reword, re-spell or join paragraphs,
    because every change we make here is a chance to corrupt a part number.
    """
    text = text.replace("\r\n", "\n").replace("\r", "\n")

    # Control characters that some PDFs embed and that confuse everything
    # downstream. Tab is kept because tables rely on it.
    text = "".join(
        character
        for character in text
        if character == "\n" or character == "\t" or ord(character) >= 32
    )

    # Tidy the line endings: no more than two newlines in a row, and no
    # trailing spaces at the end of a line.
    lines = [line.rstrip() for line in text.split("\n")]
    output: List[str] = []
    blanks = 0
    for line in lines:
        if line:
            blanks = 0
            output.append(line)
        else:
            blanks += 1
            if blanks <= 1:
                output.append("")
    return "\n".join(output).strip()


def _title_from_path(path: str) -> str:
    """A readable title when the file does not carry one."""
    name = os.path.splitext(os.path.basename(path))[0]
    return name.replace("_", " ").replace("-", " ").strip()


def extract_txt(path: str) -> ExtractedDocument:
    """Plain text file. It has no pages, so the whole thing is page 1."""
    with open(path, "r", encoding="utf-8", errors="replace") as handle:
        text = clean_text(handle.read())

    if "=== PAGE " in text:
        from .review import parse_pages
        pages = parse_pages(text)
        return ExtractedDocument(path=path, title=_title_from_path(path), pages=pages,
                                 total_pages=pages[-1].number)
    return ExtractedDocument(
        path=path,
        title=_title_from_path(path),
        pages=[Page(number=1, text=text)] if text else [],
    )


def extract_markdown(path: str) -> ExtractedDocument:
    """Markdown file.

    Markdown headings are turned into plain headings that the chunker
    recognises, so the section names in the app match what the author
    wrote. The '#' characters themselves are removed, because they are
    markup, not content.
    """
    with open(path, "r", encoding="utf-8", errors="replace") as handle:
        raw = handle.read()

    lines: List[str] = []
    for line in raw.replace("\r\n", "\n").split("\n"):
        stripped = line.lstrip()
        if stripped.startswith("#"):
            # "# Title" -> "Title" so the heading detector sees a title.
            without_marks = stripped.lstrip("#").strip()
            if without_marks:
                lines.append("")
                lines.append(without_marks)
                lines.append("")
            continue
        lines.append(line)

    text = clean_text("\n".join(lines))
    return ExtractedDocument(
        path=path,
        title=_title_from_path(path),
        pages=[Page(number=1, text=text)] if text else [],
    )


def extract_pdf(path: str) -> ExtractedDocument:
    """PDF file, one entry in `pages` for each real page.

    Requires PyMuPDF, which is listed in tools/requirements.txt.
    """
    try:
        import pymupdf
    except ImportError as problem:  # pragma: no cover - depends on install
        raise RuntimeError(
            "PyMuPDF is not installed. Run:\n"
            "    tools/.venv/bin/pip install -r tools/requirements.txt"
        ) from problem

    document = pymupdf.open(path)
    try:
        total_pages = document.page_count

        raw_pages = [
            Page(number=index + 1, text=clean_text(page.get_text()))
            for index, page in enumerate(document)
        ]

        # Keep only pages that actually carry text, but keep their real
        # numbers so citations stay correct.
        pages = [page for page in raw_pages if len(page.text) >= MIN_USEFUL_PAGE_CHARACTERS]
        blank_pages = total_pages - len(pages)

        title = choose_title(path, (document.metadata or {}).get("title") or "")

        result = ExtractedDocument(path=path, title=title, pages=pages)
        result.total_pages = total_pages
        result.blank_pages = blank_pages

        # Two separate signs of a scan, and BOTH must be checked:
        #   - no usable text at all (the strongest sign)
        #   - or some text, but far too little to be a real manual
        # Checking only the second would let a fully scanned PDF pass,
        # because it would have no pages left to average.
        text_per_page = (result.character_count // total_pages) if total_pages else 0

        if not pages or text_per_page < SCANNED_PAGE_CHARACTER_LIMIT:
            result.needs_ocr = True
            result.warning = (
                "This PDF looks like a scan, not a text document.\n"
                "  Pages in the file      : %d\n"
                "  Pages with real text   : %d\n"
                "  Pages with no text     : %d\n"
                "  Characters per page    : %d (a normal manual has 800 or more)\n"
                "\n"
                "  It is a photograph of printed pages, so there is nothing to\n"
                "  extract until it is recognised. Run it through OCRmyPDF first:\n"
                "\n"
                "      ocrmypdf --deskew --rotate-pages input.pdf output.pdf\n"
                "\n"
                "  then build the database from output.pdf, not from input.pdf."
                % (total_pages, len(pages), blank_pages, text_per_page)
            )

        return result
    finally:
        document.close()


def extract(path: str) -> ExtractedDocument:
    """Read any supported file and return its text."""
    extension = os.path.splitext(path)[1].lower()

    if extension == ".pdf":
        return extract_pdf(path)
    if extension in (".md", ".markdown"):
        return extract_markdown(path)
    if extension == ".txt":
        return extract_txt(path)

    raise ValueError(
        "Unsupported file type '%s' for %s\n"
        "  Supported so far: %s"
        % (extension, os.path.basename(path), ", ".join(SUPPORTED_EXTENSIONS))
    )


def collect_input_files(input_path: str) -> List[str]:
    """Return every supported file inside a folder, or the single file given.

    Files are sorted so that a build always produces the same result for
    the same input, which matters because chunk ids follow document order.
    """
    if os.path.isfile(input_path):
        return [input_path]

    if not os.path.isdir(input_path):
        raise FileNotFoundError("No such file or folder: %s" % input_path)

    found: List[str] = []
    for root, folders, files in os.walk(input_path):
        folders.sort()
        for name in sorted(files):
            if is_supported(name):
                found.append(os.path.join(root, name))

    return found