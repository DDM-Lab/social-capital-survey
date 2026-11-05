"""Check survey denominators, missingness, variation, and shared retention rules."""
import csv
import datetime as dt
import json
from pathlib import Path
import tempfile
import unittest

from general_analysis import duration_statistics, summarize
from post_processing import load_retained_records


def response(**fields):
    raw = {"_time": dt.datetime(2026, 11, 2, 12), "_person": "person",
           "Activity selection": "Eating/drinking", "fingerprintPeriod": "Lunch"}
    raw.update(fields)
    return raw


def find(rows, **keys):
    return next(r for r in rows if all(r[k] == v for k, v in keys.items()))


class AnalysisTests(unittest.TestCase):
    def test_selection_shares_are_distinct_from_visit_percentages(self):
        tables, meta = summarize([
            response(**{"Activity selection": "Eating/drinking,Studying/working,Eating/drinking,5"}),
            response(), response(**{"Activity selection": ""})])
        overall = tables["activities_overall"]
        eating = find(overall, activity="eating_drinking")
        self.assertEqual(eating["count"], 2)  # Duplicate selections count once per visit.
        self.assertEqual(eating["total_activity_selections"], 3)
        self.assertAlmostEqual(eating["percent_activity_selections"], 200 / 3)
        self.assertEqual(eating["total_visits"], 3)
        self.assertEqual(eating["visits_answering_activity"], 2)
        self.assertAlmostEqual(sum(r["percent_activity_selections"] for r in overall), 100)
        self.assertAlmostEqual(find(overall, activity="studying_working")["percent_visits"], 100 / 3)
        self.assertEqual(meta["legacy_planned_meeting_visits"], 1)
        self.assertEqual(meta["missing_activity_answers"], 1)

    def test_weekend_and_missing_groups_are_preserved(self):
        tables, meta = summarize([response(_time=dt.datetime(2026, 11, 1, 9), fingerprintPeriod="")])
        sunday = find(tables["activities_by_weekday"], group="Sunday", activity="eating_drinking")
        self.assertEqual(sunday["percent_activity_selections"], 100)
        monday = find(tables["activities_by_weekday"], group="Monday", activity="eating_drinking")
        self.assertIsNone(monday["percent_activity_selections"])
        self.assertEqual(meta["periods"], ["Unknown"])

    def test_means_include_zero_and_extremes_but_exclude_invalid_and_unselected(self):
        records = [response(**{"Activity duration#1_1_1": value})
                   for value in ["0", "1000", "", "-1", "nan"]]
        records.append(response(**{"Activity selection": "Studying/working", "Activity duration#1_1_1": "50"}))
        tables, meta = summarize(records)
        row = find(tables["durations"], activity="eating_drinking", timing="Planned")
        self.assertEqual(row["valid_n"], 2)
        self.assertEqual(row["mean_minutes"], 500)
        self.assertAlmostEqual(row["sd_minutes"], 707.1067811865476)
        self.assertEqual(row["invalid_n"], 2)
        self.assertEqual(row["missing_n"], 1)
        self.assertEqual(row["max_minutes"], 1000)
        self.assertEqual(meta["duration_details_without_selection"], 1)
        self.assertIsNone(duration_statistics([])["mean_minutes"])
        self.assertIsNone(duration_statistics([0])["sd_minutes"])

    def test_modes_include_ties_and_exclude_ambiguous_ratings(self):
        tables, _ = summarize([response(**{"Sentiment_1": value})
                               for value in ["Agree", "Strongly Agree", "Agree,Strongly Agree", ""]])
        row = find(tables["sentiment_modes"], group="Monday", statement="physical_comfort")
        self.assertEqual(row["modal_ratings"], "4; 5")
        self.assertEqual(row["valid_n"], 2)
        self.assertEqual(row["modal_count_each"], 1)
        self.assertEqual(row["percent_valid_each"], 50)
        self.assertEqual(row["invalid_n"], 1)
        self.assertEqual(row["missing_n"], 1)

    def test_encounters_distinguish_missing_zero_and_invalid(self):
        records = [response(**{"Group Num_1_1": count, "Group Num_1_4": category})
                   for count, category in [("0", "YES"), ("3", "Not Sure"), ("1.5", ""), ("", "unexpected")]]
        tables, _ = summarize(records)
        row = find(tables["encounter_totals"], relationship="acquaintance_classmate", encounter_type="entered_with")
        self.assertEqual((row["total_people"], row["valid_n"], row["invalid_n"], row["missing_n"]), (3, 2, 1, 1))
        rows = [r for r in tables["new_ideas_resources"] if r["relationship"] == "acquaintance_classmate"]
        self.assertEqual(sum(r["count"] for r in rows), 4)
        self.assertEqual(find(rows, answer="not sure")["count"], 1)
        self.assertIsNone(find(tables["encounter_totals"], relationship="close_friend", encounter_type="met")["total_people"])

    def test_empty_data_has_no_fabricated_percentages_or_means(self):
        tables, metadata = summarize([])
        self.assertEqual(metadata["retained_visits"], 0)
        self.assertIsNone(tables["activities_overall"][0]["percent_activity_selections"])
        self.assertIsNone(tables["durations"][0]["mean_minutes"])
        self.assertEqual(tables["sentiment_modes"][0]["modal_labels"], "")

    def test_shared_retention_preserves_seconds_and_exclusion_order(self):
        base = dict(Email="person", participantemail="", Status="IP Address", DistributionChannel="anonymous",
                    **{"Consent Form": "I consent to participate in this study."})
        rows = [dict(base, StartDate="2026-11-02 12:00:20", ResponseId="later"),
                dict(base, StartDate="2026-11-02 12:00:10", ResponseId="earlier"),
                dict(base, StartDate="2026-11-03 12:00:00", ResponseId="next_day"),
                dict(base, StartDate="2026-11-02 12:00:00", ResponseId="staff", Email="GROESSLI@example.org", Status="Survey Preview"),
                dict(base, StartDate="2026-11-02 12:00:00", ResponseId="preview", Status="Survey Preview"),
                dict(base, StartDate="2026-11-02 12:00:00", ResponseId="no_consent", **{"Consent Form": "No"}),
                dict(base, StartDate="2026-11-02 12:00:00", ResponseId="anonymous1", Email=""),
                dict(base, StartDate="2026-11-02 12:00:00", ResponseId="anonymous2", Email="")]
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "survey.csv"
            with source.open("w", encoding="utf-8", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
                writer.writeheader()
                writer.writerow({k: k for k in rows[0]})
                writer.writerow({k: json.dumps({"ImportId": k}) for k in rows[0]})
                writer.writerows(rows)
            raw, kept, excluded = load_retained_records(source)
        self.assertEqual(len(raw), 8)
        self.assertEqual({r["ResponseId"] for r in kept}, {"earlier", "next_day", "anonymous1", "anonymous2"})
        self.assertEqual(dict(excluded), {"staff": 1, "preview": 1, "no_consent": 1, "same_person_same_day_later_submission": 1})


if __name__ == "__main__":
    unittest.main()
