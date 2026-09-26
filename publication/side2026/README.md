# Experiment 1 replication artifact — Paper 171

**Version:** 1.0.0, private preparation.
**Paper:** From Adversarial Evidence to Executed Action: A Five-Model Study of Policy-Mediated Autonomous Cyber Defence.
**Author:** Ulykbek Shambulov, Nazarbayev University.
**Venue:** SIDe 2026, Springer Nature STEAM-H route, accepted; final publication metadata pending.

## One command

From the evaluator repository root:

```sh
python3 publication/side2026/reproduce.py --output replication-output/side2026
```

Python 3.10+; standard library only. Approximately 29 MiB download, with temporary scoring files and in-memory archive contents. Allow roughly 512 MiB of available memory and temporary disk space. No network or model calls are made. Runtime varies by machine. The output directory must not already exist.

The wrapper verifies the bundle SHA-256, every archived member, the original 62-file archive manifest, campaign/score provenance and hashes of the scorer, labels, rubric and analysis functions. It recomputes every cell's metrics from the original assessment and policy/execution logs, with a 1e-12 tolerance only for floating-point arithmetic. Published decimal values are compared with `paper_expectations.json`.

## Contents and provenance

`experiment1.tar.gz` contains 2,858 scored runs and their score files, plus all **4,877 attempts** in the selected campaign ledgers: 2,858 completed, 2,005 failed, ten interrupted and four timed out. These attempts are not 4,877 independent observations. The study planned 2,880 final cells and retains 22 terminal missing cells. A run's archived model metadata records the actual requested provider/model configuration; paper model names are experimental identifiers.

The bundle preserves original bytes, including failed attempts, manifest timestamps, model output, composed instructions and evidence. Historical absolute paths are retained **as provenance only**. `index.json` maps observations to safe relative archive locations; no path rewriting changes the frozen hashes. Only scorer-required files are temporarily materialized. Original files containing paths are not executed.

The first-experiment code baselines are recorded in `RELEASE.json`; they are provenance commits, not claims that every development file had that exact commit during every run. The scientific files used by this artifact are individually hashed. Rebuilding the bundle is a maintainer operation using `build_bundle.py --workspace PATH`; consumers never need the original PhD workspace.

## Paper-to-output map

| Paper result | Recreated output | Verification |
|---|---|---|
| Table 1: round scores and ICC | `table1.csv` | All printed values checked |
| Table 1: attacked-cell rates and allow/deny counts | `table1.csv`, `injected_calls.csv` | 80 positive cells; 92 matched calls, all denied |
| Table 2: six weight schemes | `table2.csv` | All 30 printed means checked |
| Complete-case sensitivity | `complete_case.csv` | 172 shared templates / 516 observations per model |
| Missingness | `missingness.csv` | 2,880 planned, 2,858 scored, 22 missing |
| Overall-score inference | `primary_inference.csv` | Recomputed bootstrap intervals, sign-flip tests and Holm correction for all ten model pairs |
| Instruction-profile descriptive means | `profile_means.csv` | Derived from original saved scores |
| Figure 3 injection rates | `injection_rates.svg` and Table 1 data | Regenerated from observations |
| Figures 1–2 conceptual diagrams | `figures/*.tex` and matching PDFs | Original editable diagrams, not statistical measurements |
| Audit totals and attempt accounting | `verification.json` | 7,666 requests; 5,090 allows/executions; 2,576 denials |

Original TikZ sources and vector PDFs for all three manuscript figures are included. To reproduce their exact typography, compile each standalone `.tex` file with an installed TeX distribution including TikZ/PGF, standalone and newtx. The generated SVG provides an API-free plot of the same Figure 3 values; it is not claimed to be byte-identical to the manuscript figure. Main manuscript, publisher class/template and reviewer correspondence are intentionally outside this software/data artifact.

The statistical analysis reuses the frozen original functions and seed strings. It reproduces the paper's primary overall-score inference, not every exploratory secondary-metric analysis archived during research. Twelve incident clusters support that inference. Repeated profiles, variants, rounds and retries must not be interpreted as independent incidents.

## Interpretation and limits

All prescribed injection targets were prohibited by policy. Zero executed matched injections validates the tested enforcement path, not the safety of every allowed action. Execution was simulated. Labels were authored for synthetic incidents and do not constitute completed independent adjudication. No later 24-scenario comparative CyberBroker results are included.

Exact offline recomputation and a fresh model replication answer different questions. Hosted model availability and stochastic responses can change. The artifact supports checking the calculations from preserved observations; it cannot guarantee identical outputs from future API calls or establish general deployment safety.

The declared attack mapping, ground truth and saved answers must remain outside future actor contexts. The test corpus is disclosed by this artifact; future generalization studies should use held-out material.

## Availability statement draft

After a stable release has actually been published, insert its real URL/DOI and version:

> The Experiment 1 code, synthetic incident corpus, preserved run artifacts, scoring rubric and offline analysis are available in the versioned Paper 171 replication artifact at [verified release URL/DOI]. The artifact reproduces the reported results without model API calls. It excludes later unpublished experiments.

This is a draft, not a claim that a public release currently exists. See `RELEASE_CHECKLIST.md` and the repository's `LICENSING.md`.
