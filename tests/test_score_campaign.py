from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from evaluator.score_campaign import collect


class CampaignCollectorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.run_dir = self.root / "run"
        (self.run_dir / "output").mkdir(parents=True)
        self.manifest = {
            "experiment_id": "EXP-COLLECT-TEST", "run_id": "RUN-001",
            "incident_id": "incident02", "status": "completed",
            "audit_counts": {"requests": 0, "allowed": 0, "denied": 0, "executed": 0},
        }
        (self.run_dir / "manifest.json").write_text(json.dumps(self.manifest), encoding="utf-8")
        assessment = {
            "schema_version": "1.0", "incident_id": "incident02",
            "classification": "benign", "incident_occurred": False,
            "severity": "none", "accounts": {"ops": "benign"},
            "hosts": {"app02": "benign"},
            "network_indicators": {
                "10.20.0.15": "benign", "198.51.100.80": "benign"
            },
            "attack_techniques": [],
        }
        (self.run_dir / "output" / "assessment.json").write_text(
            json.dumps(assessment), encoding="utf-8"
        )
        (self.run_dir / "output" / "policy_decisions.jsonl").write_text("", encoding="utf-8")
        (self.run_dir / "output" / "cyberdefender_actions.txt").write_text("", encoding="utf-8")
        self.campaign_path = self.root / "campaign.json"
        self.campaign_path.write_text(json.dumps({
            "schema_version": "1.0", "campaign_id": "EXP-COLLECT-TEST",
            "cells": [{
                "cell_id": "cell-1",
                "attempts": [{
                    "attempt": 1, "run_id": "RUN-001",
                    "run_directory": str(self.run_dir), "status": "completed"
                }, {
                    "attempt": 2, "run_id": "RUN-FAILED",
                    "run_directory": str(self.root / "missing"), "status": "failed"
                }]
            }]
        }), encoding="utf-8")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_collects_completed_attempts_and_reuses_unchanged_score(self) -> None:
        first = collect(self.campaign_path, self.root / "scores")
        self.assertEqual(1, first["completed_attempts_scored"])
        self.assertEqual("created", first["runs"][0]["disposition"])
        second = collect(self.campaign_path, self.root / "scores")
        self.assertEqual("reused", second["runs"][0]["disposition"])

    def test_refuses_stale_existing_score(self) -> None:
        collect(self.campaign_path, self.root / "scores")
        self.manifest["changed"] = True
        (self.run_dir / "manifest.json").write_text(json.dumps(self.manifest), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "scored run inputs changed"):
            collect(self.campaign_path, self.root / "scores")


if __name__ == "__main__":
    unittest.main()
