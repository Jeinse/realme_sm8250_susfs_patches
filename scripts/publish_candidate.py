#!/usr/bin/env python3
"""Publish source-checked candidate branches and draft PRs, never stable refs."""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from sync_jack import ADAPTER_FILES, StopSync, patch_paths

SHA = re.compile(r'[0-9a-f]{40}')
HASH = re.compile(r'[0-9a-f]{64}')


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def wrapper(template, patch_name, patch_hash):
    if not re.fullmatch(r'entropy-1\.7-susfs-\d+\.\d+\.\d+-jack\.patch', patch_name) or not HASH.fullmatch(patch_hash):
        raise ValueError('Invalid candidate payload metadata')
    for key, value in [('PATCH_FILE', patch_name), ('PATCH_SHA256', patch_hash)]:
        template, count = re.subn(rf"^readonly {key}='[^']*'$", f"readonly {key}='{value}'", template, flags=re.M)
        if count != 1:
            raise ValueError('Entrypoint template changed; review required')
    return template


def candidate_files(directory, base_sha):
    directory = directory.resolve()
    for name in ['report.json', 'candidate.patch']:
        path = directory / name
        if path.is_symlink() or not path.is_file():
            raise ValueError('Candidate must contain regular files')
    report = json.loads((directory / 'report.json').read_text())
    config = json.loads((ROOT / 'config/sources.json').read_text())
    if report['schema'] != 1 or report['base_repository_commit'] != base_sha:
        raise ValueError('Candidate was not generated from the checked out repository revision')
    if report['kernel'] != config['kernel'] or report['bakasu'] != config['bakasu']:
        raise ValueError('Candidate changed pinned source versions')
    if report['jack']['repository'] != config['jack']['repository'] or not SHA.fullmatch(report['jack']['commit']):
        raise ValueError('Unexpected upstream source')
    if not re.fullmatch(r'candidate/jack-[0-9a-f]{12}-[0-9a-f]{10}', report['branch']):
        raise ValueError('Only candidate branches may be published')
    for name, expected in report['adapter_hashes'].items():
        if name not in ADAPTER_FILES:
            raise ValueError('Unexpected adapter input')
        if sha256((ROOT / name).read_bytes()) != expected:
            raise ValueError('Candidate adapter differs from the publisher checkout')
    if set(report['adapter_hashes']) != set(ADAPTER_FILES):
        raise ValueError('Missing adapter input hashes')
    checks = report['checks']
    if any(checks.get(k) is not True for k in ['clean_apply_check', 'clean_apply', 'reverse_check', 'bakasu_inline_check', 'upstream_core_verbatim']):
        raise ValueError('Candidate source checks did not pass')
    if report.get('automatic_compilation') is not False or report['manual_validation'] != {'full_kernel_build': 'pending', 'device_flash_test': 'pending'}:
        raise ValueError('Candidate must remain pending manual validation')
    patch_path = report['patch']['path']
    if not re.fullmatch(r'patches/entropy-1\.7-susfs-\d+\.\d+\.\d+-jack\.patch', patch_path):
        raise ValueError('Invalid output patch path')
    patch = (directory / 'candidate.patch').read_bytes()
    if sha256(patch) != report['patch']['sha256']:
        raise ValueError('Candidate patch checksum mismatch')
    if patch_paths(patch) != report['changed_files']:
        raise ValueError('Candidate patch paths differ from the source report')
    expected_inputs = {Path(config['jack']['patch']).name, Path(config['jack']['inline_script']).name}
    if {x['path'] for x in report['inputs']} != expected_inputs or len(report['inputs']) != 2 or any(not HASH.fullmatch(x['sha256']) for x in report['inputs']):
        raise ValueError('Candidate upstream input hashes are incomplete')
    if report['patch']['files'] != len(report['changed_files']) or report['checks']['identical_result_files'] != len(report['changed_files']):
        raise ValueError('Inconsistent candidate file count')
    script = wrapper((ROOT / 'susfs_inline_hook_patches.sh').read_text(), Path(patch_path).name, sha256(patch)).encode()
    manifest = {'kernel': {**report['kernel'], 'branch': 'Entropy-1.7'}, 'jack': report['jack'],
                'bakasu_check': report['bakasu'], 'inputs': report['inputs'],
                'output': {'path': patch_path, 'sha256': sha256(patch), 'files': len(report['changed_files'])},
                'verification': {**checks, 'compiled_changed_c_files': 0,
                                 'full_kernel_link': False, 'full_bakasu_build': False,
                                 'device_boot_test': False, 'manual_validation_required': True},
                'entrypoint': {'path': 'susfs_inline_hook_patches.sh', 'sha256': sha256(script),
                               'kind': 'verified merged-patch applicator'},
                'manual_validation': report['manual_validation']}
    encode = lambda value: (json.dumps(value, indent=2, ensure_ascii=False) + '\n').encode()
    return report, {patch_path: patch, 'susfs_inline_hook_patches.sh': script,
                    'SOURCE_MANIFEST.json': encode(manifest),
                    'verification/candidate-source-checks.json': encode(report)}


def github(repository, route, *, token, method='GET', data=None):
    req = urllib.request.Request('https://api.github.com/repos/' + repository + route,
                                 method=method, data=json.dumps(data).encode() if data is not None else None,
                                 headers={'Authorization': 'Bearer ' + token,
                                          'Accept': 'application/vnd.github+json',
                                          'Content-Type': 'application/json',
                                          'X-GitHub-Api-Version': '2022-11-28',
                                          'User-Agent': 'susfs-candidate-sync'})
    with urllib.request.urlopen(req, timeout=60) as response:
        return json.load(response)


def pr_body(repository, report, commit):
    return f'''Jack upstream has changed. This is a **source-checked candidate**, not a stable release.

- Jack: `{report['jack']['commit']}`
- Kernel baseline: `{report['kernel']['commit']}`
- BakaSU checked: `{report['bakasu']['commit']}`
- Candidate revision to build: `{commit}`
- Patch SHA-256: `{report['patch']['sha256']}`

The generator verified the seven reviewed compatibility blocks, pristine application,
reverse application, identical results, original SUSFS source bytes, and BakaSU inline checks.
**No kernel compilation, full linking or device test was performed automatically.**

## Manual validation before merge

- [ ] Review upstream changes and generated patch (`verification/candidate-source-checks.json`).
- [ ] Configure Android-Builder to use **the candidate revision above**, not `main`.
- [ ] Build the complete kernel with the intended defconfig/toolchain and the recorded BakaSU version.
- [ ] Flash and verify boot, root authorization, modules, filesystem access and suspend/resume.
- [ ] Record the build run URL, device/ROM and results below; mark ready and merge only after testing.

Build run / device / results:

```text
pending
```

See [manual testing instructions](https://github.com/{repository}/blob/{commit}/docs/SYNC_AND_TEST.md).
There is no auto-merge or automatic stable promotion.
'''


def publish(args):
    if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', args.repository) or not SHA.fullmatch(args.base):
        raise ValueError('Invalid repository or base revision')
    report, files = candidate_files(args.directory, args.base)
    api = lambda route, **kw: github(args.repository, route, token=os.environ['GH_TOKEN'], **kw)
    head = api('/git/ref/heads/main')['object']['sha']
    if head != args.base:
        raise ValueError('Stable main changed during generation; rerun against the new revision')
    branch = report['branch']
    try:
        existing = api('/git/ref/heads/' + branch)
    except urllib.error.HTTPError as error:
        if error.code != 404:
            raise
        existing = None
    if existing:
        commit = existing['object']['sha']
        tree = api('/git/trees/' + commit + '?recursive=1')
        entries = {x['path']: x for x in tree['tree'] if x['type'] == 'blob'}
        for path, data in files.items():
            if path == 'verification/candidate-source-checks.json':
                continue
            expected = hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()
            mode = '100755' if path.endswith('.sh') else '100644'
            if entries.get(path, {}).get('sha') != expected or entries[path]['mode'] != mode:
                raise ValueError('Existing candidate has manual changes; it is preserved and will not be overwritten')
        source_report = entries.get('verification/candidate-source-checks.json')
        if not source_report:
            raise ValueError('Existing candidate is missing its source report')
        blob = api('/git/blobs/' + source_report['sha'])
        previous_report = json.loads(base64.b64decode(blob['content']))
        previous_report['base_repository_commit'] = report['base_repository_commit']
        if previous_report != report:
            raise ValueError('Existing candidate source report differs; it will not be overwritten')
        print('Candidate branch already exists; it will not be overwritten.', flush=True)
    else:
        base_tree = api('/git/commits/' + args.base)['tree']['sha']
        entries = []
        for path, content in files.items():
            blob = api('/git/blobs', method='POST', data={'content': base64.b64encode(content).decode(), 'encoding': 'base64'})
            entries.append({'path': path, 'type': 'blob', 'mode': '100755' if path.endswith('.sh') else '100644', 'sha': blob['sha']})
        tree = api('/git/trees', method='POST', data={'base_tree': base_tree, 'tree': entries})
        commit = api('/git/commits', method='POST', data={'message': 'sync: prepare Jack SUSFS candidate ' + report['jack']['commit'][:12], 'tree': tree['sha'], 'parents': [args.base]})['sha']
        # Only a new candidate ref is created. Stable main is never updated here.
        api('/git/refs', method='POST', data={'ref': 'refs/heads/' + branch, 'sha': commit})
    owner = args.repository.split('/')[0]
    prs = api('/pulls?state=all&head=' + owner + ':' + branch)
    link = 'https://github.com/' + args.repository + '/compare/main...' + branch
    if prs:
        link = prs[0]['html_url']
    else:
        try:
            pr = api('/pulls', method='POST', data={'title': 'sync: Jack SUSFS candidate ' + report['jack']['commit'][:12],
                     'head': branch, 'base': 'main', 'draft': True, 'body': pr_body(args.repository, report, commit)})
            link = pr['html_url']
        except urllib.error.HTTPError as error:
            if error.code != 403:
                raise
            print('::warning::GitHub denied automatic PR creation. Candidate branch is preserved; use the comparison link or allow Actions to create pull requests.')
    summary = f'## Source-checked candidate\n\n- Candidate: `{commit}`\n- Review: {link}\n- Full kernel build: **pending manual Android-Builder run**\n- Device test: **pending**\n- Stable main was not changed.\n'
    print(summary, flush=True)
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'], 'a') as f:
            f.write(summary)


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--directory', type=Path, required=True)
    p.add_argument('--repository', required=True)
    p.add_argument('--base', required=True)
    args = p.parse_args()
    try:
        publish(args)
    except (ValueError, StopSync, KeyError, OSError, urllib.error.URLError) as error:
        print(f'Publication stopped: {error}', file=sys.stderr)
        sys.exit(1)
