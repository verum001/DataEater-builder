# DataEater Builder v0.3.0

- Preserve text beneath short headings, decimal values and table rows.
- Keep original PDF page positions and avoid merging unrelated sections.
- Preserve PDF paragraph blocks and publisher heading ancestry.
- Retain that structure through editable LLM-review exports.
- Add passage-quality hints to `inspect`.

Existing `.dataeater` format-1 files remain compatible with DataEater.
Clear extracted text does not require AI rewriting. The optional review workflow
repairs extraction and requires checking changes against the source PDF.

Linux only; Python 3.10 or newer. Nine builder test scripts passed.
Original code uses Apache 2.0; PyMuPDF/MuPDF retains its separate license terms.
