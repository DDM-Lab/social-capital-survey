"""Exercise the privacy runner using temporary exports, never study data."""
import contextlib
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from general_analysis import load_analysis_summary, main as analysis_main, summarize, summarize_participation
from post_processing import load_retained_records, process
from privacy_main import run
from protect_ids import KEY_NAME, read_export, is_pseudonym
from test_protect_ids import record, write_export


def complete_record():
    row = record()
    row.update({"Duration (in seconds)": "60", "Activity selection": ""})
    row.update({f"Sentiment_{i}": "" for i in range(1, 6)})
    row.update({f"Group Num_{i}_{j}": "" for i in range(1, 4) for j in range(1, 5)})
    return row


class RunnerTests(unittest.TestCase):
    def test_nested_exports_have_separate_outputs_and_rerun_reuses_key(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            data = root / "data"
            (data / "nested").mkdir(parents=True)
            sources = [data / "survey.csv", data / "nested" / "survey.csv"]
            for source in sources:
                write_export(source, [complete_record()])
            with contextlib.redirect_stdout(io.StringIO()):
                run(data, root)
                key = (data / KEY_NAME).read_bytes()
                run(data, root)
            self.assertEqual(key, (data / KEY_NAME).read_bytes())
            for source in sources:
                self.assertTrue(is_pseudonym(read_export(source)[1][3][0]))
                self.assertTrue((root / "cleaned" / source.relative_to(data) / "visits.csv").is_file())

    def test_saved_summary_preserves_all_submissions_without_source(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "survey.csv"
            first = complete_record()
            second = dict(first, StartDate="2026-11-02 13:00:00", ResponseId="response-b")
            write_export(source, [first, second])
            raw, retained, _ = load_retained_records(source)
            expected_tables, _ = summarize(retained)
            expected_participation = summarize_participation(raw)
            with contextlib.redirect_stdout(io.StringIO()):
                process(source, root / "cleaned")
            source.unlink()  # Reporting must no longer require source data.
            tables, metadata = load_analysis_summary(root / "cleaned")
            self.assertEqual(tables, expected_tables)
            self.assertEqual(metadata["participation_statistics"], expected_participation)
            self.assertEqual(metadata["retained_visits"], 2)
            self.assertEqual(expected_participation["completed_submissions"], 2)
            text = (root / "cleaned" / "analysis_summary.json").read_text()
            self.assertNotIn("research-subject", text)
            self.assertNotIn("2026-11-02", text)
            with patch("sys.argv", ["general_analysis.py", str(root / "cleaned"),
                                    "--output-dir", str(root / "analysis")]), \
                    patch("general_analysis.create_plots", return_value=[]), \
                    contextlib.redirect_stdout(io.StringIO()):
                analysis_main()
            self.assertTrue((root / "analysis" / "report.md").is_file())
            self.assertTrue((root / "analysis" / "general_statistics.md").is_file())

    def test_audit_failure_leaves_source_ids_and_key_unchanged(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            data = root / "data"
            data.mkdir()
            source = data / "survey.csv"
            write_export(source, [complete_record()])
            original = source.read_bytes()
            (root / "analysis").mkdir()
            (root / "analysis" / "leak.txt").write_text("research-subject@example.org")
            with contextlib.redirect_stdout(io.StringIO()), self.assertRaises(ValueError):
                run(data, root)
            self.assertEqual(source.read_bytes(), original)
            self.assertFalse((data / KEY_NAME).exists())


if __name__ == "__main__":
    unittest.main()
