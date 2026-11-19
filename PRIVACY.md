# Privacy

Run the three-stage pipeline in [CLEANING.md](CLEANING.md):
**protect IDs -> post-process -> analyze**.

```powershell
python protect_ids.py --input "data/2026-Grace-Hunt Library Survey_November 19, 2026_10.15.csv" --apply
```

- This **modifies the selected source CSV in place**. Omit `--apply` to preview.
  To process every CSV recursively in a folder, use `--data-dir "PATH"` instead
  of `--input`. Exports must have the three Qualtrics header rows.
- Only non-staff `Email`, `participantemail`, and `RecipientEmail` cells change.
  HMAC-SHA-256 creates stable pseudonyms using `<source-folder>/.participant-id.key`.
  Securely back up the original exports and key. Reuse the key for future exports;
  keep it separate from shared data. No decrypt command or identity crosswalk exists.
- Normalization ignores case, surrounding whitespace, and email domains. Staff IDs
  and other source fields remain readable. Source exports still contain sensitive
  information and must remain private.
- Post-processing removes identifying fields and free text from cleaned outputs.
  Random participant keys change each run. Relative days, weekday/hour, tablet
  categories, and attribute combinations can still identify people; this does not
  guarantee anonymity. Keep cleaned data restricted.
- `data/` and its key are Git-ignored, which does not encrypt or untrack files.
  Custom paths need their own controls/exclusions. On Windows, key permissions
  inherit the folder's access controls. Batch replacement is not transactional;
  recover partial runs with the same key.

Optional output check after analysis:

```powershell
python audit_privacy.py --input "data/2026-Grace-Hunt Library Survey_November 19, 2026_10.15.csv"
```

The audit checks `cleaned/` and `results/` for identifying columns, email patterns,
known raw IDs, and PNG text metadata. With already-protected references, original
bare IDs cannot be checked. It does not inspect rendered image text, backups, Git
history, or identity inference. Audit findings require review before sharing.
