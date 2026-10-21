# DataEater Builder 0.5.0

Database creation now includes offline preparation-quality reports in both CLI and desktop workflows. Reports identify omitted/sparse pages, oversized passages and PDF layout-review limitations. Reviewed builds flag changed numbers, units, identifiers, restrictions and numbered steps. Inspect database displays the complete report; review packages include quality_report.json.

Reports contain counts, flags and source fingerprints, not document text or secret keys. They remain encrypted with private source metadata. Legacy format-v1 readers are supported. Failed database builds preserve the previous destination through staged verification and atomic replacement.

AI and internet access are not required. Flags are review hints rather than technical approval, and PDF column/table ownership is not automatically verified. English/Russian restriction hints do not cover every language. Existing extraction and passage-grouping defaults are unchanged.
