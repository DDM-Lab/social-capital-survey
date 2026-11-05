"""Generate survey question plots, aggregate CSVs, and a Markdown report.

Run: python general_analysis.py
Optional: python general_analysis.py "survey.csv" --output-dir analysis --dpi 180
Requires matplotlib and NumPy, plus the adjacent post_processing.py for shared
retention and numeric validation rules. Does not modify cleaned/ or existing maps.
"""
import argparse
import collections
import csv
import json
from pathlib import Path
import statistics

from post_processing import ACTIVITIES, SCALE, SENTIMENTS, load_retained_records, number

ROOT = Path(__file__).resolve().parent
DEFAULT_INPUT = ROOT / "2026-Grace-Hunt Library Survey_November 5, 2026_10.09.csv"
ACTIVITY_LABELS = {
    "eating_drinking": "Eating/drinking",
    "studying_working": "Studying/working",
    "reading_relaxing": "Reading/relaxing",
    "socializing": "Socializing",
    "taking_break": "Taking a break/people-watching",
    "club_event": "Attending an event/club activity",
    "passing_through": "Passing through",
    "scrolling_phone": "Scrolling phone/social media",
    "other": "Other",
}
DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
PERIOD_ORDER = ["Morning", "Lunch", "Afternoon", "Dinner", "Evening", "Late Night", "Off Hours", "Unknown"]
FEELINGS = dict(zip(SENTIMENTS, ["Physically comfortable", "Distracted", "Stressed or tense", "Safe", "Socially comfortable"]))
RELATIONSHIPS = {"acquaintance_classmate": "Acquaintances/classmates",
                 "nonclose_friend": "Non-close friends", "close_friend": "Close friends"}
COUNT_FIELDS = {"entered_with": "Entered with", "met": "Met", "ran_into": "Ran into"}
RATINGS = {v: k for k, v in SCALE.items()}
TABLET_LABELS = {"#1: Tablet Near the Magazine Stand": "Tablet #1: magazine stand",
                 "#2: Tablet Near De Fer's waiting area": "Tablet #2: De Fer waiting area"}


def percent(numerator, denominator):
    return 100 * numerator / denominator if denominator else None


def duration_statistics(values):
    """Use sample SD to describe answer variation; missing values stay missing."""
    return dict(valid_n=len(values), mean_minutes=statistics.mean(values) if values else None,
                sd_minutes=statistics.stdev(values) if len(values) > 1 else None,
                median_minutes=statistics.median(values) if values else None,
                max_minutes=max(values) if values else None)


def summarize(records):
    """Aggregate retained records only. No respondent-level data is returned."""
    observations = []
    for raw in records:
        observations.append(dict(raw=raw, weekday=DAYS[raw["_time"].weekday()],
                                 period=raw.get("fingerprintPeriod", "").strip() or "Unknown",
                                 selected=set(filter(None, raw.get("Activity selection", "").split(",")))))
    n = len(records)
    tables = {}
    tablet_counts = collections.Counter()
    for raw in records:
        answer = raw.get("Tablet Ident.", "").strip()
        tablet_counts[TABLET_LABELS.get(answer, "Other/unrecognized" if answer else "Missing")] += 1
    tablet_categories = list(TABLET_LABELS.values()) + ["Missing"]
    if tablet_counts["Other/unrecognized"]:
        tablet_categories.append("Other/unrecognized")
    tables["tablet"] = [dict(tablet=k, count=tablet_counts[k], total_visits=n,
                              percent_visits=percent(tablet_counts[k], n)) for k in tablet_categories]
    periods = {o["period"] for o in observations}
    periods = [p for p in PERIOD_ORDER if p in periods] + sorted(periods - set(PERIOD_ORDER))
    periods = periods or ["Unknown"]

    def activity_rows(group_field, groups):
        result = []
        for group in groups:
            subset = [o for o in observations if group_field is None or o[group_field] == group]
            counts = {a: sum(label in o["selected"] for o in subset)
                      for a, label, _ in ACTIVITIES[:9]}
            total = sum(counts.values())
            answered = sum(bool(o["raw"].get("Activity selection", "").strip()) for o in subset)
            for activity in ACTIVITY_LABELS:
                result.append(dict(group=group, activity=activity, count=counts[activity],
                                   total_activity_selections=total, total_visits=len(subset),
                                   visits_answering_activity=answered,
                                   percent_activity_selections=percent(counts[activity], total),
                                   percent_visits=percent(counts[activity], len(subset))))
        return result

    tables["activities_overall"] = activity_rows(None, ["Overall"])
    tables["activities_by_weekday"] = activity_rows("weekday", DAYS)
    tables["activities_by_period"] = activity_rows("period", periods)
    durations = []
    for i, (activity, label, _) in enumerate(ACTIVITIES[:9], 1):
        selected = [o["raw"] for o in observations if label in o["selected"]]
        for source, timing in [(1, "Planned"), (2, "Actual")]:
            raw_values = [r.get(f"Activity duration#{source}_{i}_1", "").strip() for r in selected]
            values = [v for v in map(number, raw_values) if v is not None]
            durations.append(dict(activity=activity, timing=timing, selected_visits=len(selected),
                                  missing_n=raw_values.count(""),
                                  invalid_n=sum(bool(v) and number(v) is None for v in raw_values),
                                  **duration_statistics(values)))
    tables["durations"] = durations
    feelings = []
    for group in ["Overall"] + DAYS[:5]:
        subset = [o["raw"] for o in observations if group == "Overall" or o["weekday"] == group]
        for i, field in enumerate(SENTIMENTS, 1):
            raw_values = [r.get(f"Sentiment_{i}", "").strip() for r in subset]
            counts = collections.Counter(SCALE[v] for v in raw_values if v in SCALE)
            maximum = max(counts.values(), default=0)
            modes = sorted(k for k, v in counts.items() if v == maximum)
            feelings.append(dict(group=group, statement=field,
                                 modal_ratings="; ".join(str(k) for k in modes),
                                 modal_labels=" / ".join(RATINGS[k] for k in modes),
                                 modal_count_each=maximum, valid_n=sum(counts.values()),
                                 percent_valid_each=percent(maximum, sum(counts.values())),
                                 missing_n=raw_values.count(""),
                                 invalid_n=sum(bool(v) and v not in SCALE for v in raw_values),
                                 total_visits=len(subset)))
    tables["sentiment_modes"] = feelings
    counts, resources = [], []
    for group, relationship in enumerate(RELATIONSHIPS, 1):
        for column, field in enumerate(COUNT_FIELDS, 1):
            answers = [r.get(f"Group Num_{group}_{column}", "").strip() for r in records]
            values = [v for v in (number(a, integer=True) for a in answers) if v is not None]
            counts.append(dict(relationship=relationship, encounter_type=field,
                               total_people=sum(values) if values else None, valid_n=len(values),
                               missing_n=answers.count(""),
                               invalid_n=sum(bool(a) and number(a, integer=True) is None for a in answers)))
        answers = [r.get(f"Group Num_{group}_4", "").strip().lower() for r in records]
        categories = ["yes", "no", "not sure"]
        frequencies = collections.Counter(answers)
        for category in categories + ["missing", "invalid"]:
            count = (frequencies[""] if category == "missing" else
                     sum(v for k, v in frequencies.items() if k and k not in categories)
                     if category == "invalid" else frequencies[category])
            resources.append(dict(relationship=relationship, answer=category, count=count,
                                  total_visits=n, percent_visits=percent(count, n)))
    tables["encounter_totals"] = counts
    tables["new_ideas_resources"] = resources
    known = {a[1] for a in ACTIVITIES}
    metadata = dict(retained_visits=n, periods=periods,
                    retained_identified_participants=len({r["_person"] for r in records if r["_person"]}),
                    missing_identity_visits=sum(not r["_person"] for r in records),
                    missing_activity_answers=sum(not o["raw"].get("Activity selection", "").strip() for o in observations),
                    legacy_planned_meeting_visits=sum("5" in o["selected"] for o in observations),
                    unknown_activity_visits=sum(bool(o["selected"] - known) for o in observations),
                    duration_details_without_selection=sum(
                        label not in o["selected"] and any(o["raw"].get(f"Activity duration#{t}_{i}_1", "").strip() for t in (1, 2))
                        for o in observations for i, (_, label, _) in enumerate(ACTIVITIES[:9], 1)))
    return tables, metadata


def save_tables(tables, destination):
    destination.mkdir(parents=True, exist_ok=True)
    for name, rows in tables.items():
        with (destination / f"{name}.csv").open("w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)


def create_plots(tables, metadata, destination, dpi):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np
    from matplotlib.ticker import PercentFormatter

    destination.mkdir(parents=True, exist_ok=True)
    plt.rcParams.update({"font.size": 10, "axes.spines.top": False, "axes.spines.right": False,
                         "axes.titleweight": "bold", "figure.facecolor": "white"})
    colors = list(plt.get_cmap("tab10").colors[:9])
    labels = list(ACTIVITY_LABELS.values())
    artifacts = []

    def save(fig, name, title, note):
        fig.suptitle(title, fontsize=15, fontweight="bold")
        fig.text(.02, .015, note, fontsize=9, va="bottom", color="#444444")
        fig.tight_layout(rect=(0, .10, 1, .94))
        filename = name + ".png"
        fig.savefig(destination / filename, dpi=dpi, bbox_inches="tight")
        plt.close(fig)
        artifacts.append((title, filename))

    fig, ax = plt.subplots(figsize=(10, 5))
    rows = tables["tablet"]
    bars = ax.bar([r["tablet"] for r in rows], [r["count"] for r in rows], color=["#4477aa", "#eeaa33", "#aaaaaa", "#999999"][:len(rows)])
    ax.bar_label(bars, labels=[f"{r['count']} ({r['percent_visits']:.1f}%)" if r["percent_visits"] is not None else "0 (no visits)" for r in rows], padding=4)
    ax.set_ylabel("Retained visits")
    ax.margins(y=.18)
    save(fig, "01_tablet", "Survey tablet", f"All {metadata['retained_visits']} retained visits; missing answers are shown explicitly.")

    rows = tables["activities_overall"]
    for field, name, title, axis_label in [
        ("count", "02_activity_frequencies", "Activity selection frequencies", "Visits selecting activity"),
        ("percent_activity_selections", "03_activity_percentages", "Overall activity selection shares", "Percentage of all nine activity selections")]:
        fig, ax = plt.subplots(figsize=(11, 7))
        values = [r[field] or 0 for r in rows]
        bars = ax.barh(labels, values, color=colors)
        ax.invert_yaxis()
        ax.bar_label(bars, labels=[str(r[field]) if field == "count" else
                                  f"{r[field]:.1f}%" if r[field] is not None else "N/A" for r in rows], padding=4)
        ax.set_xlabel(axis_label)
        ax.margins(x=.15)
        if field != "count":
            ax.xaxis.set_major_formatter(PercentFormatter())
        save(fig, name, title, f"Multiple selections allowed. Denominator: {rows[0]['total_activity_selections']} selections across the nine listed activities.")

    # Weekday and voucher-period comparisons use selection shares summing to 100%.
    matrices = []
    for table, groups, prefix, title in [
        ("activities_by_weekday", DAYS, "04", "weekday"),
        ("activities_by_period", metadata["periods"], "05", "voucher period")]:
        data = {(r["group"], r["activity"]): r for r in tables[table]}
        matrix = np.array([[data[g, a]["percent_activity_selections"] if data[g, a]["percent_activity_selections"] is not None else np.nan
                            for a in ACTIVITY_LABELS] for g in groups])
        group_labels = [f"{g}\n{data[g, next(iter(ACTIVITY_LABELS))]['total_visits']} visits\n"
                        f"{data[g, next(iter(ACTIVITY_LABELS))]['total_activity_selections']} selections" for g in groups]
        fig, ax = plt.subplots(figsize=(13, 8))
        bottom = np.zeros(len(groups))
        for i, label in enumerate(labels):
            values = np.nan_to_num(matrix[:, i])
            ax.bar(range(len(groups)), values, bottom=bottom, color=colors[i], label=label)
            for j, value in enumerate(values):
                if value >= 5:
                    ax.text(j, bottom[j] + value / 2, f"{value:.0f}%", ha="center", va="center", fontsize=9,
                            color="black", bbox=dict(facecolor="white", edgecolor="none", alpha=.8, pad=.8))
            bottom += values
        for j, row in enumerate(matrix):
            if np.isnan(row).all():
                ax.text(j, 3, "No selections", ha="center", rotation=90)
        ax.set(xticks=range(len(groups)), xticklabels=group_labels, ylim=(0, 103), ylabel="Share of activity selections")
        ax.tick_params(axis="x", labelsize=9)
        ax.yaxis.set_major_formatter(PercentFormatter())
        ax.legend(loc="upper center", bbox_to_anchor=(.5, -.15), ncol=3, frameon=False, fontsize=9)
        save(fig, prefix + "_activity_by_" + ("weekday" if title == "weekday" else "period"),
             "Activity selection shares by " + title,
             "Each bar totals 100% when selections exist. Percentages describe selections, not the percentage of visitors.")
        matrices.append((matrix, groups, group_labels, title))

    finite = [v for matrix, *_ in matrices for v in matrix.flat if np.isfinite(v)]
    maximum = max(finite, default=100) or 100
    for i, (matrix, groups, group_labels, title) in enumerate(matrices, 6):
        fig, ax = plt.subplots(figsize=(14, 7))
        cmap = plt.get_cmap("Blues").copy()
        cmap.set_bad("#eeeeee")
        plot = ax.imshow(np.ma.masked_invalid(matrix.T), vmin=0, vmax=maximum, cmap=cmap, aspect="auto")
        ax.set(xticks=range(len(groups)), xticklabels=group_labels, yticks=range(9), yticklabels=labels)
        for g in range(len(groups)):
            for a in range(9):
                value = matrix[g, a]
                ax.text(g, a, f"{value:.1f}%" if np.isfinite(value) else "N/A", ha="center", va="center",
                        color="white" if value > maximum * .6 else "black", fontsize=9)
        fig.colorbar(plot, ax=ax, label="Share of activity selections (%)")
        save(fig, f"{i:02d}_activity_heatmap_" + ("weekday" if title == "weekday" else "period"),
             "Activity selection heatmap by " + title,
             "Same denominator as the stacked bars. Heatmaps share a color scale; gray means no selections to calculate a share.")

    fig, ax = plt.subplots(figsize=(15, 8))
    x = np.arange(9)
    for timing, offset, color in [("Planned", -.2, "#4477aa"), ("Actual", .2, "#eeaa33")]:
        rows = [r for r in tables["durations"] if r["timing"] == timing]
        means = [r["mean_minutes"] if r["mean_minutes"] is not None else np.nan for r in rows]
        ax.bar(x + offset, means, width=.38, label=timing, color=color)
        for j, r in enumerate(rows):
            if r["sd_minutes"] is not None:
                ax.errorbar(x[j] + offset, r["mean_minutes"], yerr=r["sd_minutes"], fmt="none", ecolor="#333333", capsize=4)
            if r["mean_minutes"] is not None:
                endpoint = r["mean_minutes"] + (r["sd_minutes"] or 0)
                ax.annotate(f"{r['mean_minutes']:.1f} min\nn={r['valid_n']}", (x[j] + offset, endpoint),
                            xytext=(0, 5), textcoords="offset points", ha="center", fontsize=8)
            else:
                ax.annotate("No data", (x[j] + offset, 0), xytext=(0, 5), textcoords="offset points", ha="center", fontsize=7, rotation=90)
    ax.axhline(0, color="#888888", linewidth=.7)
    ax.set(xticks=x, xticklabels=labels, ylabel="Mean reported minutes (error bars: ±1 sample SD)")
    plt.setp(ax.get_xticklabels(), rotation=30, ha="right")
    ax.legend(frameon=False)
    save(fig, "08_planned_actual_minutes", "Average planned versus actual duration by activity",
         "Selected activities only; zeros included, missing/invalid answers excluded. All valid extremes retained. SD is undefined for n<2.\n"
         "Error bars describe answer variation; they are not confidence intervals. A lower SD endpoint can extend below zero.")

    # Compact mode table includes ties and n rather than converting ordinal ratings to means.
    groups = ["Overall"] + DAYS[:5]
    mode_lookup = {(r["group"], r["statement"]): r for r in tables["sentiment_modes"]}

    def mode_cell(row):
        if not row["valid_n"]:
            return "No valid ratings\nn=0"
        return f"{row['modal_labels']}\n{row['modal_count_each']}/{row['valid_n']} ({row['percent_valid_each']:.1f}%) each"

    fig, ax = plt.subplots(figsize=(18, 6))
    ax.axis("off")
    table = ax.table(cellText=[[mode_cell(mode_lookup[g, s]) for g in groups] for s in SENTIMENTS],
                     rowLabels=list(FEELINGS.values()), colLabels=groups, cellLoc="center", loc="center")
    table.auto_set_font_size(False)
    table.set_fontsize(8)
    table.scale(1, 3.8)
    for (row, column), cell in table.get_celld().items():
        if row == 0 or column == -1:
            cell.set_facecolor("#e6edf4")
    save(fig, "09_sentiment_modes", "Most common feelings: overall and Monday–Friday",
         "Overall includes weekends. All tied modes shown; count/valid n and percentage apply to EACH tied rating.\n"
         "Missing and ambiguous answers excluded. Original agreement wording preserved; distraction and stress are not reversed.")

    fig, ax = plt.subplots(figsize=(12, 6))
    rows = {(r["relationship"], r["encounter_type"]): r for r in tables["encounter_totals"]}
    x = np.arange(3)
    for i, (field, label) in enumerate(COUNT_FIELDS.items()):
        values = [rows[r, field]["total_people"] for r in RELATIONSHIPS]
        bars = ax.bar(x + (i - 1) * .25, [v if v is not None else np.nan for v in values], width=.24, label=label)
        ax.bar_label(bars, labels=[str(v) if v is not None else "N/A" for v in values], padding=3)
    ax.set(xticks=x, xticklabels=list(RELATIONSHIPS.values()), ylabel="Sum of reported people across visits")
    ax.margins(y=.2)
    ax.legend(frameon=False)
    save(fig, "10_encounter_totals", "Reported encounters by relationship",
         "Totals count reported people across visits, not distinct individuals. Zeros included; missing/invalid counts excluded. Valid n in CSV.")

    fig, ax = plt.subplots(figsize=(12, 6))
    answers = ["yes", "no", "not sure", "missing", "invalid"]
    lookup = {(r["relationship"], r["answer"]): r["count"] for r in tables["new_ideas_resources"]}
    bottom = np.zeros(3)
    for answer, color in zip(answers, ["#228833", "#cc6677", "#eecc66", "#bbbbbb", "#555555"]):
        values = np.array([lookup[r, answer] for r in RELATIONSHIPS])
        bars = ax.bar(x, values, bottom=bottom, color=color, label=answer.capitalize())
        ax.bar_label(bars, labels=[str(v) if v else "" for v in values], label_type="center")
        bottom += values
    ax.set(xticks=x, xticklabels=list(RELATIONSHIPS.values()), ylabel="Number of retained visits")
    ax.legend(loc="upper center", bbox_to_anchor=(.5, -.1), ncol=5, frameon=False)
    save(fig, "11_new_ideas_resources", "Did encounters provide new ideas or resources?",
         "Answer frequencies for all retained visits; missing answers are shown. No filtering based on encounter counts.")
    return artifacts


def markdown_table(headers, rows):
    def cell(value):
        return str(value).replace("|", "\\|").replace("\n", " ")
    return "\n".join(["| " + " | ".join(headers) + " |", "| " + " | ".join("---" for _ in headers) + " |"] +
                     ["| " + " | ".join(cell(v) for v in row) + " |" for row in rows])


def write_report(source, tables, metadata, artifacts, destination):
    n = metadata["retained_visits"]
    selection_total = tables["activities_overall"][0]["total_activity_selections"]
    lines = ["# Hunt Library survey analysis", "", f"Source: `{source.name}`.", "",
             f"Retained **{n} visits**, with **{metadata['retained_identified_participants']} identified participants** "
             f"and {metadata['missing_identity_visits']} visits without participant identity.", "",
             "## Reading the results", "",
             "The shared post-processing rules exclude staff, previews, and nonconsenting records, then keep the earliest identified participant submission per local day. "
             "Repeated visits on different days count separately. These are descriptive results without participant weighting or sampling-exposure corrections.", "",
             f"Exclusions: {json.dumps(metadata['excluded'], sort_keys=True)}.", "",
             "All activity percentage plots use the **share of selections across the nine listed activities**, summing to 100% within each group when selections exist. "
             "For example, a 40% Monday bar means 40% of Monday's activity selections, rather than 40% of Monday's visitors. "
             "The activity CSVs also include `percent_visits` (all retained visits in that group as denominator), which can sum above 100% for multiple-choice answers.", "",
             f"There are {selection_total} selections across the nine activities and {metadata['missing_activity_answers']} missing activity answers. "
             f"Legacy planned-meeting selections ({metadata['legacy_planned_meeting_visits']} visits) are reported here separately and excluded from the nine-activity charts and percentage denominators. "
             f"Unknown activity choices occur in {metadata['unknown_activity_visits']} visits and are also excluded from those denominators.", "",
             "Weekdays use survey start in Eastern time. Time categories use the recorded voucher periods; no new clock boundaries are inferred. "
             "Only observed voucher categories are plotted, including Unknown. Weekday activity charts include weekends. Sentiment comparisons cover Monday–Friday; overall sentiments include weekends.", "",
             "## Duration interpretation", "",
             "Bars show arithmetic mean planned/actual minutes for visits selecting each activity; error bars show **±1 sample standard deviation**, not standard error or confidence intervals. "
             "Zero answers are included. Missing, negative, or nonfinite values are excluded; SD is blank for fewer than two valid answers. "
             "Planned and actual means use their respective valid answers, so their sample sizes can differ. "
             "An SD endpoint below zero describes dispersion around the mean, not a negative observed duration. "
             "All valid extreme durations are retained; the CSV includes medians, maxima, and missing/invalid counts for review.", "",
             f"Duration details without a selected activity: {metadata['duration_details_without_selection']} visit/activity combinations; excluded from these mean comparisons.", ""]
    extremes = [r for r in tables["durations"] if r["max_minutes"] is not None and r["max_minutes"] > 240]
    if extremes:
        lines.extend(["Reported durations exceeding four hours (review examples, not an exclusion threshold):", "",
                      markdown_table(["Activity", "Timing", "Maximum minutes"],
                                     [[ACTIVITY_LABELS[r["activity"]], r["timing"], f"{r['max_minutes']:g}"] for r in extremes]), ""])
    lines.extend(["## Most common feelings", "",
                  "All tied modes are reported. Percentages refer to valid single-rating answers; missing and ambiguous answers are counted separately in the CSV. "
                  "Stress and distraction retain the original wording and are not reverse scored.", ""])
    mode_lookup = {(r["group"], r["statement"]): r for r in tables["sentiment_modes"]}
    groups = ["Overall"] + DAYS[:5]
    rows = []
    for statement in SENTIMENTS:
        row = [FEELINGS[statement]]
        for group in groups:
            r = mode_lookup[group, statement]
            row.append(f"{r['modal_labels']} ({r['modal_count_each']}/{r['valid_n']}; {r['percent_valid_each']:.1f}% each)" if r["valid_n"] else "No valid ratings")
        rows.append(row)
    lines.extend([markdown_table(["Statement"] + groups, rows), "", "## Encounter interpretation", "",
                  "Encounter totals sum reported people across visits and do not identify distinct individuals. "
                  "Valid zero counts contribute; missing/invalid counts do not. New-ideas plots show frequencies of Yes, No, Not sure, Missing, and Invalid answers across all retained visits. "
                  "CSV files include valid sample sizes and missingness.", "", "## Figures", ""])
    for title, filename in artifacts:
        lines.extend([f"### {title}", "", f"![{title}](plots/{filename})", ""])
    lines.extend(["## Aggregate tables", ""] +
                 [f"- [{name}.csv](tables/{name}.csv)" for name in tables] +
                 ["", "Existing spatial activity maps remain available through the separate mapping workflow. "
                  "This report excludes written responses and identifying fields.", ""])
    (destination / "report.md").write_text("\n".join(lines), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", nargs="?", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "analysis")
    parser.add_argument("--dpi", type=int, default=180)
    args = parser.parse_args()
    if args.dpi <= 0:
        parser.error("--dpi must be positive")
    source = args.input.resolve()
    destination = args.output_dir.resolve()
    protected = [ROOT / "cleaned", ROOT / "plots"]
    if any(destination == p or p in destination.parents for p in protected):
        parser.error("Use an analysis output directory separate from cleaned/ and the existing spatial plots/.")
    if source in [destination / "report.md", destination / "audit.json"] or any(
            p in source.parents for p in [destination / "tables", destination / "plots"]):
        parser.error("The source CSV must be outside the generated tables/ and plots/ directories.")
    raw, retained, excluded = load_retained_records(source)
    tables, metadata = summarize(retained)
    metadata.update(source_file=source.name, input_records=len(raw), excluded=dict(excluded),
                    activity_percentage_basis="Selections across the nine listed activities within group",
                    duration_error_bars="One sample standard deviation; not a confidence interval")
    save_tables(tables, destination / "tables")
    artifacts = create_plots(tables, metadata, destination / "plots", args.dpi)
    write_report(source, tables, metadata, artifacts, destination)
    (destination / "audit.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    print(f"Retained {len(retained)} of {len(raw)} records; generated {len(artifacts)} plots and {len(tables)} tables.")
    print(f"Report: {destination / 'report.md'}")


if __name__ == "__main__":
    main()
