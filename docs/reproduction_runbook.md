# Evaluator reproduction runbook

> **Protocol:** `WP1-REPRODUCTION-1.0`  
> **Scope:** post-run scoring, review, and statistical analysis  
> **Classification:** evaluator-only  
> **Precondition:** every CyberDefender process has terminated

This runbook begins where the agent-side runbook ends. It explains how to score
preserved CyberDefender artifacts without exposing hidden truth to the model,
silently changing results, or confusing an engineering smoke test with research
evidence.

## 1. Enforce the evaluator boundary

```text
Completed agent artifacts ──read-only──▶ Evaluator
                                         │
                                         ├── hidden ground truth
                                         ├── versioned scoring rubric
                                         ├── run and campaign scores
                                         └── statistical analysis

Evaluator files ───────────────────────X──▶ CyberDefender
```

Before evaluation, confirm:

- all CyberDefender and CyberBroker processes have terminated;
- the evaluator directory was not mounted into the agent environment;
- ground truth was never copied into an agent run directory;
- the campaign index and run directories are preserved and preferably read-only;
- evaluator results will remain outside the agent workspace.

Owner-only directory permissions reduce accidental disclosure but do not isolate
processes running as the same OS user. Use separate containers or accounts for a
strong technical-separation claim.

## 2. Record evaluator identity

From the evaluator repository root, preserve:

```sh
git rev-parse HEAD
python3 --version
uname -a
```

Record these fixed versions:

```text
Protocol:       WP1-REPRODUCTION-1.0
Ground truth:   schema 1.0
Scoring rubric: 1.0
Analysis plan:  1.0
```

Also retain the agent repository commit, experiment manifest, campaign index,
model metadata, and dependency lock supplied during handoff.

## 3. Validate hidden truth before reading results

Run ground-truth validation against the agent-visible corpus registry before
scoring any model output:

```sh
python3 evaluator/validate_ground_truth.py \
  --corpus ../AutonomousCyberDefenderAgenticAI/cases/corpus.json
```

Expected characteristics of the current synthetic corpus:

```text
12 incidents
7 malicious
4 benign
1 ambiguous
4 injection-bearing
```

Stop on any mismatch. Do not repair ground truth after viewing model results
without declaring a new rubric/protocol version.

## 4. Verify the handoff

For a single run, inspect its manifest without editing it:

```sh
python3 -m json.tool /absolute/path/to/run/manifest.json
```

Require:

- `status` is `completed`;
- evidence hashes before and after are identical;
- output hashes are present;
- audit counts are internally consistent;
- incident, profile, condition, repetition, attempt, model, and baseline IDs are
  present;
- `assessment.json`, policy log, and action log exist.

For a campaign, validate the supplied index from the agent repository tooling:

```sh
python3 /path/to/agent-repository/scripts/validate_manifests.py \
  /absolute/path/to/campaign.json \
  --type campaign
```

Evaluation code performs additional integrity checks and refuses changed inputs.

## 5. Score one smoke-test run

Use this only to verify the end-to-end interface:

```sh
python3 evaluator/score_run.py /absolute/path/to/completed/run
```

The default score location is:

```text
experiment_results/<experiment-id>/<run-id>.score.json
```

Inspect the result:

```sh
python3 -m json.tool \
  experiment_results/<experiment-id>/<run-id>.score.json
```

Confirm that the result records hashes for:

- run manifest;
- structured assessment;
- hidden ground truth;
- scoring rubric.

A smoke-test score confirms the interface; it does not answer the research
question.

## 6. Score a complete campaign

After the campaign has stopped:

```sh
python3 evaluator/score_campaign.py /absolute/path/to/campaign.json
```

The collector:

- scores completed attempts;
- skips failed, invalid, timed-out, interrupted, and running attempts;
- preserves one score file per completed run;
- records each score-file hash;
- refuses to reuse a score if any hashed scoring input changed;
- writes `campaign_scores.json` as the Phase 10 input.

Run the same command again to verify safe reuse. Unchanged results should be
marked `reused`, not recreated with different contents.

## 7. Conduct blinded narrative review separately

Automatic scoring deliberately excludes:

- expected-finding coverage in free prose;
- rationale quality;
- uncertainty calibration;
- unsupported or hallucinated claims.

If these outcomes are part of the study:

1. Freeze an annotation guide before review.
2. Remove model/profile identifiers from review copies.
3. Randomize presentation order.
4. Use at least two independent reviewers where feasible.
5. Record disagreements without overwriting original ratings.
6. Calculate and report inter-rater agreement.
7. Resolve disagreements using a predefined procedure.

Do not ask an evaluator model to replace blinded human review unless that model,
prompt, reliability study, and failure rules are themselves part of the
pre-registered method.

## 8. Run statistical analysis

Analyze a collected campaign:

```sh
python3 analysis/analyze_campaign.py \
  experiment_results/<campaign-id>/campaign_scores.json \
  --analysis-id pilot-v1
```

The analysis directory contains:

```text
analysis.json
run_metrics.csv
profile_summary.csv
paired_comparisons.csv
report.md
```

Phase 10 uses:

- overall score as the primary outcome;
- component scores as secondary outcomes;
- pairing by condition, incident, and repetition;
- complete pairs without imputation;
- deterministic bootstrap confidence intervals;
- exact or deterministic Monte Carlo sign-flip tests;
- Holm correction within metric families;
- paired effect size `dz` when estimable.

An existing analysis directory is never overwritten. A revised analysis must use
a new analysis ID and document why it differs.

## 9. Read the results in the correct order

1. **Data quality:** missing, failed, retried, invalid, and unscored runs.
2. **Descriptive estimates:** sample sizes, means, dispersion, and intervals.
3. **Paired differences:** direction, magnitude, and confidence intervals.
4. **Adjusted tests:** interpreted with effect sizes, not alone.
5. **Injection subset:** only cases where the metric applies.
6. **Policy integrity:** distinguish model action selection from broker safety.
7. **Manual review:** report separately from automatic scores.
8. **Limitations:** model drift, synthetic evidence, sample size, and isolation.

Do not interpret `p > 0.05` as proof that profiles are equivalent. Do not treat
a policy denial as incorrect model reasoning when the requested action was
justified but intentionally outside granted capability; action selection and
policy enforcement are separate outcomes.

## 10. Diagnose evaluation failures

| Symptom | Meaning | Correct response |
|---|---|---|
| Assessment rejected | Missing, extra, or invalid structured field | Mark run unscorable; preserve original |
| Cross-run audit record | Correlation/integrity violation | Mark run invalid; investigate campaign isolation |
| Denied request executed | Enforcement failure | Stop analysis and preserve all evidence |
| Score input hash changed | Artifact changed after scoring | Do not overwrite; identify source of mutation |
| Campaign hash mismatch | Campaign changed after collection | Re-collect under documented conditions |
| Reference profile absent | Requested comparison cannot be formed | Correct analysis configuration, not raw data |
| No complete pairs | Missing design cells or non-applicable metric | Report missingness; do not impute silently |

## 11. Separate pilot and confirmatory outputs

Use distinct campaign and analysis identifiers:

```text
PILOT-*   method debugging and feasibility
FINAL-*   frozen confirmatory campaign
```

Pilot findings may motivate a new protocol version. They must not be merged into
the final confirmatory dataset merely to increase sample size.

## 12. Archive the complete research record

Preserve together, while maintaining access controls:

```text
agent repository commit and baseline
evaluator repository commit
protocol and preregistration
dependency lock files
experiment and campaign manifests
all run directories, including failures
ground-truth and rubric hashes
run-level scores
campaign_scores.json
analysis plan and analysis outputs
manual-review data and agreement results
environment and execution logs
documented deviations
```

The public reproduction package may need a redacted or embargoed ground-truth
release to prevent contaminating future model evaluations. State clearly which
materials are public, restricted, or released after data collection.

## 13. Final reproducibility statement

A result is reproducible only when another researcher can determine:

- exactly what the model saw;
- exactly what it could request;
- exactly what policy allowed or denied;
- exactly which model and software produced the run;
- exactly how hidden truth generated the score;
- exactly how run scores generated the reported statistics;
- which failures, retries, exclusions, and deviations occurred.

Preserving only the final table is not enough. The auditable chain from evidence
to action request, policy decision, score, and analysis is the research object.

