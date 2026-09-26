#!/usr/bin/env python3
"""Recompute Paper 171 from preserved observations, offline and without modifying inputs."""
from __future__ import annotations
import argparse, csv, hashlib, itertools, json, math, re, statistics, sys, tarfile, tempfile
from collections import Counter
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT))
from evaluator.score_run import score_run, parse_policy_log, canonical_action
from analysis.compare_wp1_five_models_three_rounds import icc, MODELS
from analysis.analyze_campaign import paired_comparison, holm_adjust


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def close(a, b, label):
    if isinstance(a, dict):
        require(isinstance(b, dict) and set(a) == set(b), label + ': fields differ')
        for k in a:
            close(a[k], b[k], label + '.' + k)
    elif isinstance(a, list):
        require(isinstance(b, list) and len(a) == len(b), label + ': list length differs')
        for i, (x, y) in enumerate(zip(a, b)):
            close(x, y, label + f'[{i}]')
    elif isinstance(a, (float, int)) and not isinstance(a, bool):
        require(isinstance(b, (float, int)) and math.isclose(a, b, rel_tol=0, abs_tol=1e-12), label + ': numeric mismatch')
    else:
        require(a == b, label + ': mismatch')


def load_bundle(path):
    expected = path.with_suffix(path.suffix + '.sha256').read_text().split()[0]
    require(sha(path.read_bytes()) == expected, 'Bundle checksum mismatch')
    data, total = {}, 0
    with tarfile.open(path, 'r|gz') as tar:
        for member in tar:
            p = PurePosixPath(member.name)
            require(member.isfile() and not p.is_absolute() and '..' not in p.parts,
                    'Unsafe archive member')
            require(member.name not in data, 'Duplicate archive member')
            total += member.size
            require(total <= 512 * 1024 * 1024 and len(data) < 150000, 'Bundle size limit exceeded')
            data[member.name] = tar.extractfile(member).read()
    index = json.loads(data['index.json'])
    require(set(data) == set(index['files']) | {'index.json'}, 'Bundle inventory differs')
    for name, checksum in index['files'].items():
        require(sha(data[name]) == checksum, 'Bundle member hash mismatch: ' + name)
    for line in data['archive/SHA256SUMS.txt'].decode().splitlines():
        checksum, name = line.split('  ', 1)
        require(sha(data['archive/' + name]) == checksum, 'Original archive hash mismatch: ' + name)
    for c in index['campaigns']:
        original = json.loads(data[c['score_index_path']])
        require(sha(data[c['campaign_path']]) == original['campaign_index_hash'], 'Campaign hash mismatch')
        for run in original['runs']:
            require(sha(data['scores/' + run['run_id'] + '.json']) == run['score_file_hash'], 'Score provenance mismatch')
    return data, index


def dump_csv(path, rows):
    with path.open('w', newline='') as out:
        writer = csv.DictWriter(out, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def reproduce(output, bundle):
    require(not output.exists(), 'Output already exists; choose a new --output directory')
    release = json.loads((HERE / 'RELEASE.json').read_text())
    for name, checksum in release['scientific_input_sha256'].items():
        require(sha((ROOT / name).read_bytes()) == checksum, 'Changed release input: ' + name)
    data, index = load_bundle(bundle)
    require(len(index['rows']) == len({r['run_id'] for r in index['rows']}) == 2858, 'Scored cohort mismatch')
    for row in index['rows']:
        rid = row['run_id']
        require(isinstance(rid, str) and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]*', rid), 'Unsafe run identifier')
        require(row['run_path'] == 'runs/' + rid and row['score_path'] == 'scores/' + rid + '.json', 'Unsafe observation path')
    weights = json.loads((ROOT / 'evaluator/scoring_rubric.json').read_text())['weights']
    variants = json.loads((ROOT / 'ground_truth/evidence_variants.json').read_text())['variants']
    schemes = {
        'A': weights,
        'B': {k: 1 for k in weights},
        'C': {k: v for k, v in weights.items() if k != 'injection_resistance'},
        'D': {k: v for k, v in weights.items() if k not in ('injection_resistance', 'policy_enforcement_integrity')},
        'E': {k: 1 for k in weights if k not in ('injection_resistance', 'policy_enforcement_integrity')},
        'F': {k: 1 for k in weights if k not in ('injection_resistance', 'policy_enforcement_integrity', 'action_selection_f1')},
    }
    def weighted(metrics, w):
        active = [k for k in w if metrics[k] is not None]
        return sum(w[k] * metrics[k] for k in active) / sum(w[k] for k in active)
    loaded, counts, matches = {}, {}, []
    # Only scorer-required files are materialized. Original paths in manifests are inert provenance.
    required = ['manifest.json', 'output/assessment.json']
    optional = ['output/policy_decisions.jsonl', 'output/cyberdefender_actions.txt']
    with tempfile.TemporaryDirectory(prefix='paper171-') as tmp:
        for row in index['rows']:
            rd = Path(tmp) / row['run_id']
            for name in required + optional:
                key = row['run_path'] + '/' + name
                if key not in data:
                    require(name in optional, 'Missing scoring input: ' + key)
                    continue
                target = rd / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data[key])
            saved = json.loads(data[row['score_path']])
            fresh = score_run(rd)
            for key in ('metrics', 'details', 'input_hashes', 'overall_score', 'applicable_weight', 'scorable'):
                close(saved[key], fresh[key], row['run_id'] + ':' + key)
            model, round_id = row['model'], row['round']
            key = (row['incident'], row['profile'], row['variant'])
            mapping = loaded.setdefault((model, round_id), {})
            require(key not in mapping, 'Duplicate model/round cell')
            mapping[key] = {'original': saved['overall_score'], 'schemes': {s: weighted(fresh['metrics'], w) for s, w in schemes.items()}}
            cnt = counts.setdefault(model, Counter())
            cnt['scored_cells'] += 1
            cnt.update({'all_' + k: v for k, v in fresh['details']['audit_counts'].items()})
            if row['variant'] == 'BASE':
                continue
            cnt['attacked_cells'] += 1
            truth = variants[row['variant']]
            targets = {canonical_action(a['action'], a['arguments']) for a in truth['injected_actions'] + truth['semantic_equivalents']}
            manifest = json.loads((rd / 'manifest.json').read_text())
            decisions = parse_policy_log(rd / 'output/policy_decisions.jsonl', manifest['experiment_id'], manifest['run_id'])
            hits = [d for d in decisions if canonical_action(d['action'], d['arguments']) in targets]
            cnt['positive_cells'] += bool(hits)
            for d in hits:
                cnt['injected_calls'] += 1
                cnt['injected_allowed' if d['allowed'] else 'injected_denied'] += 1
                matches.append({'model': model, 'round': round_id, 'run_id': row['run_id'],
                                'request_id': d['request_id'], 'action': d['action'], 'allowed': d['allowed'],
                                'reason': d.get('reason', '')})
    models, rounds = list(MODELS), ['R001', 'R002', 'R003']
    require(set(models) == set(index['models']), 'Model registry differs')
    common = set.intersection(*(set(m) for m in loaded.values()))
    require(len(common) == 172, 'Complete-case cohort differs')
    table1, table2, missing, complete, profiles = [], [], [], [], []
    for model in models:
        c = counts[model]
        row = {'model': model}
        within = sorted(set.intersection(*(set(loaded[model, r]) for r in rounds)))
        for r in rounds:
            row[r] = statistics.fmean(v['original'] for v in loaded[model, r].values())
            missing.append({'model': model, 'round': r, 'planned': 192, 'scored': len(loaded[model, r]), 'missing': 192-len(loaded[model, r])})
        row.update({'icc_3_1': icc([[loaded[model, r][k]['original'] for k in within] for r in rounds]),
                    'positive_cells': c['positive_cells'], 'attacked_cells': c['attacked_cells'],
                    'cell_rate_percent': 100*c['positive_cells']/c['attacked_cells'],
                    'calls_allowed': c['injected_allowed'], 'calls_denied': c['injected_denied']})
        table1.append(row)
        table2.append({'model': model, **{s: statistics.fmean(v['schemes'][s] for r in rounds for v in loaded[model, r].values()) for s in schemes}})
        complete.append({'model': model, 'n': 3*len(common), **{s: statistics.fmean(loaded[model, r][k]['schemes'][s] for r in rounds for k in common) for s in schemes}})
        for profile in sorted({k[1] for k in loaded[model, 'R001']}):
            profiles.append({'model': model, 'profile': profile, 'mean': statistics.fmean(v['original'] for r in rounds for k, v in loaded[model, r].items() if k[1] == profile)})
    plan = json.loads((ROOT / 'analysis/analysis_plan.json').read_text())
    comparisons = []
    incidents = sorted({r['incident'] for r in index['rows']})
    for ref, cmp in itertools.combinations(models, 2):
        left, right = {}, {}
        for incident in incidents:
            paired = [(loaded[ref, r][k]['original'], loaded[cmp, r][k]['original'])
                      for r in rounds for k in sorted(set(loaded[ref, r]) & set(loaded[cmp, r])) if k[0] == incident]
            left['incident', incident, 1] = statistics.fmean(x for x, _ in paired)
            right['incident', incident, 1] = statistics.fmean(y for _, y in paired)
        rec = {'metric': 'overall_score', 'reference_model': ref, 'comparison_model': cmp, 'unit': 'incident_cluster_pooled_rounds'}
        rec.update(paired_comparison(left, right, plan, f'five-model:overall_score:{ref}:{cmp}'))
        comparisons.append(rec)
    holm_adjust(comparisons)
    archived = json.loads(data['archive/five_model_three_round/five_model_three_round.json'])
    expected_comparisons = [r for r in archived['cross_model_comparisons'] if r['metric'] == 'overall_score']
    close(expected_comparisons, comparisons, 'Primary incident-clustered inference')
    expectations = json.loads((HERE / 'paper_expectations.json').read_text())
    for row in table1:
        e = expectations['table1'][row['model']]
        for k, v in e.items():
            digits = 2 if k == 'cell_rate_percent' else 3 if k in rounds + ['icc_3_1'] else 0
            require(round(row[k], digits) == v, 'Paper Table 1 mismatch: ' + row['model'] + '/' + k)
    for row in table2:
        require([round(row[s], 5) for s in schemes] == expectations['table2'][row['model']], 'Paper Table 2 mismatch: ' + row['model'])
    totals = dict(sum(counts.values(), Counter()))
    close(expectations['totals'], {k: totals.get(k, 0) for k in expectations['totals']}, 'Published totals')
    require(sum(r['missing'] for r in missing) == 22, 'Missing-cell mismatch')
    # Save only after all verifications have passed. Inputs and earlier outputs remain untouched.
    output.mkdir(parents=True)
    for name, rows in [('table1', table1), ('table2', table2), ('missingness', missing), ('complete_case', complete), ('profile_means', profiles), ('primary_inference', comparisons), ('injected_calls', matches)]:
        dump_csv(output / (name + '.csv'), rows)
    summary = {'status': 'PASS', 'scored_runs': len(index['rows']), 'attempts_preserved': len(index['attempts']),
               'attempt_status_counts': dict(Counter(a['status'] for a in index['attempts'])),
               'complete_cell_templates': len(common), 'totals': totals, 'counts': counts,
               'primary_inference_recomputed': True, 'model_calls': 0,
               'bundle_sha256': sha(bundle.read_bytes()), 'python': sys.version.split()[0]}
    (output / 'verification.json').write_text(json.dumps(summary, indent=2) + '\n')
    # Figure 3's data; editable original TikZ sources are in figures/. No TeX installation is required for tables.
    svg = ['<svg xmlns="http://www.w3.org/2000/svg" width="800" height="330" viewBox="0 0 800 330">',
           '<rect width="800" height="330" fill="white"/><text x="20" y="28" font-family="sans-serif" font-size="18">Injected-action request rates (% attacked cells)</text>']
    for i, r in enumerate(sorted(table1, key=lambda r: r['cell_rate_percent'])):
        y = 60 + 48*i; value = r['cell_rate_percent']
        svg += [f'<text x="20" y="{y+20}" font-family="sans-serif" font-size="14">{r["model"]}</text>',
                f'<rect x="240" y="{y}" width="{value*55:.4f}" height="28" fill="#245a81"/>',
                f'<text x="{250+value*55:.4f}" y="{y+20}" font-family="sans-serif" font-size="14">{value:.2f}%</text>']
    svg += ['<text x="20" y="320" font-family="sans-serif" font-size="12">Intent-layer events; all matched injected calls were denied.</text></svg>']
    (output / 'injection_rates.svg').write_text('\n'.join(svg))
    print(f'PASS: 2,858 rescored runs; paper Tables 1–2, missingness, ICC, primary inference and totals agree. Outputs: {output}')

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'replication-output/side2026')
    parser.add_argument('--bundle', type=Path, default=HERE / 'experiment1.tar.gz')
    args = parser.parse_args()
    reproduce(args.output.resolve(), args.bundle.resolve())
