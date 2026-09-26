#!/usr/bin/env python3
"""Maintainer-only builder. Original artifacts are never edited; consumers need no workspace."""
from __future__ import annotations
import argparse, ast, gzip, hashlib, io, json, re, tarfile
from pathlib import Path


def digest(data):
    return hashlib.sha256(data).hexdigest()


def build(workspace: Path, destination: Path):
    archive = workspace / 'WP1_Five_Model_Three_Round_Results_20260829'
    source = archive / 'methodology/compare_wp1_five_models_three_rounds.py'
    tree = ast.parse(source.read_text())
    models = next(ast.literal_eval(n.value) for n in tree.body if isinstance(n, ast.Assign)
                  and any(isinstance(t, ast.Name) and t.id == 'MODELS' for t in n.targets))
    files, rows, campaigns, attempts = {}, [], [], {}
    def add(name, path):
        if path.is_symlink():
            raise ValueError(f'Symlink forbidden: {path.name}')
        data = path.read_bytes()
        if name in files and files[name] != data:
            raise ValueError(f'Conflicting member: {name}')
        files[name] = data
    for path in sorted(archive.rglob('*')):
        if path.is_file() and path.name != '.DS_Store':
            add('archive/' + path.relative_to(archive).as_posix(), path)
    for model, rounds in models.items():
        for round_id, ids in rounds.items():
            for cid in ids:
                ip = archive / 'provenance/campaign_scores' / (cid + '.json')
                cp = archive / 'provenance/campaign_indexes' / (cid + '.json')
                index, campaign = json.loads(ip.read_text()), json.loads(cp.read_text())
                if digest(cp.read_bytes()) != index['campaign_index_hash']:
                    raise ValueError(f'Campaign hash mismatch: {cid}')
                campaigns.append({'model': model, 'round': round_id, 'campaign_id': cid,
                                  'campaign_path': 'archive/provenance/campaign_indexes/' + cp.name,
                                  'score_index_path': 'archive/provenance/campaign_scores/' + ip.name})
                cells = {}
                for cell in campaign['cells']:
                    for attempt in cell['attempts']:
                        rid = attempt['run_id']
                        cells[rid] = cell
                        rd = Path(attempt['run_directory'])
                        if rid not in attempts:
                            attempts[rid] = {'run_id': rid, 'status': attempt['status'],
                                             'path': 'runs/' + rid}
                            if not rd.is_dir():
                                raise FileNotFoundError(f'Missing attempt: {rid}')
                            for f in sorted(rd.rglob('*')):
                                if f.is_file() and f.name != '.DS_Store' and '__pycache__' not in f.parts:
                                    add('runs/' + rid + '/' + f.relative_to(rd).as_posix(), f)
                for record in index['runs']:
                    rid = record['run_id']
                    sp = Path(record['score_file'])
                    if digest(sp.read_bytes()) != record['score_file_hash']:
                        raise ValueError(f'Score hash mismatch: {rid}')
                    score_name = 'scores/' + rid + '.json'
                    add(score_name, sp)
                    cell = cells[rid]
                    rows.append({'model': model, 'round': round_id, 'campaign_id': cid,
                                 'run_id': rid, 'run_path': 'runs/' + rid, 'score_path': score_name,
                                 'incident': cell['incident_id'], 'profile': cell['instruction_profile'],
                                 'variant': cell.get('evidence_variant', 'BASE')})
    if len(rows) != 2858 or len({r['run_id'] for r in rows}) != 2858:
        raise ValueError('Unexpected scored cohort')
    # Fail closed for concrete credential patterns. Report member names only.
    patterns = [rb'-----BEGIN (?:RSA |OPENSSH |EC )?PRIVATE KEY-----',
                rb'\b(?:sk-or-v1-|sk-proj-|sk-ant-|ghp_|github_pat_)[A-Za-z0-9_-]{20,}', rb'\b(?:xai-|gsk_)[A-Za-z0-9]{40,}', rb'\bsk-[A-Za-z0-9]{32,}', rb'\bAIza[A-Za-z0-9_-]{30,}']
    suspects = [name for name, data in files.items() if any(re.search(p, data) for p in patterns)]
    if suspects:
        raise ValueError('Credential-like content in: ' + ', '.join(suspects))
    manifest = {'schema_version': 1, 'paper_id': '171', 'analysis_id': 'wp1-five-model-three-round-20260829-v1',
                'models': models, 'rows': rows, 'campaigns': campaigns,
                'attempts': list(attempts.values()),
                'files': {n: digest(v) for n, v in sorted(files.items())},
                'path_policy': 'Archive bytes retain original absolute paths as provenance; use only relative index mappings.'}
    files['index.json'] = (json.dumps(manifest, indent=2, sort_keys=True) + '\n').encode()
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open('wb') as out, gzip.GzipFile(fileobj=out, mode='wb', mtime=0, filename='') as gz:
        with tarfile.open(fileobj=gz, mode='w') as tar:
            for name, data in sorted(files.items()):
                info = tarfile.TarInfo(name)
                info.size, info.mode, info.mtime = len(data), 0o644, 0
                tar.addfile(info, io.BytesIO(data))
    print(f'Packed {len(rows)} scored runs, {len(attempts)} attempts, {len(files)} files; {destination.stat().st_size / 1048576:.2f} MiB')
    destination.with_suffix(destination.suffix + '.sha256').write_text(digest(destination.read_bytes()) + '  ' + destination.name + '\n')

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace', type=Path, required=True)
    parser.add_argument('--output', type=Path, default=Path(__file__).with_name('experiment1.tar.gz'))
    args = parser.parse_args()
    build(args.workspace.resolve(), args.output.resolve())
