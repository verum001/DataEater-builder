"""The command line for DataEater Builder.

    dataeater-builder build ./manuals --output my_manual.dataeater
    dataeater-builder inspect my_manual.dataeater
    dataeater-builder review ./manuals --output extracted/

This runs on a Linux computer. The Android app never builds databases; it
only reads them.
"""

import argparse
import json
import os
import re
import sys
import textwrap
import zipfile
from typing import List

from . import extractors, packaging
from .chunker import chunk_pages, merge_short_chunks


def make_database_id(name: str) -> str:
    """Turn a name into something safe for a file name and an id."""
    cleaned = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return cleaned or "database"


def guess_year(path: str) -> int:
    """Look for a four digit year in the file name, e.g. 'RK250-2018.pdf'."""
    match = re.search(r"(19|20)\d{2}", os.path.basename(path))
    return int(match.group(0)) if match else 0


def human_size(size_bytes: int) -> str:
    value = float(size_bytes)
    for unit in ("bytes", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return "%.1f %s" % (value, unit)
        value /= 1024
    return "%.1f GB" % value


def command_build(arguments: argparse.Namespace) -> int:
    """Build a `.dataeater` file from a folder or a single file."""
    files = extractors.collect_input_files(arguments.input)

    if not files:
        print("No supported files found in %s" % arguments.input, file=sys.stderr)
        print("Supported types: %s" % ", ".join(extractors.SUPPORTED_EXTENSIONS),
              file=sys.stderr)
        return 1

    print("DataEater Builder %s" % packaging.BUILDER_VERSION)
    print("Input : %s" % arguments.input)
    print("Files : %d found" % len(files))
    print()

    skipped: List[str] = []
    warnings: List[str] = []

    if arguments.review:
        from .review import export_review
        export_review(arguments.input, arguments.review)
        print('Review export written to '+arguments.review)
        print('Use build-reviewed to preserve page references after editing.')
        return 0

    build = packaging.DatabaseBuild(
        database_id="",
        name=arguments.name or os.path.basename(os.path.normpath(arguments.input)),
        description=arguments.description or "Built by dataeater-builder from %d source file(s)." % len(files),
        language=arguments.language,
        license=arguments.license,
    )

    chunk_number = 1

    for index, path in enumerate(files):
        print("Reading  %s" % os.path.basename(path))
        document = extractors.extract(path)

        if document.warning:
            warnings.append(document.warning)
            print("         !! %s" % document.warning.splitlines()[0])

        if not document.pages:
            skipped.append(os.path.basename(path))
            print("         -- no usable text, skipping")
            continue

        source_id = "s%d" % (index + 1)
        build.sources.append(
            packaging.SourceRecord(
                source_id=source_id,
                title=document.title,
                publisher=arguments.publisher,
                year=guess_year(path),
                language=arguments.language,
                license=arguments.license,
                original_path=os.path.abspath(path),
            )
        )

        produced = chunk_pages(
            document.pages,
            target_chars=arguments.target_chars,
            source_id=source_id,
            start_number=chunk_number,
        )
        produced = merge_short_chunks(produced)

        for chunk in produced:
            chunk.source_id = source_id

        chunk_number += len(produced)
        build.chunks.extend(produced)

        print("         %d pages, %d characters, %d chunks"
              % (len(document.pages), document.character_count, len(produced)))

    if not build.chunks:
        print()
        print("Nothing was extracted, so no database was written.", file=sys.stderr)
        return 1

    build.database_id = make_database_id(build.name)
    if not arguments.name:
        build.name = build.name.replace("_", " ").replace("-", " ").strip()

    report = packaging.write_database(build, arguments.output)
    problems = packaging.verify_database(report.output_path)

    print()
    print("Database written")
    print("  file       : %s" % report.output_path)
    print("  size       : %s" % human_size(report.size_bytes))
    print("  name       : %s" % report.database_name)
    print("  id         : %s" % build.database_id)
    print("  documents  : %d" % report.document_count)
    print("  chunks     : %d" % report.chunk_count)

    if skipped:
        print("  skipped    : %s" % ", ".join(skipped))

    if problems:
        print()
        print("VERIFICATION FOUND PROBLEMS:")
        for problem in problems:
            print("  - %s" % problem)
        return 2

    print("  check      : all fingerprints and counts are correct")

    if warnings:
        print()
        print("WARNINGS")
        for warning in warnings:
            print(warning)

    return 0


def command_inspect(arguments: argparse.Namespace) -> int:
    """Show what is inside a finished database.

    Works on a LOCKED database too. The text inside cannot be shown, because
    that is the whole point of locking it, but everything the manifest says
    is still readable and still worth checking.
    """
    problems = packaging.verify_database(arguments.database)
    if problems and "not a readable ZIP" in problems[0]:
        print(problems[0], file=sys.stderr)
        return 1

    import json
    import zipfile

    with zipfile.ZipFile(arguments.database) as archive:
        manifest = json.loads(archive.read(packaging.MANIFEST_FILE).decode("utf-8"))

        encryption = (manifest.get("encryption") or "none").strip()
        locked = bool(encryption) and encryption.lower() != "none"

        # A locked database has no sources.json and no chunks.jsonl. Asking
        # for them anyway produced a raw Python traceback, which tells the
        # creator nothing. They are replaced by one encrypted payload.
        if locked:
            sources = []
            chunk_text = ""
        else:
            sources = json.loads(archive.read(packaging.SOURCES_FILE).decode("utf-8"))
            chunk_text = archive.read(packaging.CHUNKS_FILE).decode("utf-8")

    print("Database : %s" % os.path.basename(arguments.database))
    print("  name            %s" % manifest.get("name"))
    print("  id              %s" % manifest.get("database_id"))
    print("  format version  %s" % manifest.get("format_version"))
    print("  language        %s" % manifest.get("language"))
    print("  licence         %s" % manifest.get("license"))
    print("  encryption      %s" % encryption)
    print("  created         %s" % manifest.get("created_utc"))
    print("  chunks          %s" % (manifest.get("counts") or {}).get("chunks"))

    if locked:
        # Everything a customer is shown before entering an Unlock Code lives
        # in the readable manifest, so it is worth confirming it is right.
        print()
        print("LOCKED DATABASE")
        print("  The text inside is encrypted and cannot be shown without a")
        print("  content key. That is expected.")
        print()
        print("  creator               %s" % (manifest.get("creator") or "(none set)"))
        print("  contact               %s" % (manifest.get("contact") or "(none set)"))
        print("  creator public key    %s"
              % ("present" if manifest.get("creator_public_key") else "(MISSING)"))
        print()
        if not manifest.get("creator_public_key"):
            print("  WARNING: no creator public key. The customer's app cannot")
            print("  check that an Unlock Code really came from you. Re-run")
            print("  'encrypt' with --creator-public-key.")
            print()

    print()

    if not locked:
        print("Documents (%d)" % len(sources))
        for source in sources:
            print("  [%s] %s" % (source.get("id"), source.get("title")))
        print()

        lines = [line for line in chunk_text.splitlines() if line.strip()]
        if lines:
            import json as _json
            first = _json.loads(lines[0])
            print("First chunk")
            print(textwrap.indent(textwrap.fill(first.get("text", ""), 78), "  "))
            print("  -> %s, section %s, page %s"
                  % (first.get("source_id"), first.get("section"), first.get("page")))

    if problems:
        print()
        print("PROBLEMS")
        for problem in problems:
            print("  - %s" % problem)
        return 2

    return 0


def command_encrypt(arguments: argparse.Namespace) -> int:
    """Encrypt a plain `.dataeater` file into a locked one.

    The database is encrypted once and can then be licensed to any number of
    customers. No customer-specific data is written into it.
    """
    if not os.path.exists(arguments.input):
        print("No such file: %s" % arguments.input, file=sys.stderr)
        return 1

    secret_path = arguments.secret
    if not secret_path:
        secret_path = os.path.splitext(arguments.output)[0] + ".secret"

    content_key = None
    if os.path.exists(secret_path):
        if arguments.force_new_key:
            # Replaced deliberately. The old key is gone for good, so anyone
            # holding an old licence can no longer be helped.
            print("Replacing the key in %s as asked." % secret_path)
        else:
            # Reuse the existing key so the creator keeps one key per
            # database and can issue more licences later.
            content_key = packaging.read_secret_file(secret_path)
            print("Using the existing key from %s" % secret_path)

    try:
        key, size = packaging.encrypt_database_file(
            input_path=arguments.input,
            output_path=arguments.output,
            content_key=content_key,
            creator=arguments.creator,
            contact=arguments.contact,
            creator_public_key=arguments.creator_public_key,
        )
    except ValueError as problem:
        print("Cannot encrypt: %s" % problem, file=sys.stderr)
        return 1

    packaging.write_secret_file(
        path=secret_path,
        content_key=key,
        database=os.path.basename(arguments.output),
    )

    print()
    print("Database locked")
    print("  locked file  : %s" % arguments.output)
    print("  size         : %s" % human_size(size))
    if arguments.creator:
        print("  creator      : %s" % arguments.creator)
    if arguments.contact:
        print("  contact      : %s" % arguments.contact)
    print("  content key  : stored in %s" % secret_path)
    print()
    print("Keep that key file private. It is the only way to open this")
    print("database again. Losing it means nobody can open it, including you.")
    print()
    print("Next step, when a customer sends their Request Code:")
    print("  dataeater-builder licence %s \\" % os.path.basename(arguments.output))
    print("      --secret %s \\" % os.path.basename(secret_path))
    print("      --key <your-creator.key> \\")
    print("      --request-code <their-code>")
    return 0


def command_create_key(arguments: argparse.Namespace) -> int:
    """Make the creator's ECDSA P-256 signing key."""
    if os.path.exists(arguments.output) and not arguments.force:
        print("%s already exists." % arguments.output, file=sys.stderr)
        print("Use --force to replace it. Replacing the signing key means "
              "licences signed with the old one can no longer be verified.",
              file=sys.stderr)
        return 1

    private_key, public_key = packaging.create_creator_keypair()
    public_text = packaging.write_creator_key_file(
        arguments.output, private_key, public_key)

    print("Creator signing key created")
    print("  key file   : %s" % arguments.output)
    print("  algorithm  : ecdsa-p256-sha256")
    print()
    print("PUBLIC KEY - safe to publish, put it in the database manifest:")
    print()
    print(public_text)
    print()
    print("Keep the key file private. Anyone holding it can issue licences")
    print("for every database you own. Never commit it.")
    return 0


def command_licence(arguments: argparse.Namespace) -> int:
    """Issue a device-specific, signed Unlock Code for one customer."""
    for path, what in ((arguments.database, "database"),
                       (arguments.secret, "secret file"),
                       (arguments.key, "creator key")):
        if not os.path.exists(path):
            print("No such %s: %s" % (what, path), file=sys.stderr)
            return 1

    try:
        content_key = packaging.read_secret_file(arguments.secret)
        signing_key, _ = packaging.read_creator_key_file(arguments.key)
        device_public_key = packaging.read_request_code(arguments.request_code)
        expiry = packaging.parse_expiry(arguments.expiry)
    except ValueError as problem:
        print("Cannot issue a licence: %s" % problem, file=sys.stderr)
        return 1

    with zipfile.ZipFile(arguments.database) as archive:
        manifest = json.loads(archive.read(packaging.MANIFEST_FILE).decode("utf-8"))
    if manifest.get("encryption") in (None, "", "none"):
        print("That database is not encrypted, so it needs no licence.",
              file=sys.stderr)
        return 1

    licence = packaging.build_licence(
        content_key=content_key,
        device_public_key=device_public_key,
        expiry=expiry,
        database_id=manifest.get("database_id", ""),
    )
    licence = packaging.sign_licence(licence, signing_key)
    code = packaging.encode_licence(licence)

    written_to = arguments.output
    if written_to:
        with open(written_to, "w", encoding="utf-8") as handle:
            handle.write(code + "\n")

    print("Unlock Code for one device")
    print("  database    : %s" % manifest.get("name"))
    print("  database id : %s" % manifest.get("database_id"))
    print("  expiry      : %s" % (expiry or "never"))
    print("  signed with : ecdsa-p256-sha256")
    print()
    print("It only works on the phone that sent the matching Request Code.")
    print()
    if written_to:
        # A file, not a wall of text.
        #
        # The customer saves this and the app finds it, so nothing has to be
        # copied by hand. That was the whole reason: 850 characters retyped by
        # hand is 850 chances to lose a character and get a refusal nobody can
        # explain.
        print("WHAT TO DO NOW")
        print()
        print("  1. Email or message this file to the customer. Attach it;")
        print("     do not paste its contents.")
        print()
        print("  2. They save it on their phone into:")
        print("       %s" % LICENCE_FOLDER)
        print()
        print("  3. They open the database and tap its licence file.")
        print()
        print("The customer only has to send you a Request Code once, however")
        print("many databases they buy from you.")
        print()
        print("IF THEY CANNOT OPEN ATTACHMENTS, SEND THIS AS TEXT INSTEAD")
        print("(the app still accepts a pasted code, under")
        print(" \"I have a code as text instead\"):")
        print()
        print(code)
    else:
        print("No --output was given, so only the text is printed below.")
        print("Prefer --output: the customer saves a file and does not copy")
        print("anything by hand.")
        print()
        print(code)
    return 0


# Where the customer's app looks for licence files. Kept as one string so the
# README, the tool's output and the app cannot drift apart without it being
# obvious: the app has the same path in LicenceFiles.FOLDER_NAME.
LICENCE_FOLDER = "/sdcard/DataEater/Lic"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="dataeater-builder",
        description="Build .dataeater knowledge databases from PDF, TXT and Markdown files.",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    build = commands.add_parser("build", help="build a database from documents")
    build.add_argument("input", help="a file or a folder of files")
    build.add_argument("--output", "-o", required=True, help="the .dataeater file to write")
    build.add_argument("--language", default="en", help="main language of the documents")
    build.add_argument("--license", default="unknown", help="licence of the content")
    build.add_argument("--publisher", default="", help="who produced the documents")
    build.add_argument("--target-chars", type=int, default=700,
                       help="how long one chunk should be (default 700)")
    build.add_argument("--review", metavar="FOLDER", default=None,
                       help="only extract the text into FOLDER for human review, "
                            "and stop there")
    build.set_defaults(handler=command_build)

    build.add_argument("--name", help="display name in the Android app")
    build.add_argument("--description", default="", help="database description")

    from .review import command_review, command_build_reviewed
    review = commands.add_parser("review", help="export document text, LLM prompt and editable batches")
    review.add_argument("input", help="PDF, text file or document folder")
    review.add_argument("--output", "-o", required=True, help="new review folder")
    review.add_argument("--batch-chars", type=int, default=30000, help="target characters per batch; whole pages are retained")
    review.set_defaults(handler=command_review)

    reviewed = commands.add_parser("build-reviewed", help="build from checked LLM/human edits with original page references")
    reviewed.add_argument("input", help="review folder containing review.json")
    reviewed.add_argument("--output", "-o", required=True)
    reviewed.add_argument("--name", help="display name in the Android app")
    reviewed.add_argument("--description", default="")
    reviewed.add_argument("--language", default="en")
    reviewed.add_argument("--license", default="unknown")
    reviewed.add_argument("--publisher", default="")
    reviewed.add_argument("--target-chars", type=int, default=700)
    reviewed.set_defaults(handler=command_build_reviewed)

    inspect = commands.add_parser("inspect", help="show what is inside a database")
    inspect.add_argument("database", help="the .dataeater file to read")
    inspect.set_defaults(handler=command_inspect)

    encrypt = commands.add_parser(
        "encrypt", help="encrypt a database so it can only be opened with a licence")
    encrypt.add_argument("input", help="a plain .dataeater file")
    encrypt.add_argument("--output", "-o", required=True,
                         help="the locked .dataeater file to write")
    encrypt.add_argument("--secret", default=None,
                         help="where to keep the content key "
                              "(default: the output name with .secret)")
    encrypt.add_argument("--creator", default="", help="creator name shown to customers")
    encrypt.add_argument("--contact", default="", help="contact email shown to customers")
    encrypt.add_argument("--creator-public-key", default="",
                         help="the ECDSA P-256 public key printed by 'create-key'. "
                              "The app needs it to check Unlock Codes.")
    encrypt.add_argument("--force-new-key", action="store_true",
                         help="make a fresh key even if a secret file exists")
    encrypt.set_defaults(handler=command_encrypt)

    key = commands.add_parser(
        "create-key", help="create the creator's ECDSA P-256 signing key")
    key.add_argument("--output", "-o", default="creator.key",
                     help="where to write the private key (default creator.key)")
    key.add_argument("--force", action="store_true",
                     help="replace an existing key")
    key.set_defaults(handler=command_create_key)

    licence = commands.add_parser(
        "licence", help="issue a signed Unlock Code for one customer device")
    licence.add_argument("database", help="the locked .dataeater file")
    licence.add_argument("--secret", required=True,
                         help="the content key file made by 'encrypt'")
    licence.add_argument("--key", default="creator.key",
                         help="the creator signing key (default creator.key)")
    licence.add_argument("--request-code", required=True,
                         help="the code the customer sent you")
    licence.add_argument("--expiry", default="never",
                         help="never, 30d, 90d, 1y, or YYYY-MM-DD")
    licence.add_argument("--output", "-o", default=None,
                         help="also save the Unlock Code to this file")
    licence.set_defaults(handler=command_licence)

    return parser


def main(argv: List[str] = None) -> int:
    parser = build_parser()
    arguments = parser.parse_args(argv)
    try:
        return arguments.handler(arguments)
    except (OSError, KeyError, TypeError, RuntimeError) as problem:
        print("Error: %s" % problem, file=sys.stderr)
        return 1
    except ValueError as problem:
        print("Error: %s" % problem, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())