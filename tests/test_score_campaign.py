from __future__ import annotations

import json
import shutil
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

    def test_builds_paired_variant_comparison_against_base(self) -> None:
        self.manifest["evidence_variant"] = "BASE"
        (self.run_dir / "manifest.json").write_text(json.dumps(self.manifest), encoding="utf-8")
        variant_dir = self.root / "variant"
        shutil.copytree(self.run_dir, variant_dir)
        variant_manifest = dict(self.manifest)
        variant_manifest.update({"run_id": "RUN-002", "evidence_variant": "c91f7a2e"})
        (variant_dir / "manifest.json").write_text(json.dumps(variant_manifest), encoding="utf-8")
        assessment_path = variant_dir / "output" / "assessment.json"
        variant_assessment = json.loads(assessment_path.read_text(encoding="utf-8"))
        variant_assessment.update({
            "classification": "ambiguous", "incident_occurred": None,
            "severity": "undetermined",
        })
        assessment_path.write_text(json.dumps(variant_assessment), encoding="utf-8")
        campaign = json.loads(self.campaign_path.read_text(encoding="utf-8"))
        campaign["cells"][0].update({
            "condition_id": "broker", "incident_id": "incident02",
            "instruction_profile": "neutral", "repetition": 1,
            "evidence_variant": "BASE",
        })
        campaign["cells"].append({
            "cell_id": "cell-2", "condition_id": "broker",
            "incident_id": "incident02", "instruction_profile": "neutral",
            "repetition": 1, "evidence_variant": "c91f7a2e",
            "attempts": [{"attempt": 1, "run_id": "RUN-002",
                "run_directory": str(variant_dir), "status": "completed"}],
        })
        self.campaign_path.write_text(json.dumps(campaign), encoding="utf-8")
        result = collect(self.campaign_path, self.root / "variant-scores")
        self.assertEqual(2, result["completed_attempts_scored"])
        comparison = result["paired_variant_comparisons"][0]
        self.assertTrue(comparison["classification_changed"])
        self.assertTrue(comparison["assessment_changed"])
        self.assertFalse(comparison["enforcement_bypass"])


if __name__ == "__main__":
    unittest.main()
