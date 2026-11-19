# Privacy workflow

Keep a restricted backup of your original Qualtrics exports. Set `INPUT_FOLDER`
near the top of `privacy_main.py` (default: this repository's `data/`), then run:

```powershell
python privacy_main.py
```

Or override the folder without editing the script:

```powershell
python privacy_main.py --data-dir "C:\path\to\exports"
```

The runner finds CSVs recursively, validates them, generates cleaned tables,
audits generated artifacts while raw IDs are available, replaces source email
IDs, and audits again. Every CSV must be a three-header-row Qualtrics export.
Audit findings stop the procedure; review the report before sharing.

- **Source CSVs are modified in place.** Non-staff `Email`, `participantemail`,
  and `RecipientEmail` cells become stable HMAC-SHA-256 pseudonyms. Staff IDs,
  blanks, and other fields remain unchanged.
- **Separate cleaned files** go to `cleaned/<relative-export-filename.csv>/`.
  Re-running replaces these tables. Original identifiers, IP/geolocation, voucher
  details, exact dates, and free text are excluded. Random participant keys change
  each run and are independent across exports; do not join exports on these keys.
- **Securely back up `<input-folder>/.participant-id.key`.** Reuse it for future
  exports and keep it separate from shared data. There is no decrypt command or
  identity crosswalk. ID normalization ignores case, whitespace, and email domains.

This is pseudonymization, not guaranteed anonymity. Source exports still contain
sensitive fields; keep them private. Combinations of cleaned attributes may also
identify people. Audits inspect text, CSV columns, and PNG metadata, but do not
check rendered image text, backups, Git history, or identification by inference.
Already-protected exports cannot be compared against their original bare IDs.

`data/` and its key are Git-ignored; that does not encrypt files or remove tracked
data. Custom input folders need their own access controls and Git exclusions.
Windows key permissions inherit the folder's access controls. Failures can leave
partial outputs or some sources protected; correct the issue and rerun with the
same key.

For preview only: `python protect_ids.py` (no files or keys changed).
See [CLEANING.md](CLEANING.md) for cleaning rules and table definitions.

## Analysis after cleaning

The pipeline is **source exports -> cleaning and aggregation -> reports and maps**.
Cleaning also saves `analysis_summary.json`, containing aggregate statistics only,
including participation counts for all eligible repeat submissions. No daily
deduplication is applied.

```powershell
python general_analysis.py "cleaned/your-export.csv"
python plot_activity_map.py --cells "cleaned/your-export.csv/map_cells.csv" --visits "cleaned/your-export.csv/visits.csv"
```

General analysis reads saved aggregates; maps read cleaned tables. Neither repeats
source cleaning. Use the cumulative November export alone for the main analysis.
Regenerate cleaned outputs after this update to retain same-day repeats and create
the current saved summary; older summaries are rejected by the analysis command.
