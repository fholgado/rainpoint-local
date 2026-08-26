#!/usr/bin/env python3

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

MODULE = (
    Path(__file__).parent
    / "custom_components"
    / "rainpoint_local"
    / "api_models.py"
)
spec = importlib.util.spec_from_file_location("rainpoint_api_models", MODULE)
assert spec and spec.loader
api_models = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = api_models
spec.loader.exec_module(api_models)


class APIModelsTest(unittest.TestCase):
    def test_gateway_metadata_parses_capability_contract(self) -> None:
        metadata = api_models.GatewayMetadata.from_payload(
            {
                "api_version": "v1",
                "gateway_id": "rainpoint-local",
                "capabilities": ["event_long_poll"],
                "latest_event_id": 42,
            }
        )
        self.assertEqual("rainpoint-local", metadata.gateway_id)
        self.assertEqual(frozenset({"event_long_poll"}), metadata.capabilities)
        self.assertEqual(42, metadata.latest_event_id)

    def test_collection_rejects_missing_stable_identity(self) -> None:
        with self.assertRaises(api_models.APIModelError):
            api_models.validate_object_list(
                {"devices": [{"name": "missing ID"}]},
                "devices",
                "device_id",
            )

    def test_pairing_completion_accepts_existing_sensor_recovery(self) -> None:
        self.assertEqual(
            "c4e50024",
            api_models.pairing_completed_endpoint(
                {
                    "completed_endpoint": "C4E50024",
                    "completed_existing_record": True,
                    "new_records": [],
                }
            ),
        )

    def test_pairing_completion_wins_over_optional_node_tail_timeout(self) -> None:
        """A later node-tail diagnostic cannot reverse terminal RF evidence."""
        self.assertEqual(
            "94a98013",
            api_models.pairing_completed_endpoint(
                {
                    "stage": "valve_pairing_completed",
                    "completed_endpoint": "94a98013",
                    "pairing_nodes": [
                        {
                            "pairing_state": "completed",
                            "pairing_outcome": "completed",
                            "pairing_node_state": "failed",
                            "pairing_node_failure_reason": "session_timeout",
                            "pairing_tail_state": "optional_tail_timeout",
                        }
                    ],
                }
            ),
        )

    def test_pairing_completion_falls_back_to_new_record(self) -> None:
        self.assertEqual(
            "95a98024",
            api_models.pairing_completed_endpoint(
                {"new_records": [{"paired_endpoint": "95a98024"}]}
            ),
        )

    def test_pairing_completion_rejects_invalid_endpoint(self) -> None:
        with self.assertRaises(api_models.APIModelError):
            api_models.pairing_completed_endpoint(
                {"completed_endpoint": "not-an-endpoint"}
            )

    def test_pairing_progress_actions_follow_radio_exchange(self) -> None:
        self.assertEqual(
            "wait_for_device",
            api_models.pairing_progress_action(
                {"stage": "waiting_for_factory_announcement"}
            ),
        )
        self.assertEqual(
            "exchange_with_device",
            api_models.pairing_progress_action(
                {"stage": "pairing_exchange_in_progress"}
            ),
        )
        self.assertEqual(
            "confirm_device",
            api_models.pairing_progress_action(
                {"stage": "waiting_for_terminal_confirmation"}
            ),
        )

    def test_pairing_catalog_parses_categories_and_support_boundaries(self) -> None:
        profiles = api_models.pairing_profiles(
            {
                "supported_profiles": [
                    {
                        "profile_id": "hcs026_auto_v1",
                        "model": "HCS02xRF",
                        "device_category": "sensor",
                        "display_name": "HCS02x soil moisture sensor",
                        "required_node_capability": "sensor_pairing_tx",
                        "automatic_discovery": True,
                        "user_pairing_supported": True,
                    },
                    {
                        "profile_id": "htv405_auto_candidate_v1",
                        "model": "HTV405FRF",
                        "device_category": "valve",
                        "display_name": "HTV405 4-zone water timer",
                        "required_node_capability": (
                            "htv405_auto_identity_pairing"
                        ),
                        "automatic_discovery": True,
                        "user_pairing_supported": True,
                    },
                    {
                        "profile_id": "htv145_auto_candidate_v1",
                        "model": "HTV145FRF",
                        "device_category": "valve",
                        "display_name": "HTV145 single-zone water timer",
                        "required_node_capability": (
                            "htv145_pairing_tx_candidate"
                        ),
                        "automatic_discovery": False,
                        "user_pairing_supported": False,
                    },
                ]
            }
        )
        self.assertEqual(
            ("sensor", "valve", "valve"),
            tuple(profile.device_category for profile in profiles),
        )
        self.assertTrue(profiles[1].automatic_discovery)
        self.assertFalse(profiles[2].user_pairing_supported)

    def test_pairing_catalog_rejects_invalid_or_duplicate_profiles(self) -> None:
        profile = {
            "profile_id": "duplicate",
            "model": "HCS02xRF",
            "device_category": "sensor",
            "display_name": "Soil sensor",
            "required_node_capability": "sensor_pairing_tx",
            "automatic_discovery": True,
            "user_pairing_supported": True,
        }
        with self.assertRaises(api_models.APIModelError):
            api_models.pairing_profiles(
                {"supported_profiles": [profile, profile.copy()]}
            )
        with self.assertRaises(api_models.APIModelError):
            api_models.pairing_profiles(
                {
                    "supported_profiles": [
                        {**profile, "device_category": "controller"}
                    ]
                }
            )
        with self.assertRaises(api_models.APIModelError):
            api_models.pairing_profiles(
                {
                    "supported_profiles": [
                        {**profile, "automatic_discovery": "yes"}
                    ]
                }
            )


if __name__ == "__main__":
    unittest.main()
