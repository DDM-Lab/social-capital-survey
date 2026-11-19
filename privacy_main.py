"""Run cleaning, privacy audits, and source ID protection for every export."""
import argparse
import csv
import json
from pathlib import Path

from audit_privacy import audit
from post_processing import process
from protect_ids import KEY_NAME, ROOT, protect_directory

# EDIT THIS folder, or pass --data-dir on the command line.
INPUT_FOLDER = ROOT / "data"


def run(input_folder=INPUT_FOLDER, root=ROOT):
    input_folder = Path(input_folder).resolve()
    root = Path(root).resolve()
    output = root / "cleaned"
    if output.is_relative_to(input_folder) or input_folder.is_relative_to(output):
        raise ValueError("Input and cleaned output folders must be separate.")
    key = input_folder / KEY_NAME
    summaries = protect_directory(input_folder, key)  # Validate before writing.
    for summary in summaries:
        relative = Path(summary["file"])
        print(f"Cleaning {relative.as_posix()}")
        # Retain the filename suffix to avoid collisions between export folders.
        process(input_folder / relative, output / relative)
    # Audit before source protection so original IDs remain available for comparison.
    result = audit(root=root, data_dir=input_folder)
    print(json.dumps(result, indent=2))
    if result["issues"]:
        raise ValueError("Audit found issues; source IDs were not changed.")
    protect_directory(input_folder, key, apply=True)
    result = audit(root=root, data_dir=input_folder)
    if result["issues"]:
        print(json.dumps(result, indent=2))
        raise ValueError("Final audit found issues; review before sharing.")
    print(f"Completed {len(summaries)} exports. Cleaned tables: {output}")
    print(f"Source IDs replaced in place. Securely back up the private key: {key}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=INPUT_FOLDER)
    args = parser.parse_args()
    try:
        run(args.data_dir)
    except (OSError, UnicodeError, ValueError, KeyError, csv.Error) as error:
        # Avoid exposing field values through exception messages.
        parser.exit(1, f"Privacy procedure failed ({type(error).__name__}). "
                    "Review input format, paths, key, and any audit report. "
                    "Earlier outputs or source replacements may already have completed.\n")


if __name__ == "__main__":
    main()
