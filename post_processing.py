"""Clean the three-header-row Qualtrics export. Uses Python's standard library.

Usage: python post_processing.py "survey.csv" --output-dir cleaned
See CLEANING.md for table definitions and analytical limitations.
"""
import argparse
import collections
import csv
import datetime as dt
import json
import math
from pathlib import Path
import random

STAFF = {"groessli", "kelrod", "mdoctora", "shengq"}
ACTIVITIES = [
    ("eating_drinking", "Eating/drinking", "EatingDrinking"),
    ("studying_working", "Studying/working", "StudyingWorking"),
    ("reading_relaxing", "Reading/relaxing", "ReadingRelaxing"),
    ("socializing", "Socializing", "Socializing"),
    ("taking_break", "Taking a break/people-watching", "TakingABreak"),
    ("club_event", "Attending an event/club activity", "AttendingClubEvent"),
    ("passing_through", "Passing through", "PassingThrough"),
    ("scrolling_phone", "Scrolling phone/social media", "ScrollingPhone"),
    ("other", "Other:", "Other"),
    ("planned_meeting", "5", "MeetingSomeonePlanned"),
]
SENTIMENTS = ["physical_comfort", "distraction", "stress", "safety", "social_comfort"]
SCALE = {"Strongly Disagree": 1, "Disagree": 2, "Neutral": 3,
         "Agree": 4, "Strongly Agree": 5}


def identity(value):
    return value.strip().lower().split("@")[0]


def number(value, integer=False):
    try:
        n = float(value)
        if not math.isfinite(n) or n < 0 or (integer and not n.is_integer()):
            return None
        return int(n) if integer else n
    except (ValueError, TypeError):
        return None


def parse_start_time(value):
    """Read local Qualtrics timestamps from either export date format."""
    for format in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M",
                   "%m/%d/%Y %H:%M:%S", "%m/%d/%Y %H:%M"):
        try:
            return dt.datetime.strptime(value.strip(), format)
        except ValueError:
            pass
    raise ValueError("Unsupported StartDate; expected YYYY-MM-DD or M/D/YYYY with a local time.")


def write_table(directory, name, rows, fields):
    with (directory / name).open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def load_retained_records(source):
    """Read an export and apply consent, staff, and preview exclusions; preserve repeat submissions."""
    with source.open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.reader(f))
    if len(rows) < 3 or "ImportId" not in "".join(rows[2]):
        raise ValueError("Expected Qualtrics field names, question labels, and import metadata.")
    if len(set(rows[0])) != len(rows[0]) or any(len(r) != len(rows[0]) for r in rows[3:]):
        raise ValueError("Duplicate headers or inconsistent record widths.")
    records = [dict(zip(rows[0], r)) for r in rows[3:]]
    excluded = collections.Counter()
    eligible = []
    for d in records:
        # Both fields may contain the ID, with or without a domain.
        if any(identity(d.get(k, "")) in STAFF for k in ("Email", "participantemail")):
            excluded["staff"] += 1
        elif d["Status"] == "Survey Preview" or d["DistributionChannel"] == "preview":
            excluded["preview"] += 1
        elif d["Consent Form"].strip() != "I consent to participate in this study.":
            excluded["no_consent"] += 1
        else:
            d["_time"] = parse_start_time(d["StartDate"])
            d["_person"] = identity(d["Email"]) or identity(d["participantemail"])
            eligible.append(d)
    # Sort for stable visit numbering; retain every eligible submission.
    kept = sorted(eligible, key=lambda r: (r["_time"], r["ResponseId"]))
    return records, kept, excluded


def process(source, destination):
    source, destination = Path(source).resolve(), Path(destination).resolve()
    if source.is_relative_to(destination):
        raise ValueError("Source CSV must be outside the cleaned output folder.")
    records, kept, excluded = load_retained_records(source)
    # Fresh random IDs on each run; no identity mapping is exported.
    people = sorted({d["_person"] for d in kept if d["_person"]})
    shuffled = list(range(1, len(people) + 1))
    random.SystemRandom().shuffle(shuffled)
    person_ids = dict(zip(people, (f"p{i:04d}" for i in shuffled)))
    visits, activities, cells, encounters, issues = [], [], [], [], []

    def flag(visit, field, issue):
        issues.append(dict(visit_id=visit, field=field, issue=issue))

    # An undisclosed Monday origin preserves day/week gaps without exporting dates.
    first_day = min((d["_time"].date() for d in kept), default=dt.date(2000, 1, 3))
    monday_origin = first_day - dt.timedelta(days=first_day.weekday())
    for index, d in enumerate(kept, 1):
        vid = f"v{index:04d}"
        t = d["_time"]
        visit = dict(visit_id=vid, participant_id=person_ids.get(d["_person"], ""),
                     weekday=t.strftime("%A"), weekday_number=t.weekday(), hour=t.hour,
                     time_period=d["fingerprintPeriod"].strip() or "Unknown",
                     survey_duration_seconds=number(d["Duration (in seconds)"], True),
                     day_index=(t.date() - monday_origin).days,
                     finished=int(d.get("Finished", "").strip().lower() in {"true", "1"}),
                     tablet={"#1: Tablet Near the Magazine Stand": "tablet_1",
                             "#2: Tablet Near De Fer's waiting area": "tablet_2"}.get(
                                 d.get("Tablet Ident.", "").strip(),
                                 "other" if d.get("Tablet Ident.", "").strip() else "missing"),
                     activity_answered=int(bool(d.get("Activity selection", "").strip())))
        if not d["_person"]:
            flag(vid, "participant_id", "missing_identity_cannot_check_repeat_visits")
        for i, name in enumerate(SENTIMENTS, 1):
            raw = d[f"Sentiment_{i}"].strip()
            visit[name] = SCALE.get(raw)
            if raw and raw not in SCALE:
                flag(vid, name, "ambiguous_or_invalid_rating")
        visits.append(visit)
        selected = set(filter(None, d["Activity selection"].split(",")))
        if selected - {a[1] for a in ACTIVITIES}:
            flag(vid, "activities", "unknown_activity_choice")
        for i, (activity, label, suffix) in enumerate(ACTIVITIES, 1):
            raw_map = d.get("__js_Map" + suffix, "").strip()
            planned = d.get(f"Activity duration#1_{i}_1", "") if i <= 9 else ""
            actual = d.get(f"Activity duration#2_{i}_1", "") if i <= 9 else ""
            chosen = label in selected
            evidence = bool(raw_map or planned.strip() or actual.strip())
            if not chosen and not evidence:
                continue
            if not chosen:
                flag(vid, activity, "activity_details_without_selected_choice")
            a = dict(visit_id=vid, activity=activity, selected=int(chosen),
                     planned_minutes=number(planned), actual_minutes=number(actual))
            for raw, field in [(planned, "planned_minutes"), (actual, "actual_minutes")]:
                if raw.strip() and number(raw) is None:
                    flag(vid, activity + "." + field, "invalid_nonnegative_number")
            activities.append(a)
            unique = set()
            for pair in filter(None, raw_map.split(";")):
                try:
                    x, y = map(int, pair.split(","))
                    if not (1 <= x <= 30 and 1 <= y <= 24):
                        raise ValueError()
                except ValueError:
                    flag(vid, activity, "invalid_grid_cell")
                    continue
                if (x, y) in unique:
                    flag(vid, activity, "duplicate_grid_cell_removed")
                    continue
                unique.add((x, y))
                cells.append(dict(visit_id=vid, activity=activity, column=x, row=y,
                                  x_center_px=(x - .5) * 63.7,
                                  y_center_px=(y - .5) * 61.125))
        for group, relationship in enumerate(["acquaintance_classmate", "nonclose_friend", "close_friend"], 1):
            encounter = dict(visit_id=vid, relationship=relationship)
            for col, name in enumerate(["entered_with", "met", "ran_into"], 1):
                raw = d[f"Group Num_{group}_{col}"].strip()
                encounter[name] = number(raw, True)
                if raw and encounter[name] is None:
                    flag(vid, relationship + "." + name, "invalid_count")
            raw = d[f"Group Num_{group}_4"].strip().lower()
            encounter["new_ideas_resources"] = {"yes": "yes", "no": "no", "not sure": "not_sure"}.get(raw)
            if raw and encounter["new_ideas_resources"] is None:
                flag(vid, relationship + ".new_ideas_resources", "ambiguous_category")
            encounters.append(encounter)

    destination.mkdir(parents=True, exist_ok=True)
    write_table(destination, "visits.csv", visits, ["visit_id", "participant_id", "weekday", "weekday_number", "hour", "time_period", "survey_duration_seconds", "day_index", "finished", "tablet", "activity_answered"] + SENTIMENTS)
    write_table(destination, "activities.csv", activities, ["visit_id", "activity", "selected", "planned_minutes", "actual_minutes"])
    write_table(destination, "map_cells.csv", cells, ["visit_id", "activity", "column", "row", "x_center_px", "y_center_px"])
    write_table(destination, "encounters.csv", encounters, ["visit_id", "relationship", "entered_with", "met", "ran_into", "new_ideas_resources"])
    write_table(destination, "quality_flags.csv", issues, ["visit_id", "field", "issue"])
    audit = dict(schema_version=3, source_file=source.name, input_records=len(records), excluded=dict(excluded), retained_visits=len(visits),
                 retained_identified_participants=len(people), quality_flags=len(issues),
                 grid=dict(columns=30, rows=24, image_width=1911, image_height=1467),
                 time_basis="Survey start in America/New_York; day_index from an undisclosed Monday; time_period from voucher fingerprintPeriod")
    (destination / "audit.json").write_text(json.dumps(audit, indent=2), encoding="utf-8")
    print(json.dumps(audit, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--output-dir", type=Path, default=Path("cleaned"))
    args = parser.parse_args()
    if args.input.resolve().parent == args.output_dir.resolve():
        parser.error("Choose a separate output directory.")
    process(args.input, args.output_dir)
