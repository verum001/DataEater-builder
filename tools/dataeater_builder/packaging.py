"""Writing a `.dataeater` file.

This produces exactly the version 1 format that the Android app already
reads. Nothing about the format is being changed or redesigned here - the
app was written first, and this module follows it.

A `.dataeater` file is a ZIP archive containing:

    manifest.json   first, plain text, describes the database
    sources.json    the documents the text came from
    chunks.jsonl    the text itself, one JSON object per line

Every file listed in the manifest carries a SHA-256 fingerprint, so the app
can tell whether the file was modified after it was built.
"""

import base64
import hashlib
import json
import os
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List, Optional

from .chunker import Chunk

# This must match SUPPORTED_FORMAT_VERSION in the Android application.
FORMAT_NAME = "dataeater"
FORMAT_VERSION = 1

BUILDER_VERSION = "0.5.0"

MANIFEST_FILE = "manifest.json"
SOURCES_FILE = "sources.json"
CHUNKS_FILE = "chunks.jsonl"


# ---------------------------------------------------------------------------
# ENCRYPTION
# ---------------------------------------------------------------------------
# Only one small piece lives here at this stage: encrypting the payload.
#
# WHAT IS BEING ENCRYPTED
#   The knowledge itself: sources.json and chunks.jsonl. The manifest stays
#   readable so the app can say what the database is and that it is locked,
#   before any key exists.
#
# HOW
#   AES-256-GCM with a RANDOM 32-byte content key. The key is never derived
#   from a passphrase and never from a customer's public key - see
#   docs/ENCRYPTION_DESIGN.md.
#
# WHY A SMALL JSON ENVELOPE
#   The two files have to be carried as one blob. A JSON envelope holding the
#   two texts is the simplest container that both sides can read: Python with
#   the json module, Android with org.json, which the app already uses.
#   Storing them as text keeps the data byte-for-byte identical to the
#   unencrypted database, so nothing is lost or rewritten by encrypting.

ENCRYPTION_NAME = "aes-256-gcm"
PAYLOAD_FILE = "payload.enc"
PAYLOAD_FORMAT = "dataeater-payload"
PAYLOAD_VERSION = 1

CONTENT_KEY_BYTES = 32
GCM_NONCE_BYTES = 12
GCM_TAG_BITS = 128


@dataclass
class EncryptedPayload:
    """An encrypted payload, still in memory.

    The nonce is kept beside the ciphertext rather than inside it, because
    the nonce is not secret - it only has to be unique. Whoever writes this
    into a file decides where the nonce lives.
    """

    nonce: bytes
    ciphertext: bytes

    @property
    def size_bytes(self) -> int:
        return len(self.nonce) + len(self.ciphertext)


def generate_content_key() -> bytes:
    """A fresh random key that protects one database.

    `os.urandom` is the operating system's cryptographically secure random
    source. This is the only place a content key is created, and it is never
    derived from anything.
    """
    return os.urandom(CONTENT_KEY_BYTES)


def encrypt_payload(
    chunks_text: str,
    sources_text: str,
    content_key: bytes,
) -> EncryptedPayload:
    """Encrypt the database text with AES-256-GCM.

    :param chunks_text:   the contents of chunks.jsonl
    :param sources_text:  the contents of sources.json
    :param content_key:   32 random bytes
    :returns: an EncryptedPayload holding the nonce and the ciphertext
    :raises ValueError: if the key is not 32 bytes, or the library is missing
    """
    if len(content_key) != CONTENT_KEY_BYTES:
        raise ValueError(
            "A content key must be %d bytes, got %d."
            % (CONTENT_KEY_BYTES, len(content_key))
        )

    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    except ImportError as problem:  # pragma: no cover - depends on install
        raise RuntimeError(
            "The 'cryptography' package is not installed. Run:\n"
            "    tools/.venv/bin/pip install -r tools/requirements.txt"
        ) from problem

    envelope = json.dumps(
        {
            "format": PAYLOAD_FORMAT,
            "version": PAYLOAD_VERSION,
            "sources": sources_text,
            "chunks": chunks_text,
        },
        ensure_ascii=False,
    ).encode("utf-8")

    # A fresh random nonce for every single encryption. Reusing a nonce with
    # the same key would be a serious mistake, so it is generated here every
    # time and never reused.
    nonce = os.urandom(GCM_NONCE_BYTES)
    ciphertext = AESGCM(content_key).encrypt(nonce, envelope, None)

    return EncryptedPayload(nonce=nonce, ciphertext=ciphertext)


def decrypt_payload(payload: EncryptedPayload, content_key: bytes) -> dict:
    """Decrypt a payload. The exact inverse of :func:`encrypt_payload`.

    This exists so the round trip can be tested on the computer in seconds.
    The Android app performs the same AES-GCM step with the platform's own
    `javax.crypto`.

    :raises InvalidTag: if the key is wrong or the data was modified.
    """
    if len(content_key) != CONTENT_KEY_BYTES:
        raise ValueError(
            "A content key must be %d bytes, got %d."
            % (CONTENT_KEY_BYTES, len(content_key))
        )

    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    if len(payload.nonce) != 12 or len(payload.ciphertext) < 16:
        raise ValueError("Invalid encrypted payload lengths.")
    envelope = AESGCM(content_key).decrypt(payload.nonce, payload.ciphertext, None)
    result = _json_loads(envelope.decode("utf-8"))

    if not isinstance(result, dict) or result.get("format") != PAYLOAD_FORMAT:
        raise ValueError("This is not a DataEater payload (format=%r)."
                         % result.get("format"))
    if type(result.get("version")) is not int or result["version"] != PAYLOAD_VERSION:
        raise ValueError("Payload version is %r, expected %r."
                         % (result.get("version"), PAYLOAD_VERSION))

    if not isinstance(result.get("sources"), str) or not isinstance(result.get("chunks"), str):
        raise ValueError("Invalid payload text fields.")
    return {"sources": result["sources"], "chunks": result["chunks"]}


# ---------------------------------------------------------------------------
# ENCRYPTING A WHOLE DATABASE FILE
# ---------------------------------------------------------------------------
# A locked database keeps the SAME format, with three changes only:
#
#   manifest.json   still first, still readable, but now says
#                   "encryption": "aes-256-gcm" and carries the payload nonce
#   payload.enc      the encrypted chunks + sources, in place of the two files
#   fingerprints    the manifest now points at payload.enc
#
# What is deliberately NOT in the locked database:
#
#   * no Unlock Code  - licences are per customer and live in the licence,
#                      not in the database, so one database serves everyone
#   * no expiry       - different customers get different terms
#   * no content key   - that goes to the creator's own secret file
#
# Keeping it this way means a new customer needs only a new licence, never a
# re-encrypted database.


# ---------------------------------------------------------------------------
# GUARDED READING
# ---------------------------------------------------------------------------
#
# A `.dataeater` file does not always come from this program. A creator may be
# asked to inspect or encrypt a file a customer sent them, and the Android app
# opens files emailed by strangers. A ZIP archive is a well-known way to attack
# a program: a few kilobytes that decompress into gigabytes, exhausting memory
# with no useful error.
#
# So nothing here uses `archive.read(name)` on a file that arrived from
# outside. The declared size in the ZIP header is not trusted either, because a
# crafted file can claim anything; bytes are counted as they are produced.
#
# The limits match the Android app's (DatabaseLimits.kt), so both sides refuse
# the same files for the same reasons.
#
# 32 MB, not something larger, for the same reason as on the phone: a first
# attempt used 256 MB, and on the test phone the app was killed by Android at
# about 190 MB before the guard could ever run. A limit at the memory ceiling is
# no limit at all. Real databases are around 1 MB of text; even a 10,000-page
# manual lands near 17 MB.
MAX_ENTRY_BYTES = 32 * 1024 * 1024       # per file inside the package
MAX_ENTRIES = 10_000
MAX_SCAN_BYTES = 64 * 1024 * 1024
MAX_PACKAGE_BYTES = 128 * 1024 * 1024


def read_entry_capped(archive: zipfile.ZipFile, name: str, where: str) -> bytes:
    """Read one entry, refusing to expand past MAX_ENTRY_BYTES.

    :raises ValueError: if the entry is larger than the limit
    """
    info = name if isinstance(name, zipfile.ZipInfo) else archive.getinfo(name)
    if info.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED) or info.flag_bits & 1:
        raise ValueError("Unsupported ZIP compression or ZIP-level encryption.")
    total = 0
    chunks = []
    with archive.open(info) as stream:
        while True:
            block = stream.read(64 * 1024)
            if not block:
                break
            total += len(block)
            if total > MAX_ENTRY_BYTES:
                raise ValueError(
                    "'%s' inside %s expands to more than %d MB, which no real "
                    "database does. It is damaged, or made to exhaust memory. "
                    "It has not been read."
                    % (name, os.path.basename(where), MAX_ENTRY_BYTES // (1024 * 1024))
                )
            chunks.append(block)
    return b"".join(chunks)


def check_entry_count(names, where: str) -> None:
    """Refuse an archive with an absurd number of entries.

    :raises ValueError: if there are more than MAX_ENTRIES
    """
    if len(names) != len(set(names)):
        raise ValueError("Duplicate ZIP entries are not permitted.")
    if len(names) > MAX_ENTRIES:
        raise ValueError(
            "'%s' has %d files inside it, more than the %d any real database "
            "has. It is damaged, or made to exhaust memory."
            % (os.path.basename(where), len(names), MAX_ENTRIES)
        )


def _json_loads(text):
    if isinstance(text, bytes):
        text = text.decode("utf-8")
    depth = 0; quoted = False; escaped = False; tokens = 0
    for c in text:
        if quoted:
            if escaped: escaped = False
            elif c == "\\": escaped = True
            elif c == '"': quoted = False
        elif c == '"': quoted = True
        elif c in "{[":
            depth += 1; tokens += 1
            if depth > 32: raise ValueError("JSON is too deeply nested.")
        elif c in "}]": depth -= 1; tokens += 1
        elif c in ",:": tokens += 1
        if tokens > 100000: raise ValueError("JSON structure is too complex.")
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result: raise ValueError("Duplicate JSON field names are not permitted.")
            result[key] = value
        return result
    return json.loads(text, object_pairs_hook=unique)


def require_database_id(value):
    if not isinstance(value, str) or not value.strip() or value != value.strip() or len(value) > 256 or value in (".", "..") or any(ord(c) < 32 or 127 <= ord(c) <= 159 or c in "/\\" for c in value):
        raise ValueError("The database identifier is missing or ambiguous.")
    value.encode("utf-8")
    if len(value.encode("utf-16-le")) // 2 > 256:
        raise ValueError("The database identifier is too long.")
    return value


def _decode64(value):
    if not isinstance(value, str):
        raise ValueError("Expected base64 text.")
    if len(value) > 65536:
        raise ValueError("Base64 field is too large.")
    return base64.b64decode("".join(value.split()), validate=True)


def database_fingerprint(manifest):
    require_database_id(manifest.get("database_id"))
    if manifest.get("format") != FORMAT_NAME or type(manifest.get("format_version")) is not int or manifest["format_version"] != 1 or manifest.get("encryption") != ENCRYPTION_NAME:
        raise ValueError("Unsupported encrypted database format.")
    if not isinstance(manifest.get("payload_nonce"), str) or len(manifest["payload_nonce"]) > 128 or not isinstance(manifest.get("creator_public_key", ""), str) or len(manifest.get("creator_public_key", "")) > 2048:
        raise ValueError("Invalid manifest cryptographic fields.")
    nonce = _decode64(manifest["payload_nonce"])
    if len(nonce) != 12:
        raise ValueError("Invalid database nonce.")
    digest = manifest["files"][PAYLOAD_FILE]["sha256"]
    import re
    if not isinstance(digest, str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", digest):
        raise ValueError("Invalid encrypted payload fingerprint.")
    canonical = {"database_id": manifest["database_id"], "format_version": 1, "encryption": ENCRYPTION_NAME,
        "creator_public_key": base64.b64encode(_decode64(manifest.get("creator_public_key", ""))).decode("ascii"),
        "payload_nonce": base64.b64encode(nonce).decode("ascii"), "payload_sha256": digest}
    return "sha256:" + hashlib.sha256(_licence_signing_bytes(canonical)).hexdigest()


def read_package(path):
    """One bounded scan, including unknown entries, before any consumer uses bytes."""
    if os.path.getsize(path) > MAX_PACKAGE_BYTES:
        raise ValueError("This database archive is too large to open safely.")
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        check_entry_count(names, path)
        if not names or names[0] != MANIFEST_FILE:
            raise ValueError("manifest.json must be the first file in the archive.")
        data = {}; total = 0
        for entry in archive.infolist():
            value = read_entry_capped(archive, entry, path)
            total += len(value)
            if total > MAX_SCAN_BYTES:
                raise ValueError("This database expands beyond the total scan limit.")
            if not entry.is_dir():
                data[entry.filename] = value
        manifest = _json_loads(data[MANIFEST_FILE].decode("utf-8"))
        if not isinstance(manifest, dict) or manifest.get("format") != FORMAT_NAME or type(manifest.get("format_version")) is not int or manifest["format_version"] != FORMAT_VERSION:
            raise ValueError("Unsupported database manifest format.")
        require_database_id(manifest.get("database_id"))
        encryption = manifest.get("encryption", "none")
        if encryption not in ("none", ENCRYPTION_NAME):
            raise ValueError("Unsupported database encryption.")
        required = [PAYLOAD_FILE] if encryption == ENCRYPTION_NAME else [SOURCES_FILE, CHUNKS_FILE]
        files = manifest.get("files")
        if not isinstance(files, dict):
            raise ValueError("Missing database fingerprints.")
        import re
        for name in set(required) | set(files):
            record = files.get(name)
            expected = record.get("sha256") if isinstance(record, dict) else None
            if name not in data or not isinstance(expected, str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", expected):
                raise ValueError("Missing file or fingerprint: " + str(name))
            if "sha256:" + hashlib.sha256(data[name]).hexdigest() != expected:
                raise ValueError("Fingerprint mismatch for " + str(name))
        if encryption == ENCRYPTION_NAME:
            database_fingerprint(manifest)
        return manifest, data


def read_database_texts(path: str) -> dict:
    manifest, data = read_package(path)
    if manifest.get("encryption", "none") != "none":
        raise ValueError("This database is already encrypted. It cannot be encrypted twice.")
    return {"manifest": manifest, "sources": data[SOURCES_FILE].decode("utf-8"), "chunks": data[CHUNKS_FILE].decode("utf-8")}


def encrypt_database_file(
    input_path: str,
    output_path: str,
    content_key: bytes = None,
    creator: str = "",
    contact: str = "",
    creator_public_key: str = "",
):
    """Encrypt a plain `.dataeater` file into a locked one.

    :param content_key: reuse a key, or leave None to generate a fresh one
    :param creator:     a public name, shown to the customer
    :param contact:     a public email, shown to the customer
    :param creator_public_key: the ECDSA P-256 public key from `create-key`.
        It goes in the readable manifest, because the app needs it to check
        that an Unlock Code really came from this creator. Public keys are
        safe to publish - that is what they are for.
    :returns: (content_key, size_in_bytes)

    The content key is returned so the caller can store it in the creator's
    secret file. **If it is lost, the database can never be unlocked again**,
    not even by the creator.
    """
    if content_key is None:
        content_key = generate_content_key()

    texts = read_database_texts(input_path)
    manifest = texts["manifest"]

    if creator_public_key:
        read_creator_public_key(creator_public_key)
    payload = encrypt_payload(texts["chunks"], texts["sources"], content_key)

    # A copy of the public manifest with the lock applied. The old entries
    # for chunks.jsonl and sources.json are replaced by one for payload.enc.
    locked = dict(manifest)
    locked["encryption"] = ENCRYPTION_NAME
    locked["payload_nonce"] = base64.b64encode(payload.nonce).decode("ascii")
    if creator:
        locked["creator"] = creator
    if contact:
        locked["contact"] = contact
    if creator_public_key:
        locked["creator_public_key"] = creator_public_key
    # No expiry and no unlock code here: both belong to the licence.
    locked["files"] = {
        PAYLOAD_FILE: {
            "sha256": "sha256:" + hashlib.sha256(payload.ciphertext).hexdigest(),
            "bytes": len(payload.ciphertext),
        }
    }
    locked_manifest_text = json.dumps(locked, ensure_ascii=False, indent=2) + "\n"

    folder = os.path.dirname(os.path.abspath(output_path))
    if folder:
        os.makedirs(folder, exist_ok=True)

    with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(MANIFEST_FILE, locked_manifest_text)
        archive.writestr(PAYLOAD_FILE, payload.ciphertext)

    return content_key, os.path.getsize(output_path)


def read_secret_file(path: str) -> bytes:
    """Read a content key back out of a creator secret file.

    The file is JSON so a human can see what it is and never confuse it with
    a database.
    """
    with open(path, "r", encoding="utf-8") as handle:
        record = _json_loads(handle.read(65537))

    if record.get("format") != "dataeater-secret":
        raise ValueError("'%s' is not a DataEater secret file." % path)

    if record.get("version") != 1:
        raise ValueError("Unsupported secret version.")
    key = _decode64(record["content_key"])
    if len(key) != CONTENT_KEY_BYTES:
        raise ValueError("Content keys must be 32 bytes.")
    return key


# ---------------------------------------------------------------------------
# THE LICENCE ITSELF
# ---------------------------------------------------------------------------
# A licence is a small, signed, device-specific document. It contains no
# secret: the content key inside it can only be opened by the one phone whose
# public key it was made for.
#
# The ECDSA P-256 signature covers the whole licence, which is what stops a
# customer editing the expiry to give themselves more time. They cannot re-sign
# it, so any change makes the signature fail and the app refuses the code.

LICENCE_FORMAT = "dataeater-licence"
LICENCE_VERSION = 1


def create_creator_keypair():
    """A fresh ECDSA P-256 signing key pair for a database creator.

    :returns: (private_key, public_key)

    WHY ECDSA P-256 AND NOT ED25519
    -------------------------------
    Ed25519 was the original choice, and it is a fine algorithm. It was
    replaced because **most real Android phones cannot verify it.**

    Ed25519 reaches Android through Conscrypt, which arrived in stock Android
    13. Measured on the development phone (HarmonyOS, vivo): the registered
    crypto providers are

        AndroidNSSP, AndroidOpenSSL, CertPathProvider,
        AndroidKeyStoreBCWorkaround, BC, HarmonyJSSE, AndroidKeyStore

    There is no Conscrypt, and not one of them offers Ed25519. So on that
    phone every Unlock Code was refused.

    ECDSA with SHA-256 over P-256 is available on every Android from API 23,
    including all of the providers listed above. It is also the curve already
    used for key agreement, so the whole system now speaks one curve.

    See docs/SECURITY.md.
    """
    _, serialization, _, _, _ = _import_crypto()
    from cryptography.hazmat.primitives.asymmetric import ec

    private = ec.generate_private_key(ec.SECP256R1())
    return private, private.public_key()


def make_request_code(device_public_key) -> str:
    """The text a customer sends to the creator.

    It carries the phone's PUBLIC key and nothing else. A public key is safe
    to send: it cannot help anybody open anything without the matching
    private key, which never leaves the phone.

    This stands in for the code the Android app shows. The format matches on
    purpose so the two can be tested against each other.
    """
    _, serialization, _, _, _ = _import_crypto()
    der = device_public_key.public_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return base64.b64encode(der).decode("ascii")


def read_request_code(text: str):
    """Turn a Request Code back into the phone's public key."""
    _, serialization, ec, _, _ = _import_crypto()

    text = (text or "").strip()
    if not text:
        raise ValueError("The Unlock Request Code is empty.")

    try:
        der = _decode64(text)
    except Exception:
        raise ValueError("The Unlock Request Code is not valid base64.")

    try:
        key = serialization.load_der_public_key(der)
    except Exception:
        raise ValueError("The Unlock Request Code does not contain a public key.")

    if not isinstance(key, ec.EllipticCurvePublicKey):
        raise ValueError("The Request Code does not hold an EC public key.")
    if not isinstance(key.curve, ec.SECP256R1):
        raise ValueError(
            "That device uses curve '%s', but DataEater requires P-256."
            % key.curve.name
        )
    return key


def build_licence(
    content_key: bytes,
    device_public_key,
    expiry: str = None,
    database_id: str = "",
    extra: dict = None,
    database_fingerprint: str = None,
) -> dict:
    """Make a device-specific, optionally time-limited licence.

    :param content_key:     the database content key
    :param device_public_key: the customer's phone public key
    :param expiry:          an ISO date string, or None for "never"
    :returns: a JSON-serialisable licence. Not yet signed - see sign_licence.
    """
    require_database_id(database_id)
    wrap = wrap_content_key(content_key, device_public_key)

    licence = {
        "format": LICENCE_FORMAT,
        "version": LICENCE_VERSION,
        "database_id": database_id,
        # None is stored explicitly rather than left out, so the meaning is
        # clear to anyone reading the code.
        "expiry": expiry,
        "wrap": wrap,
    }
    if database_fingerprint is not None:
        import re
        if not re.fullmatch(r"sha256:[0-9a-f]{64}", database_fingerprint):
            raise ValueError("Invalid database binding fingerprint.")
        licence["database_fingerprint"] = database_fingerprint
    if extra:
        licence["extra"] = extra
    return licence


def _licence_signing_bytes(licence: dict) -> bytes:
    """The exact bytes a signature covers.

    Built by sorting the keys, so the same licence always produces the same
    bytes no matter which order the fields were added in. Without this, a
    signature could fail for a silly reason.
    """
    import copy as _copy
    copy = _copy.deepcopy(licence)
    copy.pop("signature", None)
    return json.dumps(copy, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False).encode("utf-8")


def sign_licence(licence: dict, signing_private_key) -> dict:
    """Sign a licence with the creator's ECDSA P-256 key.

    Everything in the licence except the signature itself is covered by it,
    including which key signed it. So a customer cannot change the expiry,
    the database, the wrapped key, or claim somebody else issued it.

    The signature is the DER form (SEQUENCE of r and s), which is exactly what
    Java's `SHA256withECDSA` expects and produces, so the two sides need no
    conversion.
    """
    hashes, serialization, ec, _, _ = _import_crypto()

    if not isinstance(signing_private_key, ec.EllipticCurvePrivateKey):
        raise ValueError("The signing key is not an EC key.")
    if not isinstance(signing_private_key.curve, ec.SECP256R1):
        raise ValueError(
            "The creator key uses curve '%s', but P-256 is required."
            % signing_private_key.curve.name
        )

    signed = dict(licence)
    signed["signed_by"] = base64.b64encode(
        signing_private_key.public_key().public_bytes(
            encoding=serialization.Encoding.DER,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
    ).decode("ascii")

    # Sign last, so the bytes cover every other field.
    #
    # `deterministic_signing` uses RFC 6979 instead of a random nonce. It
    # changes nothing about the security, and it means signing the same
    # licence twice gives the same signature — which is what lets the Android
    # tests pin exact expected values and lets a creator re-issue a code
    # without it looking different.
    signed["signature"] = base64.b64encode(
        signing_private_key.sign(
            _licence_signing_bytes(signed),
            ec.ECDSA(hashes.SHA256(), deterministic_signing=True),
        )
    ).decode("ascii")
    return signed


def verify_licence(licence: dict, creator_public_key) -> bool:
    """Check a signature. False means the licence was changed after signing.

    :raises ValueError: if the licence has no signature to check
    """
    hashes, _, ec, _, _ = _import_crypto()

    if "signature" not in licence:
        raise ValueError("This licence has no signature.")

    if not isinstance(creator_public_key, ec.EllipticCurvePublicKey) or not isinstance(creator_public_key.curve, ec.SECP256R1):
        raise ValueError("The creator key is not an EC public key.")

    signature = _decode64(licence["signature"])
    try:
        creator_public_key.verify(
            signature,
            _licence_signing_bytes(licence),
            ec.ECDSA(hashes.SHA256()),
        )
        return True
    except Exception:
        return False


def write_creator_key_file(path: str, private_key, public_key) -> str:
    """Save the creator's ECDSA P-256 key pair. Returns the public key text.

    The private key here is the most valuable secret in the whole system: it
    proves who issues licences. Anyone holding it can issue licences for any
    database this creator owns.
    """
    _, serialization, _, _, _ = _import_crypto()

    folder = os.path.dirname(os.path.abspath(path))
    if folder:
        os.makedirs(folder, exist_ok=True)

    private_der = private_key.private_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    public_der = public_key.public_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )

    record = {
        "format": "dataeater-creator-key",
        "version": 1,
        "algorithm": "ecdsa-p256-sha256",
        "private_key": base64.b64encode(private_der).decode("ascii"),
        "public_key": base64.b64encode(public_der).decode("ascii"),
        "warning": (
            "This is the creator's signing key. Anyone holding it can issue "
            "licences for every database you own. Never commit it, never "
            "send it to a customer, and keep a backup somewhere safe."
        ),
    }
    _write_private_record(path, record)

    return record["public_key"]


def read_creator_key_file(path: str):
    """Read a creator key pair back. Returns (private_key, public_key_text).

    The private key is stored in PKCS#8 form, which is the standard
    container for a private key, so it is loaded with the same standard
    loader rather than by guessing at the bytes.
    """
    _, serialization, _, _, _ = _import_crypto()

    with open(path, "r", encoding="utf-8") as handle:
        record = _json_loads(handle.read(65537))

    if record.get("format") != "dataeater-creator-key":
        raise ValueError("'%s' is not a DataEater creator key file." % path)

    private = serialization.load_der_private_key(_decode64(record["private_key"]), password=None)
    from cryptography.hazmat.primitives.asymmetric import ec
    public = read_creator_public_key(record["public_key"])
    if not isinstance(private, ec.EllipticCurvePrivateKey) or not isinstance(private.curve, ec.SECP256R1) or private.public_key().public_numbers() != public.public_numbers() or record.get("version") != 1:
        raise ValueError("Invalid or mismatched creator key pair.")
    return private, record["public_key"]


def read_creator_public_key(text: str):
    """Load a creator's PUBLIC key. Safe to publish.

    Stored and loaded in the same standard X.509 form used everywhere else
    in this project, so the key file and the manifest always agree.
    """
    _, serialization, _, _, _ = _import_crypto()
    from cryptography.hazmat.primitives.asymmetric import ec

    key = serialization.load_der_public_key(_decode64(text))
    if not isinstance(key, ec.EllipticCurvePublicKey):
        raise ValueError("That is not an EC creator public key.")
    if not isinstance(key.curve, ec.SECP256R1):
        raise ValueError(
            "That creator key uses curve '%s', but P-256 is required."
            % key.curve.name
        )
    return key


def parse_expiry(value: str):
    """Turn a creator's --expiry argument into an ISO date, or None.

    Accepted:
      never      -> None, the default
      30d 90d 1y -> today plus that much
      YYYY-MM-DD -> exactly that day

    The result is always an absolute date, because a licence may be issued
    now and opened months later, and "90 days" must not drift.
    """
    if value is None:
        return None
    text = value.strip().lower()

    if text in ("", "never", "none", "no"):
        return None

    from datetime import date, timedelta

    if text.endswith("d"):
        days = text[:-1]
        if days.isdigit():
            return (date.today() + timedelta(days=int(days))).isoformat()

    if text.endswith("y"):
        years = text[:-1]
        if years.isdigit():
            days = int(years) * 365
            return (date.today() + timedelta(days=days)).isoformat()

    try:
        return date.fromisoformat(text).isoformat()
    except ValueError:
        raise ValueError(
            "Cannot read expiry %r. Use never, 30d, 90d, 1y, or a date such "
            "as 2026-12-31." % value
        )


def encode_licence(licence: dict) -> str:
    """Pack a licence into the single string the customer pastes in."""
    return base64.b64encode(
        json.dumps(licence, sort_keys=True, separators=(",", ":"),
                   ensure_ascii=False).encode("utf-8")
    ).decode("ascii")


def decode_licence(text: str) -> dict:
    """Unpack the string a customer pasted in.

    :raises ValueError: on anything that is not a licence
    """
    cleaned = "".join((text or "").split())
    if not cleaned:
        raise ValueError("The Unlock Code is empty.")

    try:
        if len(cleaned) > 65536:
            raise ValueError("This Unlock Code is too large.")
        licence = _json_loads(_decode64(cleaned).decode("utf-8"))
    except Exception:
        raise ValueError("The Unlock Code could not be read.")

    if not isinstance(licence, dict) or licence.get("format") != LICENCE_FORMAT:
        raise ValueError("This is not a DataEater Unlock Code.")
    if type(licence.get("version")) is not int or licence["version"] != LICENCE_VERSION:
        raise ValueError("This Unlock Code has an unsupported version.")
    return licence


def _write_private_record(path, record):
    import tempfile
    folder = os.path.dirname(os.path.abspath(path))
    os.makedirs(folder, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".dataeater-key-", dir=folder)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(record, handle, indent=2)
            handle.flush(); os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def write_secret_file(path: str, content_key: bytes, database: str) -> None:
    """Save a content key where only the creator will look for it.

    This file is the single most sensitive thing in the project. It is
    covered by .gitignore, it is never sent to a customer, and losing it
    means the database can never be unlocked again.
    """
    folder = os.path.dirname(os.path.abspath(path))
    if folder:
        os.makedirs(folder, exist_ok=True)

    record = {
        "format": "dataeater-secret",
        "version": 1,
        "database": database,
        "content_key": base64.b64encode(content_key).decode("ascii"),
        "warning": (
            "Keep this file private. It is the only way to open this "
            "database. Never commit it and never send it to a customer."
        ),
    }
    _write_private_record(path, record)



# ---------------------------------------------------------------------------
# WRAPPING THE CONTENT KEY FOR ONE DEVICE
# ---------------------------------------------------------------------------
# This is what makes a licence device-specific. The database keeps ONE random
# content key; a second customer only needs a second wrapping, so the
# database is never re-encrypted.
#
# HOW IT WORKS
#   creator  makes an EPHEMERAL P-256 key pair, just for this one licence
#   shared  = ECDH(ephemeral private, device public)
#   key     = HKDF-SHA256(shared, salt, info)      RFC 5869
#   wrapped = AES-256-GCM(content key) under that key
#
# The phone does the mirror image with its own private key, so it recovers the
# content key without ever sending a private key anywhere.
#
# The constants below are the ones the ECDH spike verified on the target
# phone before this was written. They are duplicated in the Android code
# later, and both sides must agree exactly.

WRAP_CURVE_NAME = "secp256r1"
WRAP_SALT = b"\x00" * 16
WRAP_INFO = b"DataEater licence v1"
WRAP_FORMAT = "dataeater-wrap"
WRAP_VERSION = 1


def _import_crypto():
    """Import the crypto library and explain clearly if it is missing."""
    try:
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import ec
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        from cryptography.hazmat.primitives.kdf.hkdf import HKDF
    except ImportError as problem:  # pragma: no cover - depends on install
        raise RuntimeError(
            "The 'cryptography' package is not installed. Run:\n"
            "    tools/.venv/bin/pip install -r tools/requirements.txt"
        ) from problem
    return hashes, serialization, ec, AESGCM, HKDF


def generate_device_keypair():
    """A P-256 key pair standing in for a phone.

    **Used by the tests and by the future licence tool for checking a Request
    Code.** The real app generates its own pair inside AndroidKeyStore, where
    the private key is hardware-backed and cannot be exported. Nothing in the
    shipped code path calls this on a phone.
    """
    _, _, ec, _, _ = _import_crypto()
    return ec.generate_private_key(ec.SECP256R1())


def _derive_wrapping_key(shared_secret: bytes) -> bytes:
    """HKDF-SHA256, the agreed key derivation. RFC 5869."""
    hashes, _, _, _, HKDF = _import_crypto()
    return HKDF(
        algorithm=hashes.SHA256(),
        length=CONTENT_KEY_BYTES,
        salt=WRAP_SALT,
        info=WRAP_INFO,
    ).derive(shared_secret)


def wrap_content_key(content_key: bytes, device_public_key) -> dict:
    """Wrap a content key so only one particular device can open it.

    :param content_key:     the 32-byte random database key
    :param device_public_key: an EC P-256 public key
    :returns: a small JSON-serialisable envelope

    The envelope carries the creator's ephemeral public key, which is safe to
    send: it cannot help anybody open anything without the device's private
    key.
    """
    _, serialization, ec, AESGCM, _ = _import_crypto()

    if len(content_key) != CONTENT_KEY_BYTES:
        raise ValueError(
            "A content key must be %d bytes, got %d."
            % (CONTENT_KEY_BYTES, len(content_key))
        )
    if not isinstance(device_public_key, ec.EllipticCurvePublicKey):
        raise ValueError("The device public key is not an EC key.")
    if not isinstance(device_public_key.curve, ec.SECP256R1):
        raise ValueError(
            "The device uses curve '%s', but P-256 (%s) is required."
            % (device_public_key.curve.name, WRAP_CURVE_NAME)
        )

    ephemeral = ec.generate_private_key(ec.SECP256R1())
    shared = ephemeral.exchange(ec.ECDH(), device_public_key)
    wrapping_key = _derive_wrapping_key(shared)

    nonce = os.urandom(GCM_NONCE_BYTES)
    ciphertext = AESGCM(wrapping_key).encrypt(nonce, content_key, None)

    ephemeral_der = ephemeral.public_key().public_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )

    return {
        "format": WRAP_FORMAT,
        "version": WRAP_VERSION,
        "ephemeral_public_key": base64.b64encode(ephemeral_der).decode("ascii"),
        "nonce": base64.b64encode(nonce).decode("ascii"),
        "wrapped_key": base64.b64encode(ciphertext).decode("ascii"),
    }


def unwrap_content_key(envelope: dict, device_private_key) -> bytes:
    """Recover the content key. The exact inverse of :func:`wrap_content_key`.

    :raises ValueError:  if the envelope is malformed or the wrong curve
    :raises InvalidTag:  if this is not the device the key was wrapped for
    """
    _, serialization, ec, AESGCM, _ = _import_crypto()

    if envelope.get("format") != WRAP_FORMAT:
        raise ValueError("This is not a DataEater licence (format=%r)."
                         % envelope.get("format"))
    if type(envelope.get("version")) is not int or envelope["version"] != WRAP_VERSION:
        raise ValueError("Licence version is %r, expected %r."
                         % (envelope.get("version"), WRAP_VERSION))

    if not isinstance(device_private_key, ec.EllipticCurvePrivateKey) or not isinstance(device_private_key.curve, ec.SECP256R1):
        raise ValueError("The device private key is not an EC key.")

    ephemeral_public = serialization.load_der_public_key(
        _decode64(envelope["ephemeral_public_key"]))
    if not isinstance(ephemeral_public, ec.EllipticCurvePublicKey) or \
            not isinstance(ephemeral_public.curve, ec.SECP256R1):
        raise ValueError(
            "The licence was not made for P-256, so it cannot be used here."
        )

    shared = device_private_key.exchange(ec.ECDH(), ephemeral_public)
    wrapping_key = _derive_wrapping_key(shared)

    nonce = _decode64(envelope["nonce"]); wrapped = _decode64(envelope["wrapped_key"])
    if len(nonce) != 12 or len(wrapped) != CONTENT_KEY_BYTES + 16:
        raise ValueError("Invalid wrapped key or nonce length.")
    result = AESGCM(wrapping_key).decrypt(nonce, wrapped, None)
    if len(result) != CONTENT_KEY_BYTES:
        raise ValueError("Invalid content key length.")
    return result


@dataclass
class SourceRecord:
    """One document inside the database."""

    source_id: str
    title: str
    publisher: str = ""
    year: int = 0
    language: str = "en"
    license: str = "unknown"
    original_path: str = ""
    preparation_quality: dict = field(default_factory=dict)


@dataclass
class DatabaseBuild:
    """Everything that goes into one `.dataeater` file."""

    database_id: str
    name: str
    description: str = ""
    language: str = "en"
    license: str = "unknown"
    created_utc: str = ""
    sources: List[SourceRecord] = field(default_factory=list)
    chunks: List[Chunk] = field(default_factory=list)
    excluded_quality: list = field(default_factory=list)

    def finalise(self) -> None:
        """Fill in the timestamp. Called just before writing."""
        if not self.created_utc:
            self.created_utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        # Merging removes some intermediate IDs. Renumber the final collection,
        # otherwise the next document can reuse an earlier document's ID.
        for index, chunk in enumerate(self.chunks, 1):
            chunk.chunk_id = "c%03d" % index


@dataclass
class BuildReport:
    """What we produced, so the command line can report it honestly."""

    output_path: str
    database_name: str
    document_count: int
    chunk_count: int
    size_bytes: int
    skipped_documents: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)


def sha256_of_text(text: str) -> str:
    """Fingerprint of some text, written as 'sha256:<hex>'."""
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def render_sources(sources: List[SourceRecord]) -> str:
    payload = [
        {
            "id": source.source_id,
            "title": source.title,
            "publisher": source.publisher,
            "language": source.language,
            "license": source.license,
            "year": source.year,
            **({"preparation_quality": source.preparation_quality} if source.preparation_quality else {}),
        }
        for source in sources
    ]
    return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"


def render_chunks(chunks: List[Chunk]) -> str:
    lines = []
    for chunk in chunks:
        record = {
            "id": chunk.chunk_id,
            "source_id": chunk.source_id,
            "section": chunk.section,
            "page": chunk.page_start,
            "lang": "en",
            "text": chunk.text,
            "search_context": chunk.search_context,
        }
        lines.append(json.dumps(record, ensure_ascii=False))
    return "\n".join(lines) + ("\n" if lines else "")


def render_manifest(build: DatabaseBuild, chunks_text: str, sources_text: str) -> str:
    manifest = {
        "format": FORMAT_NAME,
        "format_version": FORMAT_VERSION,
        "database_id": build.database_id,
        "name": build.name,
        "description": build.description,
        "language": build.language,
        "created_utc": build.created_utc,
        "builder_version": BUILDER_VERSION,
        "license": build.license,
        # "none" for a free database. A locked database will say
        # "aes-256-gcm" here; the application already handles both.
        "encryption": "none",
        "counts": {
            "documents": len(build.sources),
            "chunks": len(build.chunks),
        },
        "files": {
            CHUNKS_FILE: {
                "sha256": sha256_of_text(chunks_text),
                "records": len(build.chunks),
            },
            SOURCES_FILE: {
                "sha256": sha256_of_text(sources_text),
            },
        },
    }
    return json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"


def write_database(build: DatabaseBuild, output_path: str) -> BuildReport:
    """Write the build out as a `.dataeater` file."""
    require_database_id(build.database_id)
    build.finalise()

    if build.excluded_quality and build.sources:
        build.sources[0].preparation_quality['excluded_documents'] = build.excluded_quality
    sources_text = render_sources(build.sources)
    chunks_text = render_chunks(build.chunks)
    manifest_text = render_manifest(build, chunks_text, sources_text)

    folder = os.path.dirname(os.path.abspath(output_path))
    if folder:
        os.makedirs(folder, exist_ok=True)

    # The archive is written with no compression on the manifest, which is
    # tiny anyway, so a reader can find it immediately at the front.
    import tempfile
    fd, stage = tempfile.mkstemp(prefix='.dataeater-build-', dir=folder)
    try:
        with os.fdopen(fd, 'wb') as handle:
            with zipfile.ZipFile(handle, "w", zipfile.ZIP_DEFLATED) as archive:
                archive.writestr(MANIFEST_FILE, manifest_text)
                archive.writestr(SOURCES_FILE, sources_text)
                archive.writestr(CHUNKS_FILE, chunks_text)
            handle.flush()
            os.fsync(handle.fileno())
        problems = verify_database(stage)
        if problems:
            raise ValueError('; '.join(problems))
        os.replace(stage, output_path)
    finally:
        if os.path.exists(stage):
            os.unlink(stage)

    return BuildReport(
        output_path=output_path,
        database_name=build.name,
        document_count=len(build.sources),
        chunk_count=len(build.chunks),
        size_bytes=os.path.getsize(output_path),
    )


def verify_database(path: str) -> List[str]:
    """Check required hashes, bounds and structure; this is not publisher authentication."""
    try:
        manifest, data = read_package(path)
        if manifest.get("encryption", "none") == ENCRYPTION_NAME:
            return []
        sources = _json_loads(data[SOURCES_FILE].decode("utf-8"))
        chunks = []
        for line in data[CHUNKS_FILE].decode("utf-8").splitlines():
            if line.strip():
                if len(chunks) >= 100000: raise ValueError("Too many passages.")
                chunks.append(_json_loads(line))
        if not isinstance(sources, list) or not all(isinstance(x, dict) for x in sources + chunks):
            raise ValueError("Invalid source or passage structure.")
        ids = [x.get("id") for x in sources]; cids = [x.get("id") for x in chunks]
        if any(not isinstance(x, str) or not x for x in ids + cids) or len(set(ids)) != len(ids) or len(set(cids)) != len(cids):
            raise ValueError("Missing or duplicate source/passage identifiers.")
        known = set(ids)
        if any(c.get("source_id") not in known for c in chunks):
            raise ValueError("A passage refers to an unknown source.")
        counts = manifest.get("counts", {})
        if not isinstance(counts, dict) or type(counts.get("documents")) is not int or type(counts.get("chunks")) is not int or counts["documents"] != len(sources) or counts["chunks"] != len(chunks):
            raise ValueError("The manifest counts do not match the database contents.")
        if len(sources) > 10000 or len(chunks) > 100000:
            raise ValueError("Too many sources or passages.")
        return []
    except (ValueError, KeyError, TypeError, AttributeError, OSError, zipfile.BadZipFile, RuntimeError) as problem:
        return ["Database verification failed: " + str(problem)]
