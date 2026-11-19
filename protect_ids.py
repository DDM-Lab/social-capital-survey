"""Pseudonymize non-team email IDs in local Qualtrics exports; preview by default.

python protect_ids.py                 # counts only; does not change CSVs or keys
python protect_ids.py --apply         # creates/reuses a private key and updates CSVs
See PRIVACY.md for key backups, audit instructions, and limitations.
"""
import argparse
import csv
import hashlib
import hmac
import io
import os
from pathlib import Path
import re
import secrets
import stat
import tempfile

from post_processing import STAFF, identity

ROOT = Path(__file__).resolve().parent
DEFAULT_DATA = ROOT / "data"
KEY_NAME = ".participant-id.key"
IDENTITY_FIELDS = {"email", "participantemail", "recipientemail"}
TOKEN_PREFIX = "pid_v1_"
TOKEN = re.compile(r"pid_v1_([0-9a-f]{16})_[0-9a-f]{64}\Z")
CONTEXT = b"social-capital-survey/participant/v1\0"


def is_pseudonym(value):
    return TOKEN.fullmatch(value.strip()) is not None


def key_id(key):
    return hashlib.sha256(CONTEXT + b"key-id\0" + key).hexdigest()[:16]


def pseudonymize(value, key):
    """Preserve blanks and team cells; normalize non-team IDs before keyed hashing."""
    normalized = identity(value)
    if not normalized or normalized in STAFF:
        return value
    if value.strip().lower().startswith(TOKEN_PREFIX):
        match = TOKEN.fullmatch(value.strip())
        if not match or match.group(1) != key_id(key):
            raise ValueError("Invalid pseudonym or key mismatch; use the original participant key.")
        return value
    digest = hmac.digest(key, CONTEXT + normalized.encode("utf-8"), "sha256").hex()
    return f"{TOKEN_PREFIX}{key_id(key)}_{digest}"


def read_export(path):
    """Validate before changing anything; preserve all three Qualtrics header rows."""
    original = path.read_bytes()
    rows = list(csv.reader(io.StringIO(original.decode("utf-8-sig"), newline="")))
    if len(rows) < 3 or "ImportId" not in "".join(rows[2]):
        raise ValueError(f"{path.name}: expected a three-header-row Qualtrics CSV.")
    if len(set(rows[0])) != len(rows[0]) or any(len(row) != len(rows[0]) for row in rows[1:]):
        raise ValueError(f"{path.name}: duplicate headers or inconsistent record widths.")
    columns = [i for i, field in enumerate(rows[0]) if field.casefold() in IDENTITY_FIELDS]
    if not columns:
        raise ValueError(f"{path.name}: no recognized email ID columns.")
    return original, rows, columns


def read_key(path):
    key = path.read_bytes()
    if len(key) != 32:
        raise ValueError("The participant key must contain exactly 32 bytes; restore its backup.")
    return key


def replace_export(path, original, rows):
    """Write beside the source and atomically replace it, checking for concurrent edits."""
    encoding = "utf-8-sig" if original.startswith(b"\xef\xbb\xbf") else "utf-8"
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding=encoding, newline="",
                                         dir=path.parent, prefix=".protect-", suffix=".tmp",
                                         delete=False) as stream:
            temporary = Path(stream.name)
            csv.writer(stream).writerows(rows)
            stream.flush()
            os.fsync(stream.fileno())
        if path.read_bytes() != original:
            raise ValueError(f"{path.name}: source changed during processing; no replacement made.")
        os.chmod(temporary, stat.S_IMODE(path.stat().st_mode))
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def protect_directory(data_dir, key_path, apply=False):
    data_dir = data_dir.resolve()
    if not data_dir.is_dir():
        raise ValueError("Data directory does not exist.")
    paths = sorted(data_dir.rglob("*.csv"))
    if not paths:
        raise ValueError("No CSV files found in the data directory.")
    exports = []
    for path in paths:
        if path.is_symlink() or not path.resolve().is_relative_to(data_dir):
            raise ValueError("Refusing a CSV symlink or a path outside the data directory.")
        original, rows, columns = read_export(path)
        exports.append((path, original, rows, columns))
    # Never silently rotate a missing key when protected data already exists.
    has_tokens = any(row[column].strip().lower().startswith(TOKEN_PREFIX)
                     for _, _, rows, columns in exports for row in rows[3:] for column in columns)
    key = read_key(key_path) if key_path.exists() else None
    if key is None and has_tokens:
        raise ValueError("Protected IDs exist but the key is missing. Restore the original key backup.")
    if key is None and apply:
        key = secrets.token_bytes(32)
    summaries = []
    for path, original, rows, columns in exports:
        counts = dict(records=len(rows) - 3, team_cells=0, protected_cells=0, cells_to_protect=0)
        for row in rows[3:]:
            for column in columns:
                value = row[column]
                normalized = identity(value)
                if not normalized:
                    continue
                if normalized in STAFF:
                    counts["team_cells"] += 1
                elif value.strip().lower().startswith(TOKEN_PREFIX):
                    # Validate both the format and the key, even in preview mode.
                    pseudonymize(value, key)
                    counts["protected_cells"] += 1
                else:
                    counts["cells_to_protect"] += 1
                    if apply:
                        row[column] = pseudonymize(value, key)
        summaries.append(dict(file=path.relative_to(data_dir).as_posix(), **counts))
    if apply:
        if not key_path.exists():
            key_path.parent.mkdir(parents=True, exist_ok=True)
            # Exclusive creation avoids replacing a key created by another process.
            descriptor = os.open(key_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(key)
                stream.flush()
                os.fsync(stream.fileno())
        elif read_key(key_path) != key:
            raise ValueError("Participant key changed during processing; no CSVs replaced.")
        # All exports and existing tokens have been validated before the first replacement.
        for (path, original, rows, _), summary in zip(exports, summaries):
            if summary["cells_to_protect"]:
                replace_export(path, original, rows)
    return summaries


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA)
    parser.add_argument("--key-file", type=Path,
                        help="Existing study key; default: data directory/.participant-id.key")
    parser.add_argument("--apply", action="store_true", help="Replace CSVs in place; otherwise preview counts only")
    args = parser.parse_args()
    key_path = args.key_file or args.data_dir / KEY_NAME
    try:
        summaries = protect_directory(args.data_dir, key_path, apply=args.apply)
    except (OSError, UnicodeError, ValueError, csv.Error) as error:
        parser.exit(1, f"Protection failed: {error}\n")
    print("Applied protection." if args.apply else "Preview only: no files or keys changed.")
    for summary in summaries:
        print("{file}: {records} records; {team_cells} team ID cells preserved; "
              "{protected_cells} already protected; {cells_to_protect} ID cells "
              .format(**summary) + ("protected." if args.apply else "to protect."))
    if args.apply:
        print("Back up the participant key securely and reuse it for every export. No identity crosswalk was written.")


if __name__ == "__main__":
    main()
