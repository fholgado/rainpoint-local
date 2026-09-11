"""Per-association isolation and upgrade preservation, with no physical RF."""
from dataclasses import replace
from pathlib import Path
import unittest

from tests import test_rainpoint_safety as safety
from rainpointd.storage import SQLiteEventStore


class MultiValveTest(unittest.TestCase):
    setUp = safety.Htv145RuntimeTest.setUp
    enroll = safety.Htv145RuntimeTest.enroll

    def test_shared_gateway_keeps_counters_and_transactions_separate(self):
        self.enroll()
        other = replace(self.profile, controller_endpoint="c1c2d38f", node_id="rp-001122334466")
        self.coordinator.configure(other, observed_at="2026-09-05T12:02:00+00:00")
        self.store.synchronize_htv145_control_counter(valve_endpoint=other.storage_key,
            next_sequence=0x89, source="matching_immediate_response", observed_at="2026-09-05T12:02:00+00:00")
        self.assertEqual(2, len(self.runtime.profiles()))
        with self.assertRaisesRegex(ValueError, "complete association"):
            self.store.htv145_control_states(self.profile.valve_endpoint)
        self.runtime.request(self.profile, "open", duration_seconds=60, now="2026-09-05T12:02:01+00:00")
        self.assertEqual(0x89, self.store.htv145_control_states(other.storage_key)[0]["next_sequence"])
        self.assertEqual({}, self.store.htv145_transaction(other.storage_key))
        self.assertEqual("waiting_for_confirmation", self.store.htv145_transaction(self.profile.storage_key)["state"])
        self.store.delete_htv145_control(other.storage_key)
        self.assertIsNotNone(self.store.htv145_control_states(self.profile.storage_key)[0]["pending_command_id"])

    def test_schema24_upgrade_preserves_counter_pending_and_diagnostics(self):
        self.enroll()
        self.runtime.request(self.profile, "open", duration_seconds=60, now="2026-09-05T12:02:00+00:00")
        before = self.store.htv145_control_states()[0]
        transaction = self.store.htv145_transaction(self.profile.storage_key)
        # Recreate the exact legacy key shape in this disposable fixture only.
        with self.store._connection:
            for table in ("htv145_control_state", "htv145_counter_sync", "htv145_transaction", "htv145_qualification"):
                self.store._connection.execute(f"UPDATE {table} SET valve_endpoint=? WHERE valve_endpoint=?",
                    (self.profile.valve_endpoint, self.profile.storage_key))
            self.store._connection.execute("ALTER TABLE htv145_control_state DROP COLUMN rf_valve_endpoint")
            self.store._connection.execute("PRAGMA user_version=24")
        self.store.close()
        self.store = SQLiteEventStore(Path(self.temp.name) / "events.sqlite3")
        self.assertEqual(25, self.store.schema_version())
        self.assertEqual(before, self.store.htv145_control_states()[0])
        self.assertEqual(transaction, self.store.htv145_transaction(self.profile.storage_key))
