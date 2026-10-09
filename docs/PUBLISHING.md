# Publish Builder v0.4.0

## Update the repository

1. Extract `DataEater-Builder-0.4.0-source.zip` into an empty folder.
2. Open the separate builder repository on GitHub and choose **Add file → Upload files**.
3. Upload the extracted contents at the repository root. Keep folders such as `tools/`, `docs/`, `packaging/`, `assets/` and `screenshots/` intact. Include README, changelog, project configuration, LICENSE, NOTICE and third-party notices.
4. Commit the update with a summary such as `Add Linux desktop in Builder 0.4.0`.

Do not upload the ZIP as a substitute for repository contents. If your existing repository has files removed in this version, remove those separately; a browser upload does not delete old files automatically. Retain existing repository history.

## Create the release

1. Open **Releases → Draft a new release**.
2. Create tag **v0.4.0** on the commit containing this update.
3. Set the title to **DataEater Builder v0.4.0**.
4. Paste [RELEASE_NOTES_0.4.0.md](RELEASE_NOTES_0.4.0.md) into the description.
5. Attach `dataeater-builder_0.4.0_all.deb`, `DataEater-Builder-0.4.0-source.zip`, `SHA256SUMS` and `VALIDATION.md` from the prepared release folder.
6. Check the preview and publish the release.

The `.deb` is a release attachment, not a source file to put in the repository root. Users install it with their distribution's software installer or `sudo apt install ./dataeater-builder_0.4.0_all.deb`.

## Record changes

Write future changes at the top of `CHANGELOG.md`. Update README and help when behavior changes. Put each release's reader-facing summary in `docs/RELEASE_NOTES_VERSION.md` and paste that into GitHub's release description. Keep version values in `pyproject.toml` and `tools/dataeater_builder/packaging.py` synchronized.

Before publishing, run the builder tests and desktop smoke check, build the package, verify its contents and regenerate checksums. Never include `.venv`, source PDFs, review exports, generated databases, signing keys, content keys or customer access codes. Screenshots must use invented content.

The Debian package contains original Python code and documentation; system PDF/encryption dependencies are not bundled. Preserve all licensing and attribution notices. Distribution packages and document content have their own rights.

GitHub documentation: [upload files](https://docs.github.com/en/repositories/working-with-files/managing-files/adding-a-file-to-a-repository) and [create a release](https://docs.github.com/en/repositories/releasing-projects-on-github/managing-releases-in-a-repository).
