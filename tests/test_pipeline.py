"""End-to-end invariants for the linear privacy -> cleaning -> analysis pipeline."""
import contextlib
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from analysis import load_cleaned, run, summarize, summarize_participation
from post_processing import load_retained_records, process
from protect_ids import KEY_NAME, protect_directory
from test_protect_ids import record, write_export


def complete_record(**changes):
    row = record()
    row.update({"Duration (in seconds)": "60", "Activity selection": ""})
    row.update({f"Sentiment_{i}": "" for i in range(1, 6)})
    row.update({f"Group Num_{i}_{j}": "" for i in range(1, 4) for j in range(1, 5)})
    row.update(changes)
    return row


class PipelineTests(unittest.TestCase):
    def test_cleaned_tables_preserve_statistics_and_work_without_source(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            data = root / "data"
            data.mkdir()
            source = data / "survey.csv"
            first = complete_record(**{"Activity selection": "Eating/drinking,5", "Sentiment_1": "ambiguous",
                "Activity duration#1_1_1": "-1", "Activity duration#2_1_1": "0",
                "Group Num_1_1": "1.5", "Group Num_1_4": "Not Sure",
                "Tablet Ident.": "#1: Tablet Near the Magazine Stand", "__js_MapEatingDrinking": "1,1;1,1"})
            second = complete_record(StartDate="2026-11-02 13:00:00", ResponseId="response-b")
            third = complete_record(StartDate="2026-11-09 12:00:00", ResponseId="response-c")
            unfinished = complete_record(Finished="False", ResponseId="unfinished")
            staff = complete_record(Email="groessli", participantemail="", ResponseId="staff")
            write_export(source, [first, second, third, unfinished, staff])
            raw, retained, _ = load_retained_records(source)
            expected_tables, expected_meta = summarize(retained)
            expected_participation = summarize_participation(raw)
            protect_directory(data, data / KEY_NAME, apply=True)
            with contextlib.redirect_stdout(io.StringIO()):
                process(source, root / "cleaned")
            source.unlink()
            cleaned, audit = load_cleaned(root / "cleaned")
            tables, metadata = summarize(cleaned)
            self.assertEqual(tables, expected_tables)
            self.assertEqual(metadata, expected_meta)
            self.assertEqual(len(cleaned), 4)  # All repeats, including unfinished, remain.
            self.assertEqual(len((root / "cleaned" / "map_cells.csv").read_text().splitlines()), 2)
            for path in (root / "cleaned").iterdir():
                self.assertNotIn("research-subject", path.read_text())
                self.assertNotIn("2026-11-02", path.read_text())
            map_path = root / "floor.png"
            map_path.touch()
            with patch("analysis.create_plots", return_value=[]), \
                    patch("analysis.create_spatial_plots", return_value=[]), \
                    contextlib.redirect_stdout(io.StringIO()):
                _, metadata = run(root / "cleaned", root / "results", map_path)
            self.assertEqual(metadata["participation_statistics"], expected_participation)
            self.assertTrue((root / "results" / "tables" / "map_cell_frequency.csv").is_file())
            self.assertEqual(list((root / "results").rglob("*.md")), [])
            self.assertFalse((root / "cleaned" / "analysis_summary.json").exists())

    def test_old_cleaned_schema_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            (folder / "audit.json").write_text('{"schema_version": 2}')
            with self.assertRaises(ValueError):
                load_cleaned(folder)

    def test_results_cannot_overwrite_cleaned_inputs(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            with self.assertRaises(ValueError):
                run(folder, folder)


if __name__ == "__main__":
    unittest.main()
