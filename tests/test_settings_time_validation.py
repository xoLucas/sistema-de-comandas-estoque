import unittest

from app.core.scheduler import _time_to_minutes
from app.validators.pydantic_mixins import normalize_hhmm, validate_setting_value


class SettingsTimeValidationTests(unittest.TestCase):
    def test_normalize_hhmm_accepts_short_hour(self):
        self.assertEqual(normalize_hhmm("3:00"), "03:00")
        self.assertEqual(normalize_hhmm(" 23:59 "), "23:59")

    def test_normalize_hhmm_rejects_invalid_values(self):
        for value in ("25:00", "18:60", "abc", "18", "", "1:2"):
            self.assertIsNone(normalize_hhmm(value))

    def test_validate_setting_value_normalizes_time_keys(self):
        self.assertEqual(
            validate_setting_value("auto_close_time", "3:00"), "03:00"
        )
        self.assertEqual(
            validate_setting_value("auto_open_time", "18:05"), "18:05"
        )

    def test_validate_setting_value_rejects_invalid_time(self):
        with self.assertRaises(ValueError):
            validate_setting_value("auto_close_time", "25:00")
        with self.assertRaises(ValueError):
            validate_setting_value("auto_open_time", "abc")

    def test_validate_setting_value_keeps_unrelated_keys(self):
        self.assertEqual(validate_setting_value("store_name", "Lads Beer"), "Lads Beer")

    def test_time_to_minutes_tolerates_legacy_values(self):
        self.assertEqual(_time_to_minutes("3:05"), 185)
        self.assertEqual(_time_to_minutes("03:05"), 185)
        self.assertIsNone(_time_to_minutes("99:99"))
        self.assertIsNone(_time_to_minutes(None))


if __name__ == "__main__":
    unittest.main()
