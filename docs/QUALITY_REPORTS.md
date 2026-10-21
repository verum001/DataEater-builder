# Preparation report schema

New source records may contain preparation_quality, a dataeater-source-quality version-1 object. It is hashed with sources.json and encrypted inside the existing dataeater-payload envelope for locked databases. No archive member or reader format change is needed. Legacy sources without the field remain valid.

The report records source_id, source_sha256, total_pages, pages (original page, inclusion, character and UTF-8 byte counts when known, reason, reading_order and flags), oversized_passages (page and character count), technical_accuracy=not_verified and limitations. Excluded documents may appear under excluded_documents in the first retained source. No body text or private key is included. Kotlin character counts use UTF-16 code units; Python counts Unicode code points, so non-BMP character counts may differ while UTF-8 byte counts remain comparable.

A PDF layout flag means layout has not been verified, not that an error was detected. Omission reasons below_100_characters and not_in_extracted_text distinguish measured short pages from unavailable older extraction metadata. Review flags describe literal number/restriction/unit/identifier/step differences; benign formatting changes remain allowed. They are not entailment, actor-ownership or language-independent correctness tests. Restriction hints cover English/Russian.

Review exports carry original page_metrics in review.json and an advisory quality_report.json. Import validates original batches/page markers and recomputes review changes; returned advisory reports are not trusted. Each source is limited to 10,000 pages and the collection to 20,000 report pages. Generated database packages remain subject to existing size/hash guards and are atomically replaced after verification.

Desktop/CLI: Inspect database displays the full readable report. Android: the build result offers Save quality report with artifact SHA-256 binding. Explicit exports are unencrypted and may disclose source fingerprints/page counts. Without decryption, ordinary inspection of a private database cannot show its encrypted report.
