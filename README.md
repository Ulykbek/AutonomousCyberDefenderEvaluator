# Autonomous CyberDefender Evaluator

Research operators should follow the evaluator-only
[reproduction runbook](docs/reproduction_runbook.md) after all CyberDefender
processes have terminated.

Evaluator-only workspace for WP1 experiments. This directory must not be mounted,
copied, retrieved, or otherwise exposed to CyberDefender during a controlled run.

It contains ground truth and scoring logic. Agent-visible evidence remains in the
separate `AutonomousCyberDefenderAgenticAI` project.

## Isolation rule

During a controlled run, configure CyberDefender's filesystem scope to a staged
run directory or the agent project only. Never add this evaluator directory as a
workspace root, retrieval source, model attachment, prompt context, or container
mount.

Owner-only filesystem permissions reduce accidental disclosure to other OS users,
but they do not isolate two processes running as the same user. Containerized runs
should mount this directory only into the evaluator container after the agent run
has finished.

Ground truth files must not be copied into the agent repository. Evaluator output
may contain expected answers, so `experiment_results/` is evaluator-only as well.

## Validation

From this directory, run:

```bash
python3 evaluator/validate_ground_truth.py \
  --corpus ../AutonomousCyberDefenderAgenticAI/cases/corpus.json
```

## Phase 8 scoring

After a Phase 7 agent run has terminated, score its preserved run directory:

```bash
python3 evaluator/score_run.py /absolute/path/to/run
```

The versioned rubric and detailed methodology are stored in
`evaluator/scoring_rubric.json` and `docs/scoring_methodology.md`. Numeric output
is written beneath `experiment_results/` and must remain evaluator-only.

## Phase 9 campaign collection

After a Phase 9 campaign has finished, collect scores for every completed
attempt without exposing evaluator state to the campaign process:

```bash
python3 evaluator/score_campaign.py /absolute/path/to/campaign.json
```

Existing scores are reused only when their recorded run-manifest hash still
matches. Failed, invalid, timed-out, interrupted, and running attempts are
preserved by the campaign but are not scored.

Blinded evidence-variant campaigns are evaluated using the secret mapping in
`ground_truth/evidence_variants.json`. This file must never be copied into or
mounted for CyberDefender. Collection records exact injected-action requests,
semantic equivalents, enforcement outcomes, and matched changes against the
corresponding `BASE` cell.

## Phase 10 statistical analysis

Analyze a collected campaign from the evaluator workspace:

```bash
python3 analysis/analyze_campaign.py path/to/campaign_scores.json \
  --analysis-id pilot-v1
```

The versioned plan and methodological cautions are documented in
`analysis/analysis_plan.json` and `docs/statistical_analysis.md`. Analysis
directories are immutable and are never silently overwritten.
