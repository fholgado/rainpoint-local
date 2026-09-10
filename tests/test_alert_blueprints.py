"""Exercise the shipped templates; HA frontend/service acceptance remains separate."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
import unittest

import jinja2
import yaml

ROOT = Path(__file__).resolve().parents[1]
DIRECTORY = ROOT / "blueprints/automation/rainpoint_local"


class BlueprintLoader(yaml.SafeLoader):
    pass


BlueprintLoader.add_constructor("!input", lambda loader, node: {"input": loader.construct_scalar(node)})


def load(name):
    return yaml.load((DIRECTORY / name).read_text(), Loader=BlueprintLoader)


class AlertBlueprintTest(unittest.TestCase):
    def render(self, template, **context):
        return jinja2.Environment(undefined=jinja2.StrictUndefined).from_string(template).render(**context).strip()

    def test_staleness_is_timestamp_based_including_unknown_and_future_clock(self):
        blueprint = load("stale_report.yaml")
        trigger = blueprint["triggers"][0]["value_template"]
        self.assertEqual(trigger, blueprint["conditions"][0]["value_template"])
        now = datetime(2026, 9, 10, tzinfo=timezone.utc)
        def as_timestamp(value, default=0):
            if isinstance(value, datetime): return value.timestamp()
            try: return datetime.fromisoformat(value).timestamp()
            except (ValueError, TypeError): return default
        cases = [(now.isoformat(), False), ((now - timedelta(hours=9)).isoformat(), True),
                 ((now - timedelta(hours=8)).isoformat(), False), ("unknown", True),
                 ("unavailable", True), ("bad-time", True),
                 ((now + timedelta(minutes=6)).isoformat(), True),
                 (now.astimezone(timezone(timedelta(hours=-4))).isoformat(), False)]
        for stamp, expected in cases:
            with self.subTest(stamp=stamp):
                result = self.render(trigger, report_entity="sensor.report", max_age_hours=8,
                    now=lambda: now, states=lambda _: stamp, as_timestamp=as_timestamp)
                self.assertEqual(str(expected), result)
        self.assertEqual(10, blueprint["blueprint"]["input"]["grace_minutes"]["default"])

    def test_valve_failure_alert_deduplicates_attributes_and_catches_new_transaction(self):
        template = load("valve_attention.yaml")["conditions"][0]["value_template"]
        failed = {"transaction_state": "failed", "transaction_id": "a"}
        for before, after, expected in [
            ({"transaction_state": "waiting_for_report"}, failed, True),
            (failed, dict(failed, some_unrelated_attribute=12), False),
            (failed, dict(failed, transaction_id="b"), True),
            (failed, {"transaction_state": "confirmed"}, False),
            ({}, {"overdue": True}, True),
            ({"overdue": True}, {"overdue": True}, False),
            ({}, {"command_pending": True}, False),
            (None, {}, False),
            ({}, None, False),
        ]:
            with self.subTest(before=before, after=after):
                trigger = SimpleNamespace(
                    from_state=SimpleNamespace(attributes=before) if before is not None else None,
                    to_state=SimpleNamespace(attributes=after) if after is not None else None)
                self.assertEqual(str(expected), self.render(template, trigger=trigger))

    def test_blueprints_have_no_builtin_actuation_and_preserve_ha_notification_first(self):
        for path in DIRECTORY.glob("*.yaml"):
            blueprint = load(path.name)
            self.assertEqual("automation", blueprint["blueprint"]["domain"])
            actions = blueprint["actions"]
            self.assertEqual("persistent_notification.create", actions[1]["action"])
            self.assertEqual({"input": "notify_actions"}, actions[2]["sequence"])
            self.assertEqual([], blueprint["blueprint"]["input"]["notify_actions"]["default"])
            for forbidden in ("valve.open_valve", "valve.close_valve", "script.turn_on", "rest_command."):
                self.assertNotIn(forbidden, path.read_text())


if __name__ == "__main__":
    unittest.main()
