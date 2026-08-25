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
        score_run, sha256, write_result,
    )
else:
    from score_run import (  # type: ignore[no-redef]
        GROUND_TRUTH_ROOT, RESULTS_ROOT, RUBRIC_PATH,
        score_run, sha256, write_result,
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
                incident_id = run_manifest.get("incident_id")
                current_hashes = {
                    "run_manifest": sha256(run_dir / "manifest.json"),
                    "assessment": sha256(run_dir / "output" / "assessment.json"),
                    "ground_truth": sha256(GROUND_TRUTH_ROOT / f"{incident_id}.json"),
                    "scoring_rubric": sha256(RUBRIC_PATH),
                }
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
                "disposition": disposition,
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
