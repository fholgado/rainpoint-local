#!/usr/bin/env python3

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT / "rainpointd_addon"))

from rainpointd.network import NetworkTransport


class NetworkTransportTest(unittest.TestCase):
    def test_lifecycle_is_intentionally_empty(self) -> None:
        transport = NetworkTransport()
        self.assertIsNone(transport.seed())
        self.assertIsNone(transport.start())
        self.assertIsNone(transport.stop())


if __name__ == "__main__":
    unittest.main()
