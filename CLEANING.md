# Cleaning and analysis

The pipeline has three explicit steps. Use the cumulative November 5 export on
its own; do not combine it with overlapping October or November 19 exports.
Install plotting dependencies in your active environment with
`python -m pip install -r requirements.txt`.

```powershell
python protect_ids.py --input "data/2026-Grace-Hunt Library Survey_November 5, 2026_10.09.csv" --apply
python post_processing.py "data/2026-Grace-Hunt Library Survey_November 5, 2026_10.09.csv"
python analysis.py
```

1. **Privacy:** Replace non-staff email IDs in the selected source CSV. Back up
   originals and the private key; see [PRIVACY.md](PRIVACY.md).
2. **Post-processing:** Exclude staff, previews, and records without consent.
   Preserve every remaining submission, including same-day repeats and unfinished
   responses. Validate answers, flag issues, and write cleaned tables to `cleaned/`.
3. **Analysis:** Read only `cleaned/`, aggregate all findings, and generate all PNG
   charts and spatial maps. No source cleaning is repeated and no Markdown reports
   or interactive maps are generated.

| Location | Contents |
| --- | --- |
| `cleaned/visits.csv` | Submission/participant keys, weekday, hour, period, completion, sentiment, tablet category, relative day index |
| `cleaned/activities.csv` | Activity selections and planned/actual minutes |
| `cleaned/encounters.csv` | Encounter counts and new-ideas categories |
| `cleaned/map_cells.csv` | Valid grid selections, unique within each submission/activity |
| `cleaned/quality_flags.csv` | Missing, invalid, or ambiguous answer flags |
| `cleaned/audit.json` | Source filename, schema, exclusions, and retained counts |
| `results/plots/` | 11 aggregate charts plus spatial cluster and heatmap PNGs |
| `results/tables/` | Activity, duration, sentiment, encounter, participation, and map-frequency aggregates |
| `results/audit.json` | Run counts, exclusions, repeat/completion statistics, timing peaks, and plot filenames |

**Cleaning rules:** Missing/invalid numbers stay blank; valid zeros and extreme
nonnegative durations remain. Counts must be nonnegative integers. Sentiments use
1-5; ambiguous ratings are blank and flagged. Stress/distraction are not reverse
scored. Map coordinates must be integer columns 1-30 and rows 1-24. Duplicate cell
selections are removed, never duplicate submissions. Original identifiers, exact
dates, free text, IP/geolocation, and vouchers are not exported. Participant keys
are random per run, with no exported identity crosswalk.

`day_index` counts days from an undisclosed Monday, retaining calendar-week and
seven-day repeat checks without recording the original dates. It is local to one
export/run and must not be aligned across exports. Relative timing, weekday/hour,
and tablet category still carry identification risk; keep cleaned data restricted.

**Interpretation:** Activity charts show selection shares across the nine current
activities, summing to 100%; tables also provide percentages of all retained
submissions, which can sum above 100%. Legacy planned-meeting selections are
tracked separately (choice `5` is an inferred mapping). Duration means use selected
activities only; error bars are one sample SD. Missingness and sample sizes are
exported. Encounter totals count reported people, not distinct people. Maps count
cell selections, not occupancy or dwell time. Blank maps are not zero occupancy.
Participation counts require `Finished=True` or `1`; other analyses do not.
Repeated submissions remain separate and do not establish distinct physical visits.

Optional paths: `post_processing.py SOURCE --output-dir cleaned_other`, then
`analysis.py cleaned_other --output-dir results_other --dpi 180 --map FLOOR.png`.
Re-running replaces outputs at those locations. Old cleaned schemas are rejected;
regenerate them with the current post-processing script.
