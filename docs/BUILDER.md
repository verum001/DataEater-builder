# Builder commands

Run `tools/dataeater-builder COMMAND --help` for options. See [README](../README.md) for setup and the complete PDF/LLM review workflow.

| Command | Purpose |
|---|---|
| `build INPUT -o FILE --name NAME` | Build directly from PDF/TXT/Markdown files |
| `review INPUT -o FOLDER` | Export original and editable text batches, source metadata and LLM prompt |
| `build-reviewed FOLDER -o FILE --name NAME` | Validate edits and build with original page references |
| `inspect FILE` | Verify format, fingerprints and counts |
| `encrypt FILE -o LOCKED --creator NAME --contact CONTACT --creator-public-key KEY` | Encrypt the content for licensed access |
| `create-key -o FILE` | Generate the creator signing key; keep it private |
| `licence LOCKED --secret FILE --key FILE --request-code CODE` | Issue a device-bound access code |

Review exports are intentionally not Git files. Keep the originals and manifest unchanged;
edit only the matching files in `reviewed/`. A large LLM receives one batch plus
`LLM_PROMPT.txt` at a time. Do not build from the whole export folder with `build`;
use `build-reviewed` so originals and edited copies cannot be mixed.

`--batch-chars` controls approximate batch size while preserving whole pages.
`--target-chars` controls final retrieval chunk size. No LLM API or automatic upload is used.
