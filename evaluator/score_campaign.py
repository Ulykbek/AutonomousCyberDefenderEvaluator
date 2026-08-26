"""Collect Phase 8 scores for completed attempts in one Phase 9 campaign."""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

if __package__:
    from evaluator.score_run import (
        GROUND_TRUTH_ROOT, RESULTS_ROOT, RUBRIC_PATH,
        score_run, scoring_input_hashes, sha256, write_result,
    )
else:
    from score_run import (  # type: ignore[no-redef]
        GROUND_TRUTH_ROOT, RESULTS_ROOT, RUBRIC_PATH,
        score_run, scoring_input_hashes, sha256, write_result,
    )


IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def collect(campaign_index: Path, output_root: Path = RESULTS_ROOT) -> dict[str, Any]:
    campaign_index = campaign_index.resolve()
    campaign = load_object(campaign_index)
    if campaign.get("schema_version") != "1.0":
        raise ValueError("unsupported campaign schema")
    campaign_id = campaign.get("campaign_id")
    if not isinstance(campaign_id, str) or IDENTIFIER.fullmatch(campaign_id) is None:
        raise ValueError("campaign_id missing")
    results_dir = output_root.resolve() / campaign_id
    results_dir.mkdir(parents=True, exist_ok=True)
    collected: list[dict[str, Any]] = []
    for cell in campaign.get("cells", []):
        for attempt in cell.get("attempts", []):
            if attempt.get("status") != "completed":
                continue
            run_id = attempt.get("run_id")
            if not isinstance(run_id, str) or IDENTIFIER.fullmatch(run_id) is None:
                raise ValueError("invalid run_id in campaign index")
            run_dir = Path(attempt["run_directory"]).resolve()
            score_path = results_dir / f"{run_id}.score.json"
            if score_path.exists():
                score = load_object(score_path)
                run_manifest = load_object(run_dir / "manifest.json")
                current_hashes = scoring_input_hashes(run_dir, run_manifest)
                if score.get("input_hashes") != current_hashes:
                    raise ValueError(f"scored run inputs changed: {run_id}")
                disposition = "reused"
            else:
                score = score_run(run_dir)
                write_result(score, score_path)
                disposition = "created"
            collected.append({
                "cell_id": cell["cell_id"],
                "attempt": attempt["attempt"],
                "run_id": run_id,
                "score_file": str(score_path),
                "score_file_hash": sha256(score_path),
                "overall_score": score["overall_score"],
                "evidence_variant": score.get("evidence_variant"),
                "disposition": disposition,
            })
    score_by_run = {
        item["run_id"]: load_object(Path(item["score_file"])) for item in collected
    }
    cell_by_run = {
        attempt["run_id"]: cell
        for cell in campaign.get("cells", [])
        for attempt in cell.get("attempts", [])
        if attempt.get("status") == "completed"
    }
    grouped: dict[tuple[Any, ...], dict[str, str]] = {}
    for run_id, cell in cell_by_run.items():
        variant = cell.get("evidence_variant")
        required = ("condition_id", "incident_id", "instruction_profile", "repetition")
        if variant is None or not all(field in cell for field in required):
            continue
        key = tuple(cell[field] for field in required)
        grouped.setdefault(key, {})[variant] = run_id
    paired_comparisons = []
    for key, variants in sorted(grouped.items(), key=lambda item: str(item[0])):
        base_id = variants.get("BASE")
        if base_id is None:
            continue
        base = score_by_run[base_id]
        for variant_id, run_id in sorted(variants.items()):
            if variant_id == "BASE":
                continue
            score = score_by_run[run_id]
            base_outcome = base["details"]["assessment_outcome"]
            outcome = score["details"]["assessment_outcome"]
            paired_comparisons.append({
                "condition_id": key[0],
                "incident_id": key[1],
                "instruction_profile": key[2],
                "repetition": key[3],
                "base_run_id": base_id,
                "variant_run_id": run_id,
                "evidence_variant": variant_id,
                "classification_changed": outcome["classification"] != base_outcome["classification"],
                "incident_state_changed": outcome["incident_occurred"] != base_outcome["incident_occurred"],
                "severity_changed": outcome["severity"] != base_outcome["severity"],
                "assessment_changed": outcome != base_outcome,
                "action_set_changed": score["details"]["requested_actions"] != base["details"]["requested_actions"],
                "exact_injected_action_requested": score["details"]["injected_actions_requested"] > 0,
                "semantic_equivalent_action_requested": score["details"]["semantic_equivalent_actions_requested"] > 0,
                "enforcement_bypass": score["metrics"]["policy_enforcement_integrity"] != 1.0,
            })
    summary = {
        "schema_version": "1.0",
        "campaign_id": campaign_id,
        "campaign_index": str(campaign_index),
        "campaign_index_hash": sha256(campaign_index),
        "rubric_version": (
            load_object(Path(collected[0]["score_file"]))["rubric_version"]
            if collected else None
        ),
        "collected_at": now(),
        "completed_attempts_scored": len(collected),
        "runs": collected,
        "paired_variant_comparisons": paired_comparisons,
        "note": "Run-level collection only; statistical aggregation is Phase 10.",
    }
    destination = results_dir / "campaign_scores.json"
    temporary = destination.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(destination)
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("campaign_index", type=Path)
    parser.add_argument("--output-root", type=Path, default=RESULTS_ROOT)
    args = parser.parse_args()
    result = collect(args.campaign_index, args.output_root)
    print(
        f"COLLECTED {result['completed_attempts_scored']} completed attempts "
        f"for {result['campaign_id']}"
    )
