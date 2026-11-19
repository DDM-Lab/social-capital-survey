"""Privacy invariants: team exclusions, repeat matching, and no output leaks."""
import csv
import json
from pathlib import Path
import tempfile
import unittest

from audit_privacy import audit
from analysis import summarize_participation
from post_processing import load_retained_records
from protect_ids import KEY_NAME, is_pseudonym, protect_directory, pseudonymize


def write_export(path, records):
    fields = list(records[0])
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerow({field: field for field in fields})
        writer.writerow({field: json.dumps({"ImportId": field}) for field in fields})
        writer.writerows(records)


def record(email="research-subject@example.org", **changes):
    row = dict(Email=email, participantemail="RESEARCH-SUBJECT", RecipientEmail="",
               StartDate="2026-11-02 12:00:00", ResponseId="response-a", Finished="True",
               Status="IP Address", DistributionChannel="anonymous", fingerprintPeriod="Lunch",
               **{"Consent Form": "I consent to participate in this study.", "Unrelated": "unchanged"})
    row.update(changes)
    return row


class ProtectionTests(unittest.TestCase):
    def test_equivalent_ids_link_but_other_people_and_keys_do_not(self):
        key = b"a" * 32
        token = pseudonymize(" RESEARCH-SUBJECT@example.org ", key)
        self.assertTrue(is_pseudonym(token))
        self.assertEqual(token, pseudonymize("research-subject", key))
        self.assertEqual(token, pseudonymize(token, key))
        self.assertNotEqual(token, pseudonymize("other-subject", key))
        self.assertNotEqual(token, pseudonymize("research-subject", b"b" * 32))
        self.assertNotIn("research-subject", token)
        with self.assertRaises(ValueError):
            pseudonymize(token, b"b" * 32)
        with self.assertRaises(ValueError):
            pseudonymize("pid_v1_invalid", key)

    def test_staff_and_empty_cells_are_preserved_exactly(self):
        for value in (" GROESSLI@example.org ", "kelrod", "MDOCTORA", "shengq@example.org", "", " "):
            self.assertEqual(pseudonymize(value, b"a" * 32), value)

    def test_preview_is_read_only_apply_is_idempotent_and_retention_is_unchanged(self):
        rows = [record(), record(StartDate="2026-11-02 13:00:00", ResponseId="response-b"),
                record(StartDate="2026-11-03 12:00:00", ResponseId="response-c"),
                record("GROESSLI@example.org", participantemail="groessli", ResponseId="staff"),
                record("", participantemail="", RecipientEmail="contact@example.org", ResponseId="missing")]
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            source, key = folder / "survey.csv", folder / KEY_NAME
            write_export(source, rows)
            original = source.read_bytes()
            raw_before, kept_before, excluded_before = load_retained_records(source)
            stats_before = summarize_participation(raw_before)
            summary = protect_directory(folder, key)
            self.assertEqual(summary[0]["cells_to_protect"], 7)
            self.assertEqual(summary[0]["team_cells"], 2)
            self.assertEqual(source.read_bytes(), original)
            self.assertFalse(key.exists())
            protect_directory(folder, key, apply=True)
            protected = source.read_bytes()
            self.assertNotIn(b"research-subject", protected.lower())
            self.assertNotIn(b"contact@example.org", protected)
            self.assertIn(b"GROESSLI@example.org", protected)
            self.assertEqual(len(key.read_bytes()), 32)
            raw_after, kept_after, excluded_after = load_retained_records(source)
            self.assertEqual(stats_before, summarize_participation(raw_after))
            self.assertEqual(excluded_before, excluded_after)
            self.assertEqual([row["ResponseId"] for row in kept_before], [row["ResponseId"] for row in kept_after])
            for before, after in zip(raw_before, raw_after):
                self.assertEqual({k: v for k, v in before.items() if k not in {"Email", "participantemail", "RecipientEmail", "_person"}},
                                 {k: v for k, v in after.items() if k not in {"Email", "participantemail", "RecipientEmail", "_person"}})
            protect_directory(folder, key, apply=True)
            self.assertEqual(source.read_bytes(), protected)
            key.unlink()
            with self.assertRaises(ValueError):
                protect_directory(folder, key, apply=True)
            self.assertFalse(key.exists())
            self.assertEqual(source.read_bytes(), protected)

    def test_all_exports_are_validated_before_any_csv_changes(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            valid, invalid = folder / "a.csv", folder / "z.csv"
            write_export(valid, [record()])
            invalid.write_text("unexpected,csv\n1,2\n", encoding="utf-8")
            original = valid.read_bytes()
            key = folder / KEY_NAME
            with self.assertRaises(ValueError):
                protect_directory(folder, key, apply=True)
            self.assertEqual(valid.read_bytes(), original)
            self.assertFalse(key.exists())

    def test_same_key_links_separate_exports_and_mismatched_key_blocks_writes(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            first, second = folder / "first.csv", folder / "second.csv"
            write_export(first, [record()])
            write_export(second, [record("RESEARCH-SUBJECT", participantemail="research-subject@example.org")])
            key = folder / KEY_NAME
            protect_directory(folder, key, apply=True)
            first_raw, _, _ = load_retained_records(first)
            second_raw, _, _ = load_retained_records(second)
            self.assertEqual(first_raw[0]["Email"], second_raw[0]["Email"])
            original = first.read_bytes()
            key.write_bytes(b"x" * 32)
            with self.assertRaises(ValueError):
                protect_directory(folder, key, apply=True)
            self.assertEqual(first.read_bytes(), original)


class AuditTests(unittest.TestCase):
    def test_detects_bare_ids_email_patterns_and_identifying_columns_without_logging_values(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            data, cleaned = root / "data", root / "cleaned"
            data.mkdir(); cleaned.mkdir()
            write_export(data / "survey.csv", [record()])
            (cleaned / "safe.csv").write_text("participant_id,count\np0001,2\n", encoding="utf-8")
            self.assertEqual(audit(root, data)["issues"], [])
            (cleaned / "unsafe.csv").write_text("Email,note\nresearch-subject@example.org,research-subject\n", encoding="utf-8")
            result = audit(root, data)
            kinds = {issue["issue"] for issue in result["issues"]}
            self.assertEqual(kinds, {"identifying_columns", "email_address_pattern", "raw_nonteam_identity_match"})
            report = json.dumps(result)
            self.assertNotIn("research-subject", report)
            self.assertNotIn("example.org", report)


if __name__ == "__main__":
    unittest.main()
