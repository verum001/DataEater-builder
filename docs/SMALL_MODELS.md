# Preparing text for small models

Clear extracted text does not need an AI rewrite. Preserve original facts first:
headings with their body, original page positions, complete sentences, tables,
negations, numbers and units. Builder 0.3.0 keeps searchable headings and avoids
merging different pages or sections. When a PDF has bookmarks, the builder uses
its publisher headings and ancestry instead of guessing headings from diagram
labels or equations. PDF paragraph blocks are preserved. This context is searchable
metadata; it is not added to answer facts. Existing databases remain readable; rebuild
to apply the fixes.

Use `tools/dataeater-builder inspect manual.dataeater` to see oversized and exact
repeated passages. Long indivisible sentences/rows remain intact rather than
silently truncated. Inspect these passages against the source. Repeated material
is reported, not silently deleted: repeated warnings can be important.

If extraction mixes columns or breaks a table, export with `review`, repair with a
human or large LLM, verify the result against the original and use `build-reviewed`.
The supplied prompt forbids new facts and summaries. No automatic LLM upload or
API is performed. Scanned text still needs OCR; diagrams are not reconstructed.

The app searches locally, gives a few relevant passages to the model and replays
bounded conversation context. A bigger or better formatted database cannot repair
a model that invents values or misses negation. Test questions with known answers,
a follow-up, a safety warning and an absent value before trusting the combination.

Source tests cover decimal preservation, headings with short bodies, complete
rows and exact page boundaries in addition to the existing PDF-review round trip.
