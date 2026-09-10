"""Regression for the installation's scheduled-duration adapter, not RF timing."""
from pathlib import Path
import unittest

from jinja2 import Environment, StrictUndefined

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "examples/federico-garden/scheduled-duration.jinja"


class GardenScheduledDurationTest(unittest.TestCase):
    def render(self, setting):
        def states(entity):
            self.assertEqual("input_number.garden_watering_duration", entity)
            return setting
        return float(Environment(undefined=StrictUndefined).from_string(
            TEMPLATE.read_text()).render(states=states))

    def test_every_supported_minute_reaches_the_watering_script_unchanged(self):
        for minutes in range(1, 61):
            with self.subTest(minutes=minutes):
                self.assertEqual(minutes, self.render(str(minutes)))

    def test_invalid_setting_is_not_silently_replaced_with_a_watering_duration(self):
        for setting in ("unknown", "unavailable", "", "abc", "0", "-1", "61", "21.5", "nan", "inf"):
            with self.subTest(setting=setting):
                self.assertEqual(0, self.render(setting))


if __name__ == "__main__":
    unittest.main()
