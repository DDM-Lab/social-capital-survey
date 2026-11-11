"""Timestamp compatibility checks for the October and November exports."""
import datetime as dt
import unittest

from post_processing import parse_start_time


class StartTimeTests(unittest.TestCase):
    def test_october_format(self):
        self.assertEqual(parse_start_time("10/1/2026 12:21"),
                         dt.datetime(2026, 10, 1, 12, 21))

    def test_november_format_preserves_seconds(self):
        self.assertEqual(parse_start_time("2026-11-04 21:59:23"),
                         dt.datetime(2026, 11, 4, 21, 59, 23))

    def test_optional_seconds_and_whitespace(self):
        expected = dt.datetime(2026, 11, 4, 21, 59)
        for value in ("2026-11-04 21:59", " 11/4/2026 21:59:00 "):
            with self.subTest(value=value):
                self.assertEqual(parse_start_time(value), expected)

    def test_invalid_dates_fail(self):
        for value in ("", "2026-02-30 12:00:00", "11/04/2026", "unrecognized"):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    parse_start_time(value)


if __name__ == "__main__":
    unittest.main()
