# DataEater Builder

Turn PDFs, text and Markdown into `.dataeater` knowledge databases for the DataEater Android app.

**Currently supported on Linux only.**

The builder creates `.dataeater` databases; the Android app reads them.

## Set up

Python 3.10 or newer:

```bash
python3 -m venv tools/.venv
tools/.venv/bin/pip install -r tools/requirements.txt
```

Run commands from this project folder. The launcher uses its own environment automatically.

## Build directly

```bash
tools/dataeater-builder build /path/to/manuals -o manual.dataeater --name "My Technical Manuals"
tools/dataeater-builder inspect manual.dataeater
```

Input can be one PDF, TXT or Markdown file, or a folder. PDF text is extracted locally.
Scanned PDFs need OCR first. Images are not embedded in the resulting database.

Clear extracted text does not need AI rewriting. The builder preserves headings,
values and page boundaries automatically. PDF paragraphs and publisher bookmarks
are retained for search, including section ancestry. Use `inspect` to see oversized or
repeated passages. See [preparing text for small models](docs/SMALL_MODELS.md) and the
[phone benchmark summary](docs/BENCHMARKS.md).
Use the optional LLM review below for broken extraction or
tables, and check every correction against the PDF.

## Improve extracted text with a large LLM

1. Export editable text and an instruction prompt:

```bash
tools/dataeater-builder review /path/to/manual.pdf -o exports/manual --batch-chars 30000
```

2. Open `exports/manual/LLM_PROMPT.txt`. Give that prompt and **one file from `original/`** to your chosen LLM. If necessary, also provide the corresponding PDF pages. No upload happens automatically.
3. Save the complete returned plain text over the matching file in `reviewed/`. Keep uncertainty notes in `notes/`. Check changes, especially numbers, units, warnings and part identifiers, against the PDF.
4. Build the final database:

```bash
tools/dataeater-builder build-reviewed exports/manual -o manual.dataeater --name "My Technical Manuals"
tools/dataeater-builder inspect manual.dataeater
```

The export includes untouched originals, editable copies, source fingerprints and page metadata. Batches preserve whole pages. `build-reviewed` rejects missing files, changed originals and missing, duplicate, reordered or renumbered page markers. Original PDF page positions survive the round trip, even when blank pages are omitted.

The prompt asks the LLM to fix extraction and formatting, **not rewrite, summarize or invent technical information**. A valid page marker does not prove an answer or correction is accurate: check the reviewed text before sharing the database. Numeric changes are reported as a review reminder. Diagrams and their relationships are not reconstructed automatically.

The older `build INPUT --review FOLDER -o ignored` syntax also creates this review package. Use `build-reviewed FOLDER` afterwards; building from an entire export folder would mix its originals and edited copies.

## Other commands

- `encrypt`: create a database protected by device-bound access codes.
- `create-key`: create the publisher signing key.
- `licence`: issue an access code for a customer device.
- `inspect`: verify fingerprints and inspect the database.

See [builder commands](docs/BUILDER.md), [database format](docs/DATABASE_FORMAT.md) and [encryption](docs/ENCRYPTION_DESIGN.md). Store creator keys and content secrets privately.

## Tests

```bash
for test in tools/tests/test_*.py; do tools/.venv/bin/python "$test" || exit; done
```

Tests cover chunking, encryption, licensing, hostile archives and the PDF/edit/database round trip. Android integration tests remain in the app project.

## GitHub publication

This folder has its own Git history. Publish only tracked source, tests and documentation. `tools/.venv`, input PDFs, real document exports, output databases and signing keys are excluded. See [publication checklist](docs/PUBLISHING.md).

## License

Copyright 2026 Jack. Original builder code and documentation: [Apache 2.0](LICENSE).
PyMuPDF/MuPDF uses AGPLv3 or a commercial license; using or distributing the PDF-enabled builder must comply with those terms. Apache licensing of our code does not override dependency obligations. See [third-party notices](THIRD_PARTY_NOTICES.md).

Input documents and resulting database content retain their own rights. Only share material you have permission to distribute, and only send documents to an external LLM when authorized.
