"""Evaluator-only paired replication analysis for WP1 R001 versus R002."""

from __future__ import annotations

import csv
import json
import statistics
from datetime import datetime, timezone

from analysis.analyze_campaign import holm_adjust, paired_comparison
from analysis.compare_wp1_models import PLAN_PATH, RESULTS, mean_ci, rows_for, sha256


ANALYSIS_ID = "wp1-r001-vs-r002-replication-20260828-v1"
OUTPUT = RESULTS / "round_comparison" / ANALYSIS_ID
MODELS = {
    "xAI Grok Build 0.1": {
        "R001": ["EXP-XAI-BUILD01-PILOT-002", "EXP-XAI-BUILD01-VARIANTS-REMAINING-001"],
        "R002": ["EXP-R002-XAI-GROK-BUILD01-FULL-001"],
    },
    "NVIDIA Nemotron 3 Super": {
        "R001": ["EXP-OPENROUTER-NVIDIA-NEMOTRON3-SUPER-INCIDENT01-VARIANTS-002", "EXP-OPENROUTER-NVIDIA-NEMOTRON3-SUPER-VARIANTS-REMAINING-001"],
        "R002": ["EXP-R002-OPENROUTER-NVIDIA-NEMOTRON3-SUPER-FULL-001"],
    },
    "DeepSeek V4 Flash 0731": {
        "R001": ["EXP-OPENROUTER-DEEPSEEK-V4-FLASH-0731-INCIDENT01-VARIANTS-001", "EXP-OPENROUTER-DEEPSEEK-V4-FLASH-0731-VARIANTS-REMAINING-001"],
        "R002": ["EXP-R002-OPENROUTER-DEEPSEEK-V4-FLASH-0731-FULL-001"],
    },
}


def key(row):
    return row["incident_id"], row["profile"], row["variant"]


def correlation(left, right):
    if len(left) != len(right) or len(left) < 2:
        raise ValueError("correlation requires equal non-trivial samples")
    mean_left, mean_right = statistics.fmean(left), statistics.fmean(right)
    numerator = sum((a - mean_left) * (b - mean_right) for a, b in zip(left, right))
    denominator = (
        sum((a - mean_left) ** 2 for a in left)
        * sum((b - mean_right) ** 2 for b in right)
    ) ** 0.5
    return numerator / denominator if denominator else 0.0


def main() -> None:
    if OUTPUT.exists():
        raise FileExistsError(f"immutable output already exists: {OUTPUT}")
    plan = json.loads(PLAN_PATH.read_text(encoding="utf-8"))
    metrics = [plan["primary_metric"], *plan["secondary_metrics"]]
    loaded = {}
    provenance = []
    for model, rounds in MODELS.items():
        for round_id, campaign_ids in rounds.items():
            rows, prov = rows_for(model, campaign_ids)
            if len(rows) != 192:
                raise ValueError(f"{model} {round_id} has {len(rows)} scored cells")
            loaded[model, round_id] = rows
            provenance.extend({"model": model, "round": round_id, **item} for item in prov)

    descriptive = []
    comparisons = []
    stability = []
    for model in MODELS:
        r1 = loaded[model, "R001"]
        r2 = loaded[model, "R002"]
        m1, m2 = {key(r): r for r in r1}, {key(r): r for r in r2}
        if set(m1) != set(m2) or len(m1) != 192:
            raise ValueError(f"unbalanced round keys for {model}")
        for round_id, rows in (("R001", r1), ("R002", r2)):
            for metric in metrics:
                values = [float(r[metric]) for r in rows if r.get(metric) is not None]
                rec = {"model": model, "round": round_id, "metric": metric}
                rec.update(mean_ci(values, plan, f"round:{model}:{round_id}:{metric}"))
                descriptive.append(rec)
        for metric in metrics:
            clusters = {}
            for round_id, mapping in (("R001", m1), ("R002", m2)):
                clusters[round_id] = {}
                for incident in sorted({k[0] for k in mapping}):
                    values = [float(row[metric]) for k, row in mapping.items()
                              if k[0] == incident and row.get(metric) is not None]
                    if values:
                        clusters[round_id][("cluster", incident, 1)] = statistics.fmean(values)
            rec = {"model": model, "metric": metric, "reference_round": "R001",
                   "comparison_round": "R002", "unit": "incident_cluster"}
            rec.update(paired_comparison(clusters["R001"], clusters["R002"], plan,
                                         f"replication:{model}:{metric}"))
            comparisons.append(rec)
        paired_overall_1 = [float(m1[k]["overall_score"]) for k in sorted(m1)]
        paired_overall_2 = [float(m2[k]["overall_score"]) for k in sorted(m2)]
        stability.append({
            "model": model,
            "matched_cells": 192,
            "overall_score_cell_correlation": correlation(
                paired_overall_1, paired_overall_2
            ),
            "exact_injection_cells_r001": sum(r["injected_actions_requested"] > 0 for r in r1 if r["variant"] != "BASE"),
            "exact_injection_cells_r002": sum(r["injected_actions_requested"] > 0 for r in r2 if r["variant"] != "BASE"),
            "actions_per_cell_r001": statistics.fmean(r["requested_actions"] for r in r1),
            "actions_per_cell_r002": statistics.fmean(r["requested_actions"] for r in r2),
            "policy_integrity_failures_r001": sum(r["policy_enforcement_integrity"] != 1 for r in r1),
            "policy_integrity_failures_r002": sum(r["policy_enforcement_integrity"] != 1 for r in r2),
        })

    primary = [r for r in comparisons if r["metric"] == plan["primary_metric"]]
    secondary = [r for r in comparisons if r["metric"] != plan["primary_metric"]]
    holm_adjust(primary)
    holm_adjust(secondary)
    result = {
        "schema_version": "1.0", "analysis_id": ANALYSIS_ID,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "analysis_plan_hash": sha256(PLAN_PATH),
        "design": "Three models, 192 exactly matched cells per round and model; inference on 12 paired incident clusters; differences are R002 minus R001.",
        "provenance": provenance, "descriptive": descriptive,
        "paired_round_comparisons": comparisons, "stability": stability,
    }
    OUTPUT.mkdir(parents=True, exist_ok=False)
    (OUTPUT / "replication.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    with (OUTPUT / "paired_round_comparisons.csv").open("w", newline="", encoding="utf-8") as handle:
        fields = ["model", "metric", "reference_round", "comparison_round", "unit",
                  "n_pairs", "mean_difference", "difference_ci", "paired_effect_dz",
                  "p_value", "p_value_holm", "test"]
        writer = csv.DictWriter(handle, fields); writer.writeheader(); writer.writerows(comparisons)

    lookup = {(x["model"], x["round"], x["metric"]): x for x in descriptive}
    comp = {(x["model"], x["metric"]): x for x in comparisons}
    lines = ["# WP1 R001 versus R002 replication analysis", "", f"Analysis ID: `{ANALYSIS_ID}`", "",
             "All differences are R002 minus R001. Descriptive means use 192 runs per model and round; inference uses 12 paired incident clusters.", "",
             "## Overall score replication", "",
             "| Model | R001 | R002 | Difference | 95% cluster CI | Holm p | dz |",
             "|---|---:|---:|---:|---:|---:|---:|"]
    for model in MODELS:
        a, b, c = lookup[model, "R001", "overall_score"], lookup[model, "R002", "overall_score"], comp[model, "overall_score"]
        ci = c["difference_ci"]
        lines.append(f"| {model} | {a['mean']:.3f} | {b['mean']:.3f} | {c['mean_difference']:.3f} | {ci[0]:.3f} to {ci[1]:.3f} | {c['p_value_holm']:.4f} | {c['paired_effect_dz']:.3f} |")
    lines.extend(["", "## Stability and safety", "", "| Model | Cell-score correlation | Injection failures R001 | Injection failures R002 | Actions/cell R001 | Actions/cell R002 | Policy failures R001/R002 |", "|---|---:|---:|---:|---:|---:|---:|"])
    for s in stability:
        lines.append(f"| {s['model']} | {s['overall_score_cell_correlation']:.3f} | {s['exact_injection_cells_r001']}/144 | {s['exact_injection_cells_r002']}/144 | {s['actions_per_cell_r001']:.3f} | {s['actions_per_cell_r002']:.3f} | {s['policy_integrity_failures_r001']}/{s['policy_integrity_failures_r002']} |")
    lines.extend(["", "## Interpretation constraints", "",
                  "- R002 NVIDIA experienced a documented OpenRouter free-tier quota exhaustion and used a provider-facing schema transport that omitted uniqueItems while preserving local validation.",
                  "- Provider routing for NVIDIA was not pinned, so round differences cannot be attributed solely to model stochasticity.",
                  "- Retries are operational history, not independent replications.",
                  "- Non-significance is not evidence of equivalence; R003 is required before making stability claims.", ""])
    (OUTPUT / "report.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"WROTE {OUTPUT}")


if __name__ == "__main__":
    main()
