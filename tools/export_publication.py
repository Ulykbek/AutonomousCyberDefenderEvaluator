#!/usr/bin/env python3
"""Export current tracked publication files without Git history or local research files."""
from __future__ import annotations
import argparse, gzip, hashlib, io, json, re, subprocess, tarfile
from pathlib import Path

PATTERNS = [rb'-----BEGIN (?:RSA |OPENSSH |EC )?PRIVATE KEY-----',
            rb'\b(?:sk-or-v1-|sk-proj-|sk-ant-|ghp_|github_pat_)[A-Za-z0-9_-]{20,}', rb'\b(?:xai-|gsk_)[A-Za-z0-9]{40,}', rb'\bsk-[A-Za-z0-9]{32,}', rb'\bAIza[A-Za-z0-9_-]{30,}']


def export(repo, destination, role):
    # The staged/tracked file list is explicit: untracked local research is never included.
    names = subprocess.check_output(['git', '-C', str(repo), 'ls-files', '-z']).decode().split('\0')
    content = {}
    for name in sorted(filter(None, names)):
        p = Path(name)
        if '__pycache__' in p.parts or p.suffix == '.pyc' or p.name == '.DS_Store':
            continue
        if p.parts[0] in {'experiment_runs', 'experiment_results', 'analysis_results', 'replication-output', 'release-dist'}:
            continue
        if role == 'agent' and (p.parts[0].startswith('experiment_preflight') or p.parts[0] in {'logs', 'reports'}):
            continue
        if 'cyberbroker_v3' in name.lower() or name in {'PhD_Proposal_Bounded_Autonomy.docx', 'docs/WP1_CYBERBROKER_EXPERIMENT_REPRODUCTION.md', 'docs/WP1_EXPERIMENT_SIMPLE_EXPLANATION.md'}:
            continue
        if (p.name.startswith('.env') and p.name != '.env.example') or p.suffix in {'.key', '.pem'}:
            raise ValueError('Unexpected sensitive filename in export: ' + name)
        f = repo / name
        if f.is_symlink():
            raise ValueError('Symlink is not exported: ' + name)
        if not f.is_file():
            raise ValueError('Tracked file missing: ' + name)
        data = f.read_bytes()
        if any(re.search(pattern, data) for pattern in PATTERNS):
            raise ValueError('Credential-like content in export member: ' + name)
        content[name] = data
    require = 'README.md' if role == 'agent' else 'publication/side2026/experiment1.tar.gz'
    if require not in content:
        raise ValueError('Publication files must be staged/tracked before export: ' + require)
    archive = destination / (repo.name + '-paper171-v1.0.0.tar.gz')
    with archive.open('wb') as raw, gzip.GzipFile(fileobj=raw, mode='wb', mtime=0, filename='') as gz:
        with tarfile.open(fileobj=gz, mode='w') as tar:
            for name, data in content.items():
                info = tarfile.TarInfo(repo.name + '/' + name)
                info.size, info.mode, info.mtime = len(data), 0o644, 0
                tar.addfile(info, io.BytesIO(data))
    return {'repository': repo.name,
            'source_head': subprocess.check_output(['git', '-C', str(repo), 'rev-parse', 'HEAD'], text=True).strip(),
            'archive': archive.name, 'sha256': hashlib.sha256(archive.read_bytes()).hexdigest(),
            'files': {n: hashlib.sha256(v).hexdigest() for n, v in content.items()},
            'history_included': False, 'license_status': 'See LICENSING.md; no public release implied'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--agent-repo', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError('Output already exists; choose a new directory')
    args.output.mkdir(parents=True)
    evaluator = Path(__file__).resolve().parents[1]
    manifest = [export(args.agent_repo.resolve(), args.output, 'agent'), export(evaluator, args.output, 'evaluator')]
    (args.output / 'MANIFEST.json').write_text(json.dumps(manifest, indent=2) + '\n')
    (args.output / 'SHA256SUMS.txt').write_text(''.join(x['sha256'] + '  ' + x['archive'] + '\n' for x in manifest))
    print('Created two history-free archives and checksums in', args.output)

if __name__ == '__main__':
    main()
