# Publish Builder v0.3.0

1. Extract `dist/DataEater-builder-source.zip` into an empty folder.
2. In the separate builder GitHub repository, choose **Add file → Upload files**.
   Upload the extracted contents at the repository root: `README.md`, `tools/`,
   `docs/`, tests, project configuration, `LICENSE`, `NOTICE` and third-party notices.
   Commit the update with a short summary, such as `Prepare Builder 0.3.0`.
3. Open **Releases → Draft a new release**. Create tag **v0.3.0** on that updated
   commit, with title **DataEater Builder v0.3.0**.
4. Paste [these release notes](RELEASE_NOTES_0.3.0.md) into the release description.
   Attach the source ZIP if you want a ready-to-use download, then publish.

Keep `.venv`, input PDFs, review exports, generated databases, keys and secrets
out of the repository. Retain all license notices. A packaged PDF-enabled
executable has additional PyMuPDF/MuPDF distribution obligations; this release
contains source and dependency requirements, not a bundled executable.

For later updates, describe changes at the top of `CHANGELOG.md`, update setup or
usage instructions in `README.md` when needed, and copy the version’s changes into
the GitHub release description. Keep earlier changelog entries.

GitHub instructions: [upload files](https://docs.github.com/en/repositories/working-with-files/managing-files/adding-a-file-to-a-repository)
and [create a release](https://docs.github.com/en/repositories/releasing-projects-on-github/managing-releases-in-a-repository).
