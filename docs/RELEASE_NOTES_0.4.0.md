# DataEater Builder v0.4.0

A Linux desktop for building knowledge databases without typing terminal commands.

- A simple sidebar and focused forms for all seven builder commands.
- Direct database building, editable PDF/text review and validated reviewed builds.
- Database inspection, encryption, signing-key creation and device access codes.
- Background operations with progress, cancellation and readable results.
- Advanced settings kept out of the main workflow.
- Offline help with detailed explanations and troubleshooting.
- A Debian package with an application-menu entry and the existing CLI.
- Completed-output staging, cancellation cleanup and rollback after ordinary output-move failures.

Existing version 1 `.dataeater` files remain compatible with the Android app. This release does not add OCR, an LLM API, automatic document uploads or a new database format.

## Install

Tested package target: Debian 13. Download the `.deb`, then open it with the system software installer or run:

```bash
sudo apt install ./dataeater-builder_0.4.0_all.deb
```

Open DataEater Builder from the applications menu. Other Debian-family systems need the declared dependency versions and have not been verified.

## Downloads

- `dataeater-builder_0.4.0_all.deb` — Linux desktop and CLI.
- `DataEater-Builder-0.4.0-source.zip` — source, tests and documentation.
- `SHA256SUMS` — download checksums.
- `VALIDATION.md` — test environment, results and limits.

The source ZIP excludes private keys, real documents, generated databases and environments. Dependencies are supplied by the distribution, with their own licensing terms. See THIRD_PARTY_NOTICES.md.

Help → Getting started explains the first build. Read the text-review and key-management sections before publishing reviewed or locked databases.
