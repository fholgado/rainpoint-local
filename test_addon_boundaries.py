#!/usr/bin/env python3

from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).parent


class AddonBoundaryTest(unittest.TestCase):
    def test_installable_addon_excludes_research_controls(self) -> None:
        config = (ROOT / "rainpointd_addon" / "config.yaml").read_text()
        run_script = (ROOT / "rainpointd_addon" / "run.sh").read_text()
        for research_control in (
            "replay_interval",
            "research_capture_minutes",
            "--signal-capture-seconds",
        ):
            self.assertNotIn(research_control, config)
            self.assertNotIn(research_control, run_script)
        self.assertNotIn("|replay", config)
        self.assertIn("share:ro", config)
        self.assertNotIn("share:rw", config)


if __name__ == "__main__":
    unittest.main()
