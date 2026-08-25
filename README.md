# Autonomous CyberDefender Evaluator

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
