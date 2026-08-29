"""Evaluator-only three-round reproducibility analysis for the WP1 models."""

from __future__ import annotations

import csv
import json
import statistics
from datetime import datetime, timezone

from analysis.analyze_campaign import holm_adjust, paired_comparison
from analysis.compare_wp1_models import PLAN_PATH, RESULTS, mean_ci, rows_for, sha256


ANALYSIS_ID = "wp1-r001-r002-r003-replication-20260828-v1"
OUTPUT = RESULTS / "round_comparison" / ANALYSIS_ID
ROUNDS = ("R001", "R002", "R003")
MODELS = {
    "xAI Grok Build 0.1": {
        "R001": ["EXP-XAI-BUILD01-PILOT-002", "EXP-XAI-BUILD01-VARIANTS-REMAINING-001"],
        "R002": ["EXP-R002-XAI-GROK-BUILD01-FULL-001"],
        "R003": ["EXP-R003-XAI-GROK-BUILD01-FULL-001"],
    },
    "NVIDIA Nemotron 3 Super": {
        "R001": ["EXP-OPENROUTER-NVIDIA-NEMOTRON3-SUPER-INCIDENT01-VARIANTS-002", "EXP-OPENROUTER-NVIDIA-NEMOTRON3-SUPER-VARIANTS-REMAINING-001"],
        "R002": ["EXP-R002-OPENROUTER-NVIDIA-NEMOTRON3-SUPER-FULL-001"],
        "R003": ["EXP-R003-OPENROUTER-NVIDIA-NEMOTRON3-SUPER-FULL-001"],
    },
    "DeepSeek V4 Flash 0731": {
        "R001": ["EXP-OPENROUTER-DEEPSEEK-V4-FLASH-0731-INCIDENT01-VARIANTS-001", "EXP-OPENROUTER-DEEPSEEK-V4-FLASH-0731-VARIANTS-REMAINING-001"],
        "R002": ["EXP-R002-OPENROUTER-DEEPSEEK-V4-FLASH-0731-FULL-001"],
        "R003": ["EXP-R003-OPENROUTER-DEEPSEEK-V4-FLASH-0731-FULL-001"],
    },
}


def key(row):
    return row["incident_id"], row["profile"], row["variant"]


def correlation(left, right):
    ml, mr = statistics.fmean(left), statistics.fmean(right)
    numerator = sum((a - ml) * (b - mr) for a, b in zip(left, right))
    denominator = (sum((a - ml) ** 2 for a in left) * sum((b - mr) ** 2 for b in right)) ** 0.5
    return numerator / denominator if denominator else 0.0


def intraclass_reliability(round_vectors):
    """ICC(3,1): consistency of fixed rounds across matched cells."""
    n, k = len(round_vectors[0]), len(round_vectors)
    cell_means = [statistics.fmean(round_vectors[j][i] for j in range(k)) for i in range(n)]
    round_means = [statistics.fmean(vector) for vector in round_vectors]
    grand = statistics.fmean(cell_means)
    ss_cells = k * sum((value - grand) ** 2 for value in cell_means)
    ss_error = sum(
        (round_vectors[j][i] - cell_means[i] - round_means[j] + grand) ** 2
        for i in range(n) for j in range(k)
    )
    ms_cells = ss_cells / (n - 1)
    ms_error = ss_error / ((n - 1) * (k - 1))
    return (ms_cells - ms_error) / (ms_cells + (k - 1) * ms_error) if ms_cells + (k - 1) * ms_error else 0.0


def main():
    if OUTPUT.exists():
        raise FileExistsError(f"immutable output already exists: {OUTPUT}")
    plan = json.loads(PLAN_PATH.read_text(encoding="utf-8"))
    metrics = [plan["primary_metric"], *plan["secondary_metrics"]]
    loaded, provenance = {}, []
    for model, rounds in MODELS.items():
        for round_id, campaign_ids in rounds.items():
            rows, prov = rows_for(model, campaign_ids)
            if len(rows) != 192:
                raise ValueError(f"{model} {round_id} has {len(rows)} scored cells")
            mapping = {key(row): row for row in rows}
            if len(mapping) != 192:
                raise ValueError(f"duplicate cells for {model} {round_id}")
            loaded[model, round_id] = mapping
            provenance.extend({"model": model, "round": round_id, **item} for item in prov)
    expected = set(next(iter(loaded.values())))
    if any(set(mapping) != expected for mapping in loaded.values()):
        raise ValueError("round/model cell keys are not balanced")

    descriptive, comparisons, stability = [], [], []
    round_pairs = (("R001", "R002"), ("R001", "R003"), ("R002", "R003"))
    for model in MODELS:
        for round_id in ROUNDS:
            rows = list(loaded[model, round_id].values())
            for metric in metrics:
                values = [float(row[metric]) for row in rows if row.get(metric) is not None]
                record = {"model": model, "round": round_id, "metric": metric}
                record.update(mean_ci(values, plan, f"three-round:{model}:{round_id}:{metric}"))
                descriptive.append(record)
        for left, right in round_pairs:
            for metric in metrics:
                clusters = {}
                for round_id in (left, right):
                    clusters[round_id] = {}
                    mapping = loaded[model, round_id]
                    for incident in sorted({k[0] for k in mapping}):
                        values = [float(row[metric]) for k, row in mapping.items() if k[0] == incident and row.get(metric) is not None]
                        if values:
                            clusters[round_id][("cluster", incident, 1)] = statistics.fmean(values)
                record = {"model": model, "metric": metric, "reference_round": left, "comparison_round": right, "unit": "incident_cluster"}
                record.update(paired_comparison(clusters[left], clusters[right], plan, f"three-round:{model}:{left}:{right}:{metric}"))
                comparisons.append(record)
        vectors = {
            round_id: [float(loaded[model, round_id][cell]["overall_score"]) for cell in sorted(expected)]
            for round_id in ROUNDS
        }
        stability.append({
            "model": model,
            "matched_cells_per_round": 192,
            "overall_score_icc_3_1": intraclass_reliability([vectors[r] for r in ROUNDS]),
            "overall_score_correlations": {
                f"{a}_{b}": correlation(vectors[a], vectors[b]) for a, b in round_pairs
            },
            "rounds": {
                round_id: {
                    "overall_score": statistics.fmean(vectors[round_id]),
                    "actions_per_cell": statistics.fmean(float(row["requested_actions"]) for row in loaded[model, round_id].values()),
                    "exact_injection_cells": sum(row["injected_actions_requested"] > 0 for row in loaded[model, round_id].values() if row["variant"] != "BASE"),
                    "injection_cells": sum(row["variant"] != "BASE" for row in loaded[model, round_id].values()),
                    "policy_integrity_failures": sum(float(row["policy_enforcement_integrity"]) < 1.0 for row in loaded[model, round_id].values()),
                } for round_id in ROUNDS
            },
        })

    holm_adjust(comparisons)

    result = {
        "schema_version": "1.0", "analysis_id": ANALYSIS_ID,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "design": {"models": 3, "rounds": 3, "cells_per_model_round": 192, "total_scored_cells": 1728, "independent_clusters": 12},
        "provenance": provenance, "descriptive": descriptive,
        "paired_round_comparisons": comparisons, "stability": stability,
        "limitations": [
            "Only 12 incident clusters support population-level inference.",
            "Model identity is confounded with provider and adapter implementation.",
            "NVIDIA provider routing was not pinned and R003 used two OpenRouter accounts after quota exhaustion.",
            "Retries are operational provenance, not independent observations.",
            "Non-significance is not evidence of equivalence.",
        ],
    }
    OUTPUT.mkdir(parents=True)
    (OUTPUT / "three_round_replication.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    with (OUTPUT / "paired_round_comparisons.csv").open("w", newline="", encoding="utf-8") as handle:
        fields = list(comparisons[0])
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader(); writer.writerows(comparisons)
    lines = [
        "# WP1 three-round reproducibility analysis", "", f"Analysis ID: `{ANALYSIS_ID}`", "",
        "The balanced analysis contains 1,728 scored cells. Inference uses 12 paired incident clusters.", "",
        "## Overall score and stability", "",
        "| Model | R001 | R002 | R003 | ICC(3,1) | R001-R002 r | R001-R003 r | R002-R003 r | Injection failures R001/R002/R003 | Policy failures |", 
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for item in stability:
        rounds, corr = item["rounds"], item["overall_score_correlations"]
        injections = "/".join(str(rounds[r]["exact_injection_cells"]) for r in ROUNDS)
        policy = sum(rounds[r]["policy_integrity_failures"] for r in ROUNDS)
        lines.append(f"| {item['model']} | {rounds['R001']['overall_score']:.3f} | {rounds['R002']['overall_score']:.3f} | {rounds['R003']['overall_score']:.3f} | {item['overall_score_icc_3_1']:.3f} | {corr['R001_R002']:.3f} | {corr['R001_R003']:.3f} | {corr['R002_R003']:.3f} | {injections} | {policy} |")
    lines.extend(["", "## Interpretation constraints", ""] + [f"- {value}" for value in result["limitations"]])
    (OUTPUT / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"WROTE {OUTPUT}")


if __name__ == "__main__":
    main()
