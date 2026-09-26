# Paper 171: offline evaluation and replication

This repository contains scoring code, labels and the Experiment 1 artifact for **From Adversarial Evidence to Executed Action: A Five-Model Study of Policy-Mediated Autonomous Cyber Defence**, Ulykbek Shambulov, Nazarbayev University. Accepted to SIDe 2026, Springer Nature STEAM-H route; final volume metadata and DOI are pending.

## Reproduce the published results offline

Using Python 3.10+ with the standard library:

```sh
python3 publication/side2026/reproduce.py --output replication-output/side2026
```

The command verifies archive and scientific-input hashes, independently rescores all **2,858 observations**, and checks the paper's tables, missingness, ICC, weighting sensitivity and primary incident-clustered inference. It requires no agent checkout, network access, API credentials or model calls. Inputs are never overwritten; choose a new output directory for another run.

See [the artifact guide](publication/side2026/README.md) for contents, output definitions, limitations and figure instructions. The ~29 MiB archive preserves the full first-experiment campaign attempt history; failed attempts are provenance, not additional scored observations.

## Research isolation

This is an **evaluator-only** workspace. It contains ground truth and attack-variant labels. Never mount it, retrieve from it or include its results in an acting model's controlled run. Public accessibility would not remove this experimental separation requirement. Fresh agent runs use the companion [agent repository](https://github.com/Ulykbek/AutonomousCyberDefenderAgenticAI) and its staged incident contexts.

Operator documentation remains in [the evaluator runbook](docs/reproduction_runbook.md), [scoring methodology](docs/scoring_methodology.md) and [statistical methodology](docs/statistical_analysis.md). Historical campaign scripts are retained; the publication wrapper resolves original absolute paths through a relative artifact index instead of requiring the author's machine layout.

## Development and release

```sh
python3 -m unittest discover -s tests -p 'test_score*.py' -v
python3 -m unittest discover -s tests -p 'test_analysis.py' -v
python3 -m unittest discover -s tests -p 'test_publication.py' -v
```

Later unpublished CyberBroker studies remain outside the Paper 171 artifact and are ignored by Git. See [release preparation](publication/side2026/RELEASE_CHECKLIST.md), [licensing status](LICENSING.md) and [CITATION.cff](CITATION.cff). A clean, history-free export of both repositories is available through `tools/export_publication.py`.
