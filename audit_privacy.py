"""Check generated artifacts for raw participant IDs without printing their values.

Run before protecting newly downloaded exports: python audit_privacy.py
Checks text/CSV content and PNG text metadata, not text rendered inside images.
"""
import argparse
import csv
import io
import json
from pathlib import Path
import re
import struct
import zlib

from post_processing import STAFF, identity
from protect_ids import DEFAULT_DATA, ROOT, is_pseudonym, read_export

EMAIL = re.compile(r"[A-Z0-9.!#$%&'*+/=?^_`{|}~-]{1,64}@[A-Z0-9.-]{1,253}\.[A-Z]{2,63}", re.I)
BLOCKED_FIELD = re.compile(
    r"email|recipient|ipaddress|latitude|longitude|responseid|externalreference|"
    r"^(startdate|enddate|recordeddate)$|fingerprint(timestamp|displaytimestamp|color|symbol)", re.I)
TEXT_SUFFIXES = {".csv", ".json", ".md", ".html", ".txt", ".svg"}


def png_text(blob):
    """Read PNG text chunks instead of treating compressed pixels as plain text."""
    if not blob.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ValueError("Invalid PNG signature.")
    texts, offset = [], 8
    while offset < len(blob):
        if offset + 12 > len(blob):
            raise ValueError("Truncated PNG chunk.")
        size = struct.unpack(">I", blob[offset:offset + 4])[0]
        kind = blob[offset + 4:offset + 8]
        payload = blob[offset + 8:offset + 8 + size]
        offset += size + 12
        if offset > len(blob):
            raise ValueError("Truncated PNG data.")
        if kind == b"tEXt":
            texts.append(payload.decode("latin1"))
        elif kind == b"zTXt":
            keyword, rest = payload.split(b"\0", 1)
            if rest[0] != 0:
                raise ValueError("Unknown PNG text compression.")
            texts.append(keyword.decode("latin1") + " " + zlib.decompress(rest[1:]).decode("latin1"))
        elif kind == b"iTXt":
            keyword, rest = payload.split(b"\0", 1)
            compressed, method = rest[:2]
            _, _, text = rest[2:].split(b"\0", 2)
            if compressed not in (0, 1) or method != 0:
                raise ValueError("Unknown international PNG text compression.")
            if compressed:
                text = zlib.decompress(text)
            texts.append(keyword.decode("latin1") + " " + text.decode("utf-8"))
        if kind == b"IEND":
            break
    return "\n".join(texts)


def reference_ids(data_dir, reference_file=None):
    identifiers = set()
    for path in ([reference_file] if reference_file else data_dir.rglob("*.csv")):
        _, rows, columns = read_export(path)
        for row in rows[3:]:
            for column in columns:
                value = row[column].strip()
                normalized = identity(value)
                if normalized and normalized not in STAFF and not is_pseudonym(value):
                    identifiers.add(normalized)
                    if "@" in value:
                        identifiers.add(value.casefold())
    return identifiers


def audit(root=ROOT, data_dir=DEFAULT_DATA, reference_file=None):
    if not data_dir.is_dir() or not any(data_dir.rglob("*.csv")):
        raise ValueError("Reference exports are missing; specify --data-dir containing the study exports.")
    identifiers = reference_ids(data_dir, reference_file)
    known = (re.compile(r"(?<![\w])(?:" + "|".join(re.escape(v) for v in sorted(identifiers)) + r")(?![\w])", re.I)
             if identifiers else None)
    paths = {path for folder in ("cleaned", "results")
             for path in (root / folder).rglob("*") if path.is_file()}
    if (root / "activity_heatmap.html").is_file():
        paths.add(root / "activity_heatmap.html")
    if not paths:
        raise ValueError("No generated artifacts found to audit.")
    issues, csvs, pngs = [], 0, 0
    for path in sorted(paths):
        relative = path.relative_to(root).as_posix()
        if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
            issues.append(dict(file=relative, issue="symlink_or_external_path"))
            continue
        try:
            if path.suffix.lower() == ".png":
                text = png_text(path.read_bytes())
                pngs += 1
            elif path.suffix.lower() in TEXT_SUFFIXES:
                text = path.read_text(encoding="utf-8-sig")
            else:
                issues.append(dict(file=relative, issue="unsupported_artifact_requires_review"))
                continue
            if path.suffix.lower() == ".csv":
                csvs += 1
                fields = next(csv.reader(io.StringIO(text)), [])
                blocked = sum(bool(BLOCKED_FIELD.search(field)) for field in fields)
                if blocked:
                    issues.append(dict(file=relative, issue="identifying_columns", count=blocked))
            # Embedded PNG pixels are inspected through PNG metadata, not their base64 encoding.
            if path.suffix.lower() in {".html", ".svg"}:
                text = re.sub(r"data:image/[^;]+;base64,[A-Za-z0-9+/=\r\n]+", "", text)
            emails = len(EMAIL.findall(text))
            if emails:
                issues.append(dict(file=relative, issue="email_address_pattern", count=emails))
            matches = len(known.findall(text)) if known else 0
            if matches:
                issues.append(dict(file=relative, issue="raw_nonteam_identity_match", count=matches))
        except (OSError, UnicodeError, ValueError, csv.Error, zlib.error, IndexError) as error:
            issues.append(dict(file=relative, issue="unreadable_artifact", error_type=type(error).__name__))
    return dict(files_checked=len(paths), csvs_checked=csvs, png_metadata_checked=pngs,
                reference_identity_values=len(identifiers), issues=issues,
                limitations=["No OCR of rendered image pixels; review plot generation code and labels.",
                             "No inference of identity from combinations of visit attributes.",
                             "Bare-ID matching requires unprotected reference exports; zero reference values means this check is unavailable.",
                             "Does not inspect Git object storage, old backups, or remote caches."])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA)
    parser.add_argument("--input", type=Path, help="Use only this CSV as the reference export")
    args = parser.parse_args()
    try:
        result = audit(data_dir=args.input.parent if args.input else args.data_dir, reference_file=args.input)
    except (OSError, UnicodeError, ValueError, csv.Error) as error:
        parser.exit(1, f"Audit failed: {type(error).__name__}; check reference exports and paths.\n")
    print(json.dumps(result, indent=2))
    raise SystemExit(bool(result["issues"]))


if __name__ == "__main__":
    main()
