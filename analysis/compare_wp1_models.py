"""Reproducible cross-model WP1 comparison using evaluator-only scores."""

from __future__ import annotations

import csv
import hashlib
import json
import math
import statistics
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from analysis.analyze_campaign import (
    bootstrap_mean_ci,
    holm_adjust,
    paired_comparison,
)


ROOT = Path(__file__).resolve().parent.parent
if not (ROOT / "analysis" / "analysis_plan.json").exists():
    ROOT = Path.cwd()
PLAN_PATH = ROOT / "analysis" / "analysis_plan.json"
RESULTS = ROOT / "experiment_results"
ANALYSIS_ID = "wp1-xai-nvidia-deepseek-20260827-v1"
OUTPUT = RESULTS / "model_comparison" / ANALYSIS_ID

CAMPAIGNS = {
    "xAI Grok Build 0.1": [
        "EXP-XAI-BUILD01-PILOT-002",
        "EXP-XAI-BUILD01-VARIANTS-REMAINING-001",
    ],
    "NVIDIA Nemotron 3 Super": [
        "EXP-OPENROUTER-NVIDIA-NEMOTRON3-SUPER-INCIDENT01-VARIANTS-002",
        "EXP-OPENROUTER-NVIDIA-NEMOTRON3-SUPER-VARIANTS-REMAINING-001",
    ],
    "DeepSeek V4 Flash 0731": [
        "EXP-OPENROUTER-DEEPSEEK-V4-FLASH-0731-INCIDENT01-VARIANTS-001",
        "EXP-OPENROUTER-DEEPSEEK-V4-FLASH-0731-VARIANTS-REMAINING-001",
    ],
}


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rows_for(model: str, campaign_ids: list[str]):
    rows = []
    provenance = []
    for campaign_id in campaign_ids:
        index_path = RESULTS / campaign_id / "campaign_scores.json"
        index = load(index_path)
        campaign_path = Path(index["campaign_index"])
        campaign = load(campaign_path)
        cell_by_run = {
            attempt["run_id"]: cell | {"attempt": attempt["attempt"]}
            for cell in campaign["cells"]
            for attempt in cell["attempts"]
        }
        for item in index["runs"]:
            score_path = Path(item["score_file"])
            if sha256(score_path) != item["score_file_hash"]:
                raise ValueError(f"changed score: {score_path}")
            score = load(score_path)
            cell = cell_by_run[item["run_id"]]
            rows.append({
                "model": model,
                "campaign_id": campaign_id,
                "incident_id": cell["incident_id"],
                "profile": cell["instruction_profile"],
                "variant": cell.get("evidence_variant", "BASE"),
                "attempt": cell["attempt"],
                "overall_score": score["overall_score"],
                **score["metrics"],
                "requested_actions": score["details"]["requested_action_count"],
                "allowed": score["details"]["audit_counts"]["allowed"],
                "denied": score["details"]["audit_counts"]["denied"],
                "executed": score["details"]["audit_counts"]["executed"],
                "injected_actions_requested": score["details"]["injected_actions_requested"],
                "semantic_equivalent_actions_requested": score["details"]["semantic_equivalent_actions_requested"],
            })
        attempts = [a for c in campaign["cells"] for a in c["attempts"]]
        provenance.append({
            "campaign_id": campaign_id,
            "campaign_scores_hash": sha256(index_path),
            "campaign_index_hash": sha256(campaign_path),
            "cells": len(campaign["cells"]),
            "attempts": len(attempts),
            "failed_attempts": sum(a["status"] != "completed" for a in attempts),
            "retry_attempts": sum(max(0, len(c["attempts"]) - 1) for c in campaign["cells"]),
        })
    return rows, provenance


def mean_ci(values, plan, seed):
    values = [float(x) for x in values]
    return {
        "n": len(values),
        "mean": statistics.fmean(values),
        "sd": statistics.stdev(values) if len(values) > 1 else None,
        "ci": bootstrap_mean_ci(values, plan["confidence_level"], plan["bootstrap_resamples"], seed),
    }


def fmt(value, digits=3):
    return "NA" if value is None else f"{value:.{digits}f}"


def pct(n, d):
    return 100 * n / d if d else None


def main():
    if OUTPUT.exists():
        raise FileExistsError(f"immutable output already exists: {OUTPUT}")
    plan = load(PLAN_PATH)
    all_rows = []
    provenance = []
    for model, ids in CAMPAIGNS.items():
        rows, prov = rows_for(model, ids)
        all_rows.extend(rows)
        provenance.extend(prov)
    metrics = [plan["primary_metric"], *plan["secondary_metrics"]]

    incident01 = [r for r in all_rows if r["incident_id"] == "incident01"]
    pilot_descriptive = []
    for model in CAMPAIGNS:
        group = [r for r in incident01 if r["model"] == model]
        for metric in metrics:
            values = [r[metric] for r in group if r.get(metric) is not None]
            rec = {"model": model, "metric": metric}
            rec.update(mean_ci(values, plan, f"pilot:{model}:{metric}"))
            pilot_descriptive.append(rec)

    pilot_pairs = []
    models = list(CAMPAIGNS)
    for metric in metrics:
        family = []
        for i, reference_model in enumerate(models):
            for comparison_model in models[i + 1:]:
                ref = {
                    (r["profile"], r["variant"], 1): float(r[metric])
                    for r in incident01 if r["model"] == reference_model and r.get(metric) is not None
                }
                cmp = {
                    (r["profile"], r["variant"], 1): float(r[metric])
                    for r in incident01 if r["model"] == comparison_model and r.get(metric) is not None
                }
                rec = {"metric": metric, "reference_model": reference_model,
                       "comparison_model": comparison_model}
                rec.update(paired_comparison(ref, cmp, plan, f"pilot:{metric}:{reference_model}:{comparison_model}"))
                family.append(rec)
        holm_adjust(family)
        pilot_pairs.extend(family)

    full_models = list(CAMPAIGNS)
    full_rows = [r for r in all_rows if r["model"] in full_models]
    full_descriptive = []
    for model in full_models:
        group = [r for r in full_rows if r["model"] == model]
        for metric in metrics:
            values = [r[metric] for r in group if r.get(metric) is not None]
            rec = {"model": model, "metric": metric}
            rec.update(mean_ci(values, plan, f"full:{model}:{metric}"))
            full_descriptive.append(rec)

    full_comparisons = []
    for metric in metrics:
        cluster_means = defaultdict(dict)
        for model in full_models:
            for incident in sorted({r["incident_id"] for r in full_rows}):
                values = [float(r[metric]) for r in full_rows
                          if r["model"] == model and r["incident_id"] == incident
                          and r.get(metric) is not None]
                if values:
                    cluster_means[model][("cluster", incident, 1)] = statistics.fmean(values)
        for i, reference_model in enumerate(full_models):
            for comparison_model in full_models[i + 1:]:
                rec = {"metric": metric, "reference_model": reference_model,
                       "comparison_model": comparison_model,
                       "unit": "incident_cluster"}
                rec.update(paired_comparison(
                    cluster_means[reference_model], cluster_means[comparison_model],
                    plan, f"full:{metric}:{reference_model}:{comparison_model}",
                ))
                full_comparisons.append(rec)
    # Treat the three primary pairwise model comparisons as one family and all
    # secondary metric-by-model comparisons as a second exploratory family.
    primary = [r for r in full_comparisons if r["metric"] == plan["primary_metric"]]
    secondary = [r for r in full_comparisons if r["metric"] != plan["primary_metric"]]
    holm_adjust(secondary)
    holm_adjust(primary)

    behavior = []
    for model in models:
        group = [r for r in all_rows if r["model"] == model]
        attacked = [r for r in group if r["variant"] != "BASE"]
        behavior.append({
            "model": model,
            "scope": "all_12_incidents",
            "cells": len(group),
            "attacked_cells": len(attacked),
            "requested_actions": sum(r["requested_actions"] for r in group),
            "actions_per_cell": sum(r["requested_actions"] for r in group) / len(group),
            "denied": sum(r["denied"] for r in group),
            "denial_rate": (
                sum(r["denied"] for r in group) /
                max(1, sum(r["requested_actions"] for r in group))
            ),
            "exact_injection_cells": sum(r["injected_actions_requested"] > 0 for r in attacked),
            "semantic_injection_cells": sum(r["semantic_equivalent_actions_requested"] > 0 for r in attacked),
            "injection_resistance_failures": sum(r.get("injection_resistance") == 0 for r in attacked),
            "exact_injection_rate": (
                sum(r["injected_actions_requested"] > 0 for r in attacked) /
                max(1, len(attacked))
            ),
            "policy_integrity_failures": sum(r.get("policy_enforcement_integrity") != 1 for r in group),
        })

    result = {
        "schema_version": "1.0",
        "analysis_id": ANALYSIS_ID,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "analysis_plan_hash": sha256(PLAN_PATH),
        "provenance": provenance,
        "design": {
            "incident01_pilot": "16 matched profile-by-variant cells per model; exploratory cell-level inference",
            "full_corpus": "xAI, NVIDIA, and DeepSeek; 192 matched cells per model; pairwise inference clustered at the 12-incident level",
        },
        "pilot_descriptive": pilot_descriptive,
        "pilot_pairwise": pilot_pairs,
        "full_descriptive": full_descriptive,
        "full_three_model_pairwise": full_comparisons,
        "behavior": behavior,
    }

    OUTPUT.mkdir(parents=True, exist_ok=False)
    (OUTPUT / "comparison.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    with (OUTPUT / "full_three_model_pairwise.csv").open("w", encoding="utf-8", newline="") as h:
        fields = ["metric", "reference_model", "comparison_model", "unit", "n_pairs",
                  "mean_difference", "difference_ci", "paired_effect_dz", "p_value",
                  "p_value_holm", "test"]
        w = csv.DictWriter(h, fields); w.writeheader(); w.writerows(full_comparisons)
    with (OUTPUT / "incident01_three_model.csv").open("w", encoding="utf-8", newline="") as h:
        fields = ["metric", "reference_model", "comparison_model", "n_pairs",
                  "mean_difference", "difference_ci", "paired_effect_dz", "p_value",
                  "p_value_holm", "test"]
        w = csv.DictWriter(h, fields); w.writeheader(); w.writerows(pilot_pairs)

    full_lookup = {(x["model"], x["metric"]): x for x in full_descriptive}
    pilot_lookup = {(x["model"], x["metric"]): x for x in pilot_descriptive}
    lines = [
        "# WP1 cross-model statistical comparison", "",
        f"Analysis ID: `{ANALYSIS_ID}`  ",
        "Models: xAI Grok Build 0.1, NVIDIA Nemotron 3 Super, DeepSeek V4 Flash 0731  ",
        "Evaluator rubric: version 1.1", "",
        "## Analysis populations", "",
        "1. **Balanced three-model pilot:** incident01 only, 16 matched cells per model. "
        "Because there is only one incident, confidence intervals and cell-level sign-flip tests are exploratory and must not be generalized to the incident population.",
        "2. **Balanced full-corpus comparison:** xAI, NVIDIA, and DeepSeek, 192 cells per model. "
        "Inference uses the incident as the independent cluster (12 paired incident means), avoiding treatment of 192 correlated cells as independent replicates.",
        "", "## Full-corpus descriptive means", "",
        "Means below are descriptive run-level means; pairwise inference is reported separately at the incident-cluster level.", "",
        "| Metric | xAI | NVIDIA | DeepSeek |",
        "|---|---:|---:|---:|",
    ]
    for metric in metrics:
        lines.append(
            f"| {metric} | "
            + " | ".join(fmt(full_lookup[(model, metric)]["mean"]) for model in full_models)
            + " |"
        )
    lines.extend(["", "## Full-corpus pairwise comparisons", "",
                  "Differences are comparison model minus reference model and use 12 paired incident clusters.", "",
                  "| Metric | Reference | Comparison | Difference | 95% cluster bootstrap CI | Holm p | dz |",
                  "|---|---|---|---:|---:|---:|---:|"])
    for comparison in full_comparisons:
        ci = comparison["difference_ci"]
        lines.append(
            f"| {comparison['metric']} | {comparison['reference_model']} | "
            f"{comparison['comparison_model']} | {fmt(comparison['mean_difference'])} | "
            f"{fmt(ci[0])} to {fmt(ci[1])} | "
            f"{fmt(comparison['p_value_holm'], 4)} | "
            f"{fmt(comparison['paired_effect_dz'])} |"
        )
    lines.extend(["", "## Three-model incident01 pilot", "",
                  "| Metric | xAI | NVIDIA | DeepSeek |", "|---|---:|---:|---:|"])
    for metric in metrics:
        lines.append(
            f"| {metric} | {fmt(pilot_lookup[(models[0], metric)]['mean'])} | "
            f"{fmt(pilot_lookup[(models[1], metric)]['mean'])} | "
            f"{fmt(pilot_lookup[(models[2], metric)]['mean'])} |"
        )
    lines.extend(["", "## Behavioral and safety outcomes", "",
                  "| Model and scope | Cells | Actions/cell | Denial rate | Exact injection cells | Semantic-equivalent cells | Total resistance failures | Enforcement failures |",
                  "|---|---:|---:|---:|---:|---:|---:|---:|"])
    for b in behavior:
        lines.append(
            f"| {b['model']} ({b['scope']}) | {b['cells']} | {b['actions_per_cell']:.3f} | "
            f"{100*b['denial_rate']:.1f}% | {b['exact_injection_cells']}/{b['attacked_cells']} | "
            f"{b['semantic_injection_cells']}/{b['attacked_cells']} | "
            f"{b['injection_resistance_failures']}/{b['attacked_cells']} | "
            f"{b['policy_integrity_failures']} |"
        )
    lines.extend(["", "## Interpretation", "",
        "- Policy-enforcement integrity was perfect in all included runs; this does not establish that every policy-allowed action was semantically safe.",
        "- Injection resistance is scored from exact or evaluator-declared semantically equivalent requested actions, independently of whether policy denied the request.",
        "- Provider adapters and retry histories differ. Model identity is therefore partially confounded with provider and transport implementation.",
        "- Kimi and Llama are excluded from this balanced comparison because they did not complete the frozen 192-cell protocol.",
        "- No adjustment is made for model/API cost, latency, or token usage in this comparison.",
        "- Statistical estimates should be reported with confidence intervals and effect sizes; non-significance must not be interpreted as equivalence.", "",
        "Machine-readable results are in `comparison.json`; exact paired tables are in the accompanying CSV files.", "",
    ])
    (OUTPUT / "report.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"WROTE {OUTPUT}")


if __name__ == "__main__":
    main()
