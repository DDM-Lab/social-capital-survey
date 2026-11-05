# Survey analysis tables

## General survey analysis

Run `python general_analysis.py` to analyze the cumulative November export and
write `analysis/report.md`, 11 PNG figures under `analysis/plots/`, eight aggregate
CSV tables under `analysis/tables/`, and `analysis/audit.json`.
Requires matplotlib and NumPy (`python -m pip install matplotlib numpy`).
It reuses retention and validation rules from the adjacent `post_processing.py`;
existing cleaned tables and spatial activity maps are not regenerated.
An alternative export/output folder can be specified with
`python general_analysis.py "survey.csv" --output-dir analysis_other --dpi 180`.

The figures cover tablet counts (including missing answers), separate activity
frequency and overall percentage charts, activity percentages by weekday and
voucher period, two additional activity heatmaps, average planned/actual minutes
with sample standard-deviation error bars, a compact modal sentiment table
(overall plus Monday-Friday), encounter totals, and new-ideas answer frequencies.
Weekday activity figures include weekends. Written responses are omitted.

For these analysis figures, activity percentages describe the **share of selections
among the nine current activities**, summing to 100% in each nonempty group.
The CSVs also include `percent_visits`, using all retained visits in that group.
Legacy planned-meeting selections are counted separately in the report.
This differs from the visit-based percentages in the cleaned summaries below.
Duration means include valid zeros and extreme values, and use only visits
selecting that activity; missing/invalid numbers are excluded. Error bars are
plus/minus one sample SD, not confidence intervals. Sample sizes, medians, maxima,
and missingness are exported for interpretation. Modal sentiment ties are preserved.

## Activity map visualization

Run `python plot_activity_map.py`, then open `activity_heatmap.html` in a browser.
The standalone file embeds the original PNG and cleaned selections; it needs no plotting packages, server, or network. Toggle activities, filter weekday/time period, switch between colored point clusters and grid heatmaps, hover for counts, and export the current overlay as SVG. Each activity's peak cell is labeled. Isolate activities to inspect overlaps. Point area scales with visit count; heatmap opacity increases with visit count. Both modes use a common maximum for the current filter. These are discrete cell selection frequencies, not smoothed density estimates or dwell times.

Optional paths: `python plot_activity_map.py --cells cleaned/map_cells.csv --visits cleaned/visits.csv --map survey_cad_full_labelled_3.png --output activity_heatmap.html`.

Run `python post_processing.py "2026-Grace-Hunt Library Survey_November 5, 2026_10.09.csv" --output-dir cleaned`.
Requires only Python's standard library. The source CSV is never modified.
The November export is cumulative; process it on its own rather than combining it with October.
After processing, rerun `python plot_activity_map.py` and
`python plot_activity_map_matplotlib.py` to refresh the interactive map and PNG plots
(the latter requires matplotlib and NumPy). These commands replace the current
cleaned tables and visualizations. Participant keys are regenerated together.
To reproduce the October results separately, use its source CSV with
`--output-dir cleaned_october`, and pass those tables and separate output paths
to the plotting scripts.

## Cleaning rules

Exclude the four staff IDs (case insensitive, accepting bare IDs or email addresses), previews, and records without affirmative consent. Exclusion categories are mutually exclusive, with staff checked first. Keep the earliest survey start per identified participant per local calendar day; review this policy if the first submission was a test or correction. Different-day visits remain eligible.

Remove original identifiers, response IDs, voucher codes, IP/geolocation, tablet location, exact dates/timestamps, and all free text from exported tables. Free text can contain names or identifying details and needs separate manual redaction before qualitative analysis. Anonymous participant keys preserve repeated-visit linkage, are randomly reassigned each run, and have no exported identity crosswalk. This reduces identification risk but does not guarantee anonymity against outside information. Treat the output as research data with appropriate access controls.

Use survey start time for weekday/hour (Eastern time). Both the October `M/D/YYYY HH:MM` and November `YYYY-MM-DD HH:MM:SS` export formats are accepted, with optional seconds in either format. Seconds, when present, are retained internally when choosing the earliest same-day submission. The time period is the original voucher period; its clock boundaries are not inferred, and it can differ from the start hour near a boundary. Do not infer visit duration from survey completion time.

Map activity choice `5` to `planned_meeting`, based on its exact correspondence with the seven planned-meeting map/reason records. This is a documented inference pending survey-definition confirmation. No planned-meeting duration is available. Absence after October 8 may reflect a survey revision; absence should not automatically be interpreted as behavioral change.

Missing numeric values remain blank, never zero. Reject negative/nonfinite durations and noninteger counts. Keep zero values. Ambiguous multiple sentiment ratings become blank and receive a quality flag. Sentiment scores run 1 (strongly disagree) to 5 (strongly agree); distraction and stress remain negatively worded and are not reverse scored. Normalize yes/no/not-sure capitalization; ambiguous numeric answers remain blank. Flag questionable answers without automatically dropping the entire visit.

Validate map cells as integers in columns 1–30 and rows 1–24. Remove duplicate cells within each visit/activity. Each row represents one selected grid cell, not a precise position or time spent there. Blank maps are not zero occupancy. Pixel centers use the supplied original image dimensions.

## Outputs

Join tables using `visit_id`; use `participant_id` for repeated-person analysis.

| File | One row per | Purpose |
| --- | --- | --- |
| visits.csv | Retained visit | Weekday, hour, voucher period, survey duration, five sentiment ratings |
| activities.csv | Visit/activity with a selection or details | Selection indicator, planned/actual minutes; details without selection are flagged |
| map_cells.csv | Visit/activity/selected cell | Grid indices and pixel centers for overlay on the supplied map |
| encounters.csv | Visit/relationship category | Three encounter counts and new ideas/resources response |
| quality_flags.csv | Detected issue | Anonymous visit key, field, issue type; no raw identifying values |
| activity_by_weekday_period.csv | Observed weekday/period/activity | Visit counts and proportion reporting each activity, including zero counts |
| map_cell_frequency.csv | Activity/observed cell | Number of retained visits selecting each cell |
| map_cell_frequency_by_weekday_period.csv | Weekday/period/activity/observed cell | Cell frequencies split by weekday and voucher period |
| audit.json | Processing run | Source filename, exclusions, retained counts, quality flags, grid/time conventions |

Activity percentages use all retained visits in each weekday/period as denominator and can sum above 100% because activities are multiple choice. A missing activity answer is not distinguishable from no selection in this summary; inspect missingness before interpreting other exports. To summarize locations by weekday/period, join map_cells.csv to visits.csv and count distinct visit_id within activity/cell/weekday/period. Planned/actual minutes are activity totals and cannot be assigned to individual cells. Heatmap frequencies measure selections, not occupancy or dwell time. Repeated visitors contribute multiple days; use participant clustering or participant weighting when appropriate. The tables do not correct for changing survey versions, sampling exposure, or unequal collection times.
