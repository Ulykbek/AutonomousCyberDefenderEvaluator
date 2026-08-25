# Phase 10 statistical analysis

Phase 10 converts evaluator-only run scores into reproducible descriptive and
comparative results. The analysis plan is versioned in
`analysis/analysis_plan.json`; it must be frozen before a confirmatory campaign
is examined.

## Unit of analysis and pairing

A run is the descriptive unit. Profile comparisons are paired by condition,
incident, and repetition. Only complete pairs for a metric are used, with no
imputation. The estimand is the paired mean difference, comparison profile minus
the neutral reference profile by default.

The primary outcome is overall score. Component scores are secondary outcomes.
Non-applicable values, such as injection resistance for a non-injection case,
remain missing rather than being replaced with success or failure.

## Uncertainty and tests

- Means receive deterministic percentile bootstrap confidence intervals.
- Paired mean differences receive paired bootstrap confidence intervals.
- Two-sided paired sign-flip permutation tests are exact for up to 16 pairs and
  use deterministic Monte Carlo sampling above that threshold.
- P-values use Holm correction across profile comparisons within each metric.
- Paired standardized effect size `dz` is reported when difference variance is
  nonzero.

P-values do not establish practical importance, and failure to reject a null
hypothesis does not demonstrate equivalence. Estimates, intervals, sample sizes,
missingness, and effect sizes should lead interpretation.

## Integrity and outputs

Analysis refuses a changed campaign index or changed run-score file. It records
hashes of the campaign score index, campaign index, and analysis plan. An
existing analysis directory is never overwritten.

Outputs are:

- `analysis.json` — complete machine-readable result;
- `run_metrics.csv` — one row per scored run;
- `profile_summary.csv` — descriptive outcomes per condition and profile;
- `paired_comparisons.csv` — paired estimates and corrected tests;
- `report.md` — compact primary-outcome report.

Run from the evaluator workspace only:

```sh
python3 analysis/analyze_campaign.py path/to/campaign_scores.json \
  --analysis-id pilot-v1
```

This phase performs analysis but does not decide whether results support a thesis
claim. Confirmatory hypotheses, exclusion rules, minimum sample size, and any
deviations should be pre-registered separately.
