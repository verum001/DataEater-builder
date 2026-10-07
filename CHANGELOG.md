# Changelog

## 0.3.0 — 7 October 2026

- Preserve content beneath short headings and standalone decimal values.
- Keep searchable headings and complete table rows; do not invent punctuation.
- Keep chunks on their actual page and avoid merging unrelated sections.
- Inspect reports oversized and repeated passages for optional human/LLM review.
- Preserve PDF paragraph blocks and publisher bookmark ancestry through review exports.
- Keep publisher search context separate from answer facts; avoid guessing diagram labels as sections.
- Existing version 1 databases remain compatible with the Android app.


## 0.2.0 — 7 October 2026

- Separated the database builder from the private Android project.
- Added `review` exports with a large-LLM prompt, editable batches and source fingerprints.
- Added `build-reviewed` with original page-reference validation.
- Preserved page markers when importing previously exported plain text.
- Added display-name and description options to direct database builds.
- Preserved existing encryption, licensing and Android database-format compatibility.
- Fixed duplicate chunk IDs after short-section merging across source documents.
