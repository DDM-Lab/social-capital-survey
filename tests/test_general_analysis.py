"""Check survey denominators, missingness, variation, and shared retention rules."""
import csv
import datetime as dt
import json
from pathlib import Path
import tempfile
import unittest

from general_analysis import (duration_statistics, summarize, summarize_participation,
                              write_participation_report)
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


def completion(person, start, **fields):
    record = dict(Email=person, participantemail="", StartDate=start, Finished="True",
                  Status="IP Address", DistributionChannel="anonymous", fingerprintPeriod="Lunch",
                  **{"Consent Form": "I consent to participate in this study."})
    record.update(fields)
    return record


class ParticipationTests(unittest.TestCase):
    def test_completion_filter_identity_normalization_and_raw_same_day_repeats(self):
        rows = [completion(" Person@example.org ", "2026-11-02 12:00:00"),
                completion("", "2026-11-02 12:01:00", participantemail="PERSON"),
                completion("", "2026-11-02 12:02:00"),
                completion("incomplete", "2026-11-02 12:00:00", Finished="False"),
                completion("GROESSLI@example.org", "2026-11-02 12:00:00", Status="Survey Preview"),
                completion("", "2026-11-02 12:00:00", participantemail="SHENGQ", Finished="False"),
                completion("preview", "2026-11-02 12:00:00", DistributionChannel="preview"),
                completion("nonconsenting", "2026-11-02 12:00:00", **{"Consent Form": "No"})]
        stats = summarize_participation(rows)
        self.assertEqual(stats["completed_submissions"], 3)
        self.assertEqual(stats["unique_participant_ids"], 1)
        self.assertEqual(stats["identified_completed_submissions"], 2)
        self.assertEqual(stats["missing_identity_submissions"], 1)
        self.assertEqual(stats["same_day_participants"], 1)
        self.assertEqual(stats["extra_same_day_submissions"], 1)
        self.assertEqual(stats["excluded"], {"staff": 2, "preview": 1, "no_consent": 1, "not_finished": 1})

    def test_calendar_week_vs_rolling_window_and_exact_seven_day_boundary(self):
        rows = [completion("boundary", "2026-11-01 23:00:00"),
                completion("boundary", "2026-11-02 01:00:00"),
                completion("seven_days", "2026-11-02 10:00:00"),
                completion("seven_days", "2026-11-09 09:00:00"),
                completion("year_boundary", "2026-12-31 10:00:00"),
                completion("year_boundary", "2027-01-01 10:00:00")]
        stats = summarize_participation(rows)
        self.assertEqual(stats["repeat_participants"], 3)
        self.assertEqual(stats["same_calendar_week_participants"], 1)
        self.assertEqual(stats["different_day_same_week_participants"], 1)
        self.assertEqual(stats["rolling_seven_day_participants"], 2)
        self.assertEqual(stats["different_day_rolling_seven_day_participants"], 2)
        self.assertEqual(stats["same_day_participants"], 0)

    def test_repeat_breakdown_is_exhaustive_and_nonoverlapping(self):
        rows = [completion("both", "2026-11-02 10:00:00"),
                completion("both", "2026-11-02 11:00:00"),
                completion("both", "2026-11-03 10:00:00"),
                completion("day_only", "2026-11-02 10:00:00"),
                completion("day_only", "2026-11-02 11:00:00"),
                completion("week_only", "2026-11-02 10:00:00"),
                completion("week_only", "2026-11-03 11:00:00"),
                completion("neither", "2026-11-02 10:00:00"),
                completion("neither", "2026-11-16 11:00:00")]
        stats = summarize_participation(rows)
        self.assertEqual(stats["repeat_participants"], 4)
        for field in ["same_day_and_different_day_same_week", "same_day_without_different_day_same_week",
                      "different_day_same_week_without_same_day", "repeats_without_same_day_or_different_day_same_week"]:
            self.assertEqual(stats[field], 1, field)
        self.assertEqual(stats["same_day_participants"], 2)
        self.assertEqual(stats["same_calendar_week_participants"], 3)
        self.assertEqual(stats["different_day_same_week_participants"], 2)

    def test_timing_ties_include_anonymous_completions_and_unknown_period(self):
        rows = [completion("a", "2026-11-02 12:00:00"),
                completion("", "2026-11-03 12:00:00", fingerprintPeriod="")]
        stats = summarize_participation(rows)
        self.assertEqual(len(stats["timing_peaks"]["weekday"]), 2)
        self.assertEqual(stats["timing_peaks"]["start_hour"][0]["count"], 2)
        self.assertEqual(stats["timing_peaks"]["start_hour"][0]["percent_completions"], 100)
        self.assertEqual(len(stats["timing_peaks"]["voucher_period"]), 2)

    def test_empty_statistics_and_report_have_no_identifier_values(self):
        empty = summarize_participation([])
        self.assertEqual(empty["unique_participant_ids"], 0)
        self.assertEqual(empty["timing_peaks"]["weekday"], [])
        stats = summarize_participation([completion("sensitive-person@example.org", "2026-11-02 12:00:00")])
        with tempfile.TemporaryDirectory() as tmp:
            destination = Path(tmp)
            write_participation_report(Path("survey.csv"), stats, destination)
            report = (destination / "general_statistics.md").read_text(encoding="utf-8")
            write_participation_report(Path("empty.csv"), empty, destination)
            self.assertIn("No completed surveys", (destination / "general_statistics.md").read_text(encoding="utf-8"))
        self.assertNotIn("sensitive-person", report)
        self.assertNotIn("sensitive-person", json.dumps(stats))
        self.assertIn("Unique normalized non-staff participant IDs", report)


if __name__ == "__main__":
    unittest.main()
