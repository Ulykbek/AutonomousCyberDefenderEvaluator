"""Deterministic Phase 10 statistical analysis for one scored campaign."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import random
import re
import statistics
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


EVALUATOR_ROOT = Path(__file__).resolve().parent.parent
PLAN_PATH = Path(__file__).resolve().parent / "analysis_plan.json"
DEFAULT_RESULTS_ROOT = EVALUATOR_ROOT / "experiment_results"
IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def percentile(values: list[float], probability: float) -> float:
    ordered = sorted(values)
    if not ordered:
        raise ValueError("percentile requires observations")
    position = probability * (len(ordered) - 1)
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    fraction = position - lower
    return ordered[lower] * (1 - fraction) + ordered[upper] * fraction


def bootstrap_mean_ci(
    values: list[float], confidence: float, resamples: int, seed: str
) -> list[float]:
    if len(values) == 1:
        return [values[0], values[0]]
    generator = random.Random(seed)
    size = len(values)
    means = [
        statistics.fmean(values[generator.randrange(size)] for _ in range(size))
        for _ in range(resamples)
    ]
    tail = (1 - confidence) / 2
    return [percentile(means, tail), percentile(means, 1 - tail)]


def describe(values: list[float], plan: dict[str, Any], seed: str) -> dict[str, Any]:
    if not values:
        return {"n": 0, "mean": None, "sd": None, "median": None, "min": None,
                "max": None, "mean_ci": None}
    return {
        "n": len(values),
        "mean": statistics.fmean(values),
        "sd": statistics.stdev(values) if len(values) > 1 else None,
        "median": statistics.median(values),
        "min": min(values),
        "max": max(values),
        "mean_ci": bootstrap_mean_ci(
            values, plan["confidence_level"], plan["bootstrap_resamples"], seed
        ),
    }


def permutation_pvalue(differences: list[float], plan: dict[str, Any], seed: str) -> tuple[float, str]:
    observed = abs(statistics.fmean(differences))
    size = len(differences)
    if size <= plan["exact_permutation_max_pairs"]:
        extreme = 0
        total = 1 << size
        for mask in range(total):
            value = statistics.fmean(
                difference if mask & (1 << index) else -difference
                for index, difference in enumerate(differences)
            )
            extreme += abs(value) >= observed - 1e-15
        return extreme / total, "exact_sign_flip"
    generator = random.Random(seed)
    resamples = plan["permutation_resamples"]
    extreme = 0
    for _ in range(resamples):
        value = statistics.fmean(
            difference if generator.getrandbits(1) else -difference
            for difference in differences
        )
        extreme += abs(value) >= observed - 1e-15
    return (extreme + 1) / (resamples + 1), "monte_carlo_sign_flip"


def paired_comparison(
    reference: dict[tuple[str, str, int], float],
    comparison: dict[tuple[str, str, int], float],
    plan: dict[str, Any],
    seed: str,
) -> dict[str, Any]:
    keys = sorted(set(reference) & set(comparison))
    differences = [comparison[key] - reference[key] for key in keys]
    if not differences:
        return {"n_pairs": 0, "mean_difference": None, "difference_ci": None,
                "paired_effect_dz": None, "p_value": None, "test": None}
    sd = statistics.stdev(differences) if len(differences) > 1 else None
    mean = statistics.fmean(differences)
    p_value, test = permutation_pvalue(differences, plan, seed)
    return {
        "n_pairs": len(differences),
        "mean_difference": mean,
        "difference_ci": bootstrap_mean_ci(
            differences, plan["confidence_level"], plan["bootstrap_resamples"], seed + ":ci"
        ),
        "paired_effect_dz": (
            mean / sd if sd is not None and not math.isclose(sd, 0.0, abs_tol=1e-15)
            else None
        ),
        "p_value": p_value,
        "test": test,
    }


def holm_adjust(records: list[dict[str, Any]]) -> None:
    eligible = [record for record in records if record["p_value"] is not None]
    ordered = sorted(eligible, key=lambda item: item["p_value"])
    running = 0.0
    total = len(ordered)
    for index, record in enumerate(ordered):
        running = max(running, min(1.0, record["p_value"] * (total - index)))
        record["p_value_holm"] = running
    for record in records:
        record.setdefault("p_value_holm", None)


def write_csv(path: Path, rows: Iterable[dict[str, Any]], fields: list[str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def analyze(
    campaign_scores_path: Path,
    output_root: Path,
    analysis_id: str,
    reference_profile: str | None = None,
) -> dict[str, Any]:
    if IDENTIFIER.fullmatch(analysis_id) is None:
        raise ValueError("invalid analysis_id")
    campaign_scores_path = campaign_scores_path.resolve()
    campaign_scores = load_object(campaign_scores_path)
    plan = load_object(PLAN_PATH)
    campaign_index_path = Path(campaign_scores["campaign_index"]).resolve()
    if sha256(campaign_index_path) != campaign_scores["campaign_index_hash"]:
        raise ValueError("campaign index changed after score collection")
    campaign = load_object(campaign_index_path)
    campaign_id = campaign.get("campaign_id")
    if not isinstance(campaign_id, str) or IDENTIFIER.fullmatch(campaign_id) is None:
        raise ValueError("invalid campaign_id")
    if campaign_scores.get("campaign_id") not in {None, campaign_id}:
        raise ValueError("campaign identifier mismatch")
    reference_profile = reference_profile or plan["default_reference_profile"]
    cell_by_run: dict[str, dict[str, Any]] = {}
    for cell in campaign["cells"]:
        for attempt in cell["attempts"]:
            cell_by_run[attempt["run_id"]] = cell | {"attempt": attempt["attempt"]}

    metric_names = [plan["primary_metric"], *plan["secondary_metrics"]]
    rows: list[dict[str, Any]] = []
    for collected in campaign_scores["runs"]:
        score_path = Path(collected["score_file"]).resolve()
        if sha256(score_path) != collected.get("score_file_hash"):
            raise ValueError(f"run score changed after collection: {collected['run_id']}")
        score = load_object(score_path)
        run_id = collected["run_id"]
        if run_id not in cell_by_run:
            raise ValueError(f"score has no campaign cell: {run_id}")
        if score.get("run_id") != run_id or score.get("overall_score") != collected["overall_score"]:
            raise ValueError(f"campaign score index mismatch: {run_id}")
        cell = cell_by_run[run_id]
        row: dict[str, Any] = {
            "campaign_id": campaign["campaign_id"], "cell_id": cell["cell_id"],
            "run_id": run_id, "condition_id": cell["condition_id"],
            "incident_id": cell["incident_id"],
            "instruction_profile": cell["instruction_profile"],
            "evidence_variant": cell.get("evidence_variant", "BASE"),
            "repetition": cell["repetition"], "attempt": cell["attempt"],
            "overall_score": score["overall_score"],
        }
        row.update(score["metrics"])
        rows.append(row)
    if not rows:
        raise ValueError("campaign contains no scored completed runs")
    profiles = sorted({row["instruction_profile"] for row in rows})
    if reference_profile not in profiles:
        raise ValueError(f"reference profile absent: {reference_profile}")

    descriptive: list[dict[str, Any]] = []
    for (condition, profile, variant), group in sorted(_groups(rows).items()):
        for metric in metric_names:
            values = [float(row[metric]) for row in group if row.get(metric) is not None]
            record = {"condition_id": condition, "instruction_profile": profile,
                      "evidence_variant": variant,
                      "metric": metric}
            record.update(describe(values, plan, f"{plan['random_seed']}:{condition}:{profile}:{metric}"))
            descriptive.append(record)

    comparisons: list[dict[str, Any]] = []
    conditions = sorted({row["condition_id"] for row in rows})
    variants = sorted({row["evidence_variant"] for row in rows})
    for metric in metric_names:
        metric_family: list[dict[str, Any]] = []
        for condition in conditions:
            for variant in variants:
                reference = _paired_values(rows, condition, reference_profile, variant, metric)
                for profile in profiles:
                    if profile == reference_profile:
                        continue
                    comparison = _paired_values(rows, condition, profile, variant, metric)
                    record = {
                        "condition_id": condition, "evidence_variant": variant,
                        "metric": metric, "reference_profile": reference_profile,
                        "comparison_profile": profile,
                    }
                    record.update(paired_comparison(
                        reference, comparison, plan,
                        f"{plan['random_seed']}:{condition}:{variant}:{metric}:{profile}",
                    ))
                    metric_family.append(record)
        holm_adjust(metric_family)
        comparisons.extend(metric_family)

    output_dir = output_root.resolve() / campaign["campaign_id"] / analysis_id
    output_dir.mkdir(parents=True, exist_ok=False)
    result = {
        "schema_version": "1.0", "analysis_version": plan["analysis_version"],
        "analysis_id": analysis_id, "campaign_id": campaign["campaign_id"],
        "created_at": now(), "reference_profile": reference_profile,
        "input_hashes": {
            "campaign_scores": sha256(campaign_scores_path),
            "campaign_index": sha256(campaign_index_path),
            "analysis_plan": sha256(PLAN_PATH),
        },
        "run_count": len(rows),
        "data_quality": _data_quality(campaign, len(rows)),
        "descriptive": descriptive,
        "paired_comparisons": comparisons,
        "limitations": [
            "Complete-pair analysis without imputation.",
            "Permutation tests assess paired mean differences, not equivalence.",
            "Narrative manual-review fields are not included in numeric outcomes.",
        ],
    }
    (output_dir / "analysis.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    write_csv(output_dir / "run_metrics.csv", rows, [
        "campaign_id", "cell_id", "run_id", "condition_id", "incident_id",
        "instruction_profile", "evidence_variant", "repetition", "attempt", *metric_names,
    ])
    write_csv(output_dir / "profile_summary.csv", descriptive, [
        "condition_id", "instruction_profile", "evidence_variant", "metric", "n", "mean", "sd",
        "median", "min", "max", "mean_ci",
    ])
    write_csv(output_dir / "paired_comparisons.csv", comparisons, [
        "condition_id", "evidence_variant", "metric", "reference_profile", "comparison_profile",
        "n_pairs", "mean_difference", "difference_ci", "paired_effect_dz",
        "p_value", "p_value_holm", "test",
    ])
    (output_dir / "report.md").write_text(
        render_report(result, plan), encoding="utf-8"
    )
    result["output_directory"] = str(output_dir)
    return result


def _groups(rows: list[dict[str, Any]]) -> dict[tuple[str, str, str], list[dict[str, Any]]]:
    groups: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[(row["condition_id"], row["instruction_profile"], row["evidence_variant"])].append(row)
    return groups


def _paired_values(
    rows: list[dict[str, Any]], condition: str, profile: str,
    evidence_variant: str, metric: str,
) -> dict[tuple[str, str, int], float]:
    values: dict[tuple[str, str, int], float] = {}
    for row in rows:
        if (
            row["condition_id"] != condition
            or row["instruction_profile"] != profile
            or row["evidence_variant"] != evidence_variant
            or row.get(metric) is None
        ):
            continue
        key = (row["condition_id"], row["incident_id"], row["repetition"])
        if key in values:
            raise ValueError(f"duplicate paired observation: {condition}/{profile}/{key}")
        values[key] = float(row[metric])
    return values


def _data_quality(campaign: dict[str, Any], scored_runs: int) -> dict[str, Any]:
    statuses: dict[str, int] = defaultdict(int)
    retry_attempts = 0
    total_attempts = 0
    for cell in campaign["cells"]:
        attempts = cell["attempts"]
        total_attempts += len(attempts)
        retry_attempts += max(0, len(attempts) - 1)
        for attempt in attempts:
            statuses[str(attempt.get("status", "unknown"))] += 1
    return {
        "total_cells": len(campaign["cells"]),
        "total_attempts": total_attempts,
        "retry_attempts": retry_attempts,
        "attempt_status_counts": dict(sorted(statuses.items())),
        "scored_runs": scored_runs,
        "completed_but_unscored": max(0, statuses.get("completed", 0) - scored_runs),
    }


def render_report(result: dict[str, Any], plan: dict[str, Any]) -> str:
    primary = plan["primary_metric"]
    summaries = [item for item in result["descriptive"] if item["metric"] == primary]
    comparisons = [item for item in result["paired_comparisons"] if item["metric"] == primary]
    lines = [
        f"# Campaign analysis: {result['campaign_id']}", "",
        f"Analysis ID: `{result['analysis_id']}`  ",
        f"Analysis version: `{result['analysis_version']}`  ",
        f"Scored runs: {result['run_count']}  ",
        f"Reference profile: `{result['reference_profile']}`", "",
        "## Data quality", "",
        f"- Campaign cells: {result['data_quality']['total_cells']}",
        f"- Physical attempts: {result['data_quality']['total_attempts']}",
        f"- Retry attempts: {result['data_quality']['retry_attempts']}",
        f"- Completed but unscored: {result['data_quality']['completed_but_unscored']}", "",
        "## Primary outcome: overall score", "",
        "| Condition | Profile | n | Mean | 95% bootstrap CI | SD |", "|---|---:|---:|---:|---:|---:|",
    ]
    for item in summaries:
        interval = item["mean_ci"]
        ci = "NA" if interval is None else f"{interval[0]:.4f} to {interval[1]:.4f}"
        sd = "NA" if item["sd"] is None else f"{item['sd']:.4f}"
        mean = "NA" if item["mean"] is None else f"{item['mean']:.4f}"
        lines.append(
            f"| {item['condition_id']} | {item['instruction_profile']} | {item['n']} | {mean} | {ci} | {sd} |"
        )
    lines.extend(["", "## Paired profile comparisons", "",
                  "Differences are comparison minus reference.", "",
                  "| Condition | Comparison | Pairs | Mean difference | 95% bootstrap CI | Holm-adjusted p | Paired dz |",
                  "|---|---:|---:|---:|---:|---:|---:|"])
    for item in comparisons:
        interval = item["difference_ci"]
        ci = "NA" if interval is None else f"{interval[0]:.4f} to {interval[1]:.4f}"
        effect = "NA" if item["paired_effect_dz"] is None else f"{item['paired_effect_dz']:.4f}"
        adjusted = "NA" if item["p_value_holm"] is None else f"{item['p_value_holm']:.6f}"
        difference = "NA" if item["mean_difference"] is None else f"{item['mean_difference']:.4f}"
        lines.append(
            f"| {item['condition_id']} | {item['comparison_profile']} | {item['n_pairs']} | "
            f"{difference} | {ci} | {adjusted} | {effect} |"
        )
    lines.extend(["", "## Interpretation constraints", ""])
    lines.extend(f"- {value}" for value in result["limitations"])
    lines.extend(["", "Secondary outcomes are available in `profile_summary.csv` and "
                  "`paired_comparisons.csv`.", ""])
    return "\n".join(lines)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("campaign_scores", type=Path)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_RESULTS_ROOT)
    parser.add_argument("--analysis-id", required=True)
    parser.add_argument("--reference-profile")
    args = parser.parse_args()
    result = analyze(
        args.campaign_scores, args.output_root, args.analysis_id, args.reference_profile
    )
    print(f"ANALYZED {result['run_count']} runs -> {result['output_directory']}")
