from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from analysis.analyze_campaign import analyze, holm_adjust, sha256


METRICS = [
    "classification", "incident_occurred", "severity", "accounts_f1",
    "hosts_f1", "network_indicators_f1", "attack_techniques_f1",
    "action_selection_f1", "injection_resistance",
    "policy_enforcement_integrity",
]


class CampaignAnalysisTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.scores_dir = self.root / "scores"
        self.scores_dir.mkdir()
        cells = []
        collected = []
        for profile, values in (("neutral", (0.5, 0.6)), ("security-aware", (0.7, 0.8))):
            for repetition, value in enumerate(values, start=1):
                run_id = f"RUN-{profile}-{repetition}"
                score_path = self.scores_dir / f"{run_id}.json"
                score_path.write_text(json.dumps({
                    "run_id": run_id, "overall_score": value,
                    "metrics": {metric: value for metric in METRICS},
                }), encoding="utf-8")
                collected.append({
                    "run_id": run_id, "score_file": str(score_path),
                    "score_file_hash": sha256(score_path), "overall_score": value,
                })
                cells.append({
                    "cell_id": f"CELL-{profile}-{repetition}",
                    "condition_id": "broker", "incident_id": "incident01",
                    "instruction_profile": profile, "repetition": repetition,
                    "attempts": [{"attempt": 1, "run_id": run_id, "status": "completed"}],
                })
        self.campaign_path = self.root / "campaign.json"
        self.campaign_path.write_text(json.dumps({
            "campaign_id": "EXP-ANALYSIS-TEST", "cells": cells,
        }), encoding="utf-8")
        self.campaign_scores_path = self.root / "campaign_scores.json"
        self.campaign_scores_path.write_text(json.dumps({
            "campaign_index": str(self.campaign_path),
            "campaign_index_hash": sha256(self.campaign_path),
            "runs": collected,
        }), encoding="utf-8")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_analysis_produces_paired_estimate_and_all_outputs(self) -> None:
        result = analyze(self.campaign_scores_path, self.root / "results", "analysis-v1")
        self.assertEqual(4, result["run_count"])
        primary = next(
            item for item in result["paired_comparisons"]
            if item["metric"] == "overall_score"
        )
        self.assertEqual(2, primary["n_pairs"])
        self.assertAlmostEqual(0.2, primary["mean_difference"])
        self.assertEqual("exact_sign_flip", primary["test"])
        self.assertAlmostEqual(0.5, primary["p_value"])
        output = Path(result["output_directory"])
        for name in (
            "analysis.json", "run_metrics.csv", "profile_summary.csv",
            "paired_comparisons.csv", "report.md",
        ):
            self.assertTrue((output / name).is_file(), name)

    def test_existing_analysis_is_not_overwritten(self) -> None:
        self.analyze_once()
        with self.assertRaises(FileExistsError):
            analyze(self.campaign_scores_path, self.root / "results", "analysis-v1")

    def analyze_once(self):
        return analyze(self.campaign_scores_path, self.root / "results", "analysis-v1")

    def test_changed_score_is_rejected(self) -> None:
        first = json.loads(self.campaign_scores_path.read_text(encoding="utf-8"))["runs"][0]
        Path(first["score_file"]).write_text("{}", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "score changed after collection"):
            analyze(self.campaign_scores_path, self.root / "results", "analysis-v1")

    def test_holm_adjustment_is_monotone_and_bounded(self) -> None:
        records = [{"p_value": 0.01}, {"p_value": 0.04}, {"p_value": 0.03}]
        holm_adjust(records)
        adjusted = [record["p_value_holm"] for record in sorted(records, key=lambda x: x["p_value"])]
        self.assertEqual(sorted(adjusted), adjusted)
        self.assertTrue(all(0 <= value <= 1 for value in adjusted))


if __name__ == "__main__":
    unittest.main()
