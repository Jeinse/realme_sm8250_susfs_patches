#!/usr/bin/env python3
"""Generate reviewed-source candidates. This program never builds a kernel."""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
CORE_FILES = ('fs/susfs.c', 'include/linux/susfs.h', 'include/linux/susfs_def.h')
ADAPTER_FILES = ('config/sources.json', 'compat/entropy-1.7-fixups.patch',
                 'compat/entropy-1.7-rejections.json', 'scripts/sync_jack.py',
                 'scripts/publish_candidate.py', 'susfs_inline_hook_patches.sh')
SHA = re.compile(r'[0-9a-f]{40}')


class StopSync(RuntimeError):
    pass


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def load(path: Path):
    return json.loads(path.read_text())


def save(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + '\n')


def command(args, cwd=None, *, input=None, allowed=(0,), log=None):
    env = os.environ.copy()
    env['GIT_TERMINAL_PROMPT'] = '0'
    result = subprocess.run([str(x) for x in args], cwd=cwd, input=input,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            env=env, timeout=1200)
    if log:
        Path(log).parent.mkdir(parents=True, exist_ok=True)
        Path(log).write_bytes(result.stdout + result.stderr)
    if result.returncode not in allowed:
        detail = (result.stdout + result.stderr).decode(errors='replace')[-12000:]
        raise StopSync(f'{args[0]} failed ({result.returncode}):\n{detail}')
    return result


def git(repo: Path, *args, **kw):
    return command(['git', '-C', repo, *args], **kw)


def safe_path(path: str) -> str:
    p = PurePosixPath(path)
    if not path or p.is_absolute() or '..' in p.parts or str(p) != path or '\\' in path:
        raise StopSync(f'Unsafe source path: {path!r}')
    return path


def patch_paths(data: bytes):
    result = []
    for line in data.decode().splitlines():
        if line.startswith('diff --git '):
            m = re.fullmatch(r'diff --git a/(\S+) b/(\S+)', line)
            if not m or m[1] != m[2]:
                raise StopSync('Renamed/quoted patch paths require review')
            result.append(safe_path(m[1]))
    if not result or len(result) != len(set(result)):
        raise StopSync('Missing or duplicated patch file sections')
    return result


def rejected_blocks(text: str):
    """Ignore line-number drift, but compare every context/deleted/added byte."""
    result = []
    for m in re.finditer(r'^@@[^\n]*\n((?:(?!^@@)[\s\S])*)', text, re.M):
        result.append(digest(m[1].encode()))
    return result


def verify_rejections(kernel: Path, expected):
    actual = []
    rejects = sorted(kernel.rglob('*.rej'))
    for p in rejects:
        name = str(p.relative_to(kernel))[:-4]
        actual.extend((name, sha) for sha in rejected_blocks(p.read_text()))
    wanted = [(x['path'], x['body_sha256']) for x in expected]
    if Counter(actual) != Counter(wanted):
        missing = list((Counter(wanted) - Counter(actual)).elements())
        unknown = list((Counter(actual) - Counter(wanted)).elements())
        raise StopSync(f'Known compatibility blocks changed. Manual review required. '
                       f'Missing: {missing}; unknown: {unknown}')
    return rejects


def url(repository: str):
    if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', repository):
        raise StopSync('Invalid repository name')
    return 'https://github.com/' + repository + '.git'


def source(cache: Path, name: str, repository: str, sha: str, override=None):
    if not SHA.fullmatch(sha):
        raise StopSync('Sources must be full commit SHAs')
    dest = cache / name
    remote = str(Path(override).resolve()) if override else url(repository)
    if not (dest / '.git').exists():
        dest.mkdir(parents=True, exist_ok=True)
        command(['git', 'init', '--quiet', dest])
        git(dest, 'remote', 'add', 'origin', remote)
    current = git(dest, 'remote', 'get-url', 'origin').stdout.decode().strip()
    if current != remote:
        raise StopSync(f'Unexpected remote for cache {name}')
    exists = git(dest, 'cat-file', '-e', sha + '^{commit}', allowed=(0, 128))
    if exists.returncode:
        git(dest, 'config', 'remote.origin.promisor', 'true')
        git(dest, 'config', 'remote.origin.partialclonefilter', 'blob:none')
        git(dest, 'fetch', '--quiet', '--filter=blob:none', '--depth=1', 'origin', sha)
    return dest


def checkout(cache: Path, sha: str, dest: Path, paths):
    git(cache, 'worktree', 'prune')
    git(cache, 'worktree', 'add', '--quiet', '--detach', '--no-checkout', dest, sha)
    patterns = ''.join('/' + safe_path(p) + '\n' for p in sorted(set(paths)))
    git(dest, 'sparse-checkout', 'set', '--no-cone', '--stdin', input=patterns.encode())
    git(dest, 'checkout', '--quiet', '--detach', sha)
    if git(dest, 'status', '--porcelain').stdout:
        raise StopSync('Kernel baseline is not clean')


def inputs(args):
    config = load(ROOT / 'config/sources.json')
    jack = config['jack']
    sha = args.jack_ref
    if not sha:
        remote = str(Path(args.jack_source).resolve()) if args.jack_source else url(jack['repository'])
        line = command(['git', 'ls-remote', remote, 'refs/heads/' + jack['branch']]).stdout.decode().split()
        if len(line) != 2:
            raise StopSync('Cannot resolve the tracked Jack branch')
        sha = line[0]
    repo = source(args.cache, 'jack', jack['repository'], sha, args.jack_source)
    blobs = {p: git(repo, 'show', f'{sha}:{p}').stdout for p in (jack['patch'], jack['inline_script'])}
    hashes = {Path(p).name: digest(data) for p, data in blobs.items()}
    previous = {x['path']: x['sha256'] for x in load(ROOT / 'SOURCE_MANIFEST.json')['inputs']}
    return config, sha, blobs, hashes, hashes != previous


def outputs(**values):
    if os.environ.get('GITHUB_OUTPUT'):
        with open(os.environ['GITHUB_OUTPUT'], 'a') as f:
            for key, value in values.items():
                f.write(f'{key}={str(value).lower() if isinstance(value, bool) else value}\n')


def check(args):
    _, sha, _, hashes, changed = inputs(args)
    changed = changed or args.force
    save(args.out / 'detected.json', {'jack_commit': sha, 'inputs': hashes, 'changed': changed})
    outputs(changed=changed, jack_commit=sha)
    print(json.dumps({'jack_commit': sha, 'changed': changed}), flush=True)


def verify_repository():
    manifest = load(ROOT / 'SOURCE_MANIFEST.json')
    patch = ROOT / safe_path(manifest['output']['path'])
    if digest(patch.read_bytes()) != manifest['output']['sha256']:
        raise StopSync('Repository patch checksum mismatch')
    script = (ROOT / 'susfs_inline_hook_patches.sh').read_text()
    if digest(script.encode()) != manifest['entrypoint']['sha256']:
        raise StopSync('Entrypoint checksum does not match the manifest')
    for key, value in [('PATCH_FILE', patch.name), ('PATCH_SHA256', manifest['output']['sha256'])]:
        if f"readonly {key}='{value}'" not in script:
            raise StopSync(f'Entrypoint {key} does not match the manifest')
    command(['bash', '-n', ROOT / 'susfs_inline_hook_patches.sh'])
    patch_paths(patch.read_bytes())
    print('Repository payload, metadata and shell syntax are consistent.', flush=True)


def generate(args):
    config, sha, blobs, hashes, changed = inputs(args)
    if not changed and not args.force:
        print('Tracked file contents are unchanged; no candidate generated.', flush=True)
        outputs(changed=False)
        return
    args.out.mkdir(parents=True, exist_ok=True)
    logs = args.out / 'logs'
    logs.mkdir(exist_ok=True)
    jack = config['jack']
    raw_patch = args.out / 'upstream.patch'
    raw_script = args.out / 'upstream-inline.sh'
    raw_patch.write_bytes(blobs[jack['patch']])
    raw_script.write_bytes(blobs[jack['inline_script']])
    command(['bash', '-n', raw_script], log=logs / 'inline-syntax.log')
    files = patch_paths(raw_patch.read_bytes())
    scope = set(files) | set(config['inline_paths'])
    paths = scope | {'Makefile', 'arch/arm64/configs/vendor/kona-perf_defconfig'}
    kernel_cache = source(args.cache, 'kernel', config['kernel']['repository'], config['kernel']['commit'], args.kernel_source)
    baka = source(args.cache, 'bakasu', config['bakasu']['repository'], config['bakasu']['commit'], args.bakasu_source)
    git(baka, 'sparse-checkout', 'set', '--no-cone', '--stdin', input=b'/kernel/\n')
    git(baka, 'checkout', '--quiet', '--detach', config['bakasu']['commit'])
    if git(baka, 'status', '--porcelain').stdout:
        raise StopSync('BakaSU checkout is modified')
    with tempfile.TemporaryDirectory(prefix='susfs-generate-', dir=args.cache) as temp:
        work = Path(temp)
        kernel = work / 'kernel'
        checkout(kernel_cache, config['kernel']['commit'], kernel, paths)
        result = git(kernel, 'apply', '--reject', '--whitespace=nowarn', raw_patch,
                     allowed=(0, 1), log=logs / 'core-application.log')
        rules = load(ROOT / 'compat/entropy-1.7-rejections.json')
        if len(rules['expected_rejections']) != 7:
            raise StopSync('The reviewed adapter must contain exactly seven blocks')
        rejects = verify_rejections(kernel, rules['expected_rejections'])
        if result.returncode != 1:
            raise StopSync('The reviewed seven-block backport is no longer applicable')
        fixups = ROOT / 'compat/entropy-1.7-fixups.patch'
        git(kernel, 'apply', '--check', fixups, log=logs / 'compat-check.log')
        git(kernel, 'apply', fixups, log=logs / 'compat-application.log')
        for p in rejects:
            p.unlink()
        (kernel / 'drivers/kernelsu').symlink_to(baka / 'kernel', target_is_directory=True)
        command(['bash', '-e', raw_script], cwd=kernel, log=logs / 'inline-application.log')
        if git(baka, 'status', '--porcelain').stdout:
            raise StopSync('Inline script modified the pinned BakaSU source')
        checker = work / 'check.mk'
        checker.write_text(f'srctree := {kernel}\nREPO_NAME := BakaSU\ninclude {baka}/kernel/tools/inline_hook_check.mk\n.PHONY: validate\nvalidate:\n\t@:\n')
        command(['make', '-f', checker, 'validate'], log=logs / 'bakasu-inline-check.log')
        (kernel / 'drivers/kernelsu').unlink()
        if list(kernel.rglob('*.rej')):
            raise StopSync('Rejected source hunks remain')
        core_hashes = {}
        text = raw_patch.read_text()
        for path in CORE_FILES:
            block = text.split(f'diff --git a/{path} b/{path}\n', 1)[1].split('\ndiff --git ', 1)[0]
            if '--- /dev/null\n' not in block:
                raise StopSync(f'{path} must remain a complete upstream new-file section')
            expected = ''.join(x[1:] + '\n' for x in block.splitlines() if x.startswith('+') and not x.startswith('+++')).encode()
            actual = (kernel / path).read_bytes()
            if actual != expected:
                raise StopSync(f'Upstream source was not preserved verbatim: {path}')
            core_hashes[path] = digest(actual)
        status = git(kernel, 'ls-files', '--others', '--exclude-standard').stdout.decode().splitlines()
        for path in status:
            if safe_path(path) not in scope:
                raise StopSync(f'Unexpected generated file: {path}')
            git(kernel, 'add', '-N', '--', path)
        changed_files = git(kernel, 'diff', '--name-only', 'HEAD').stdout.decode().splitlines()
        if not changed_files or not set(changed_files) <= scope:
            raise StopSync('Generated changes exceed the reviewed source scope')
        data = git(kernel, 'diff', '--full-index', '--binary', '--no-ext-diff', 'HEAD', '--', *changed_files).stdout
        final = args.out / 'candidate.patch'
        final.write_bytes(data)
        verify = work / 'verify'
        checkout(kernel_cache, config['kernel']['commit'], verify, paths)
        git(verify, 'apply', '--check', final, log=logs / 'final-apply-check.log')
        git(verify, 'apply', '--whitespace=nowarn', final, log=logs / 'final-application.log')
        git(verify, 'apply', '--reverse', '--check', final, log=logs / 'final-reverse-check.log')
        for path in changed_files:
            if (kernel / path).read_bytes() != (verify / path).read_bytes():
                raise StopSync(f'Clean reapplication differs: {path}')
        version = re.search(r'^#define SUSFS_VERSION "v([0-9]+\.[0-9]+\.[0-9]+)"$', (kernel / 'include/linux/susfs.h').read_text(), re.M)
        if not version:
            raise StopSync('Unknown SUSFS version format')
        adapter_hashes = {p: digest((ROOT / p).read_bytes()) for p in ADAPTER_FILES}
        candidate_key = digest(json.dumps({'inputs': hashes, 'adapter': adapter_hashes}, sort_keys=True).encode())[:10]
        report = {'schema': 1, 'base_repository_commit': git(ROOT, 'rev-parse', 'HEAD').stdout.decode().strip(),
                  'kernel': config['kernel'], 'bakasu': config['bakasu'],
                  'jack': {'repository': jack['repository'], 'branch': jack['branch'], 'commit': sha},
                  'inputs': [{'path': p, 'sha256': hashes[p]} for p in sorted(hashes)],
                  'patch': {'path': f'patches/entropy-1.7-susfs-{version[1]}-jack.patch', 'sha256': digest(data),
                            'files': len(changed_files)},
                  'adapter_hashes': adapter_hashes, 'core_source_sha256': core_hashes,
                  'changed_files': changed_files, 'branch': f'candidate/jack-{sha[:12]}-{candidate_key}',
                  'checks': {'clean_apply_check': True, 'clean_apply': True, 'reverse_check': True,
                             'identical_result_files': len(changed_files), 'bakasu_inline_check': True,
                             'upstream_core_verbatim': True, 'known_compatibility_blocks': 7},
                  'manual_validation': {'full_kernel_build': 'pending', 'device_flash_test': 'pending'},
                  'automatic_compilation': False}
        save(args.out / 'report.json', report)
    outputs(changed=True, jack_commit=sha)
    print(f'Candidate generated: {report["branch"]}; manual build and device tests are pending.', flush=True)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('command', choices=['check', 'generate', 'verify-repository'])
    p.add_argument('--cache', type=Path, default=Path(tempfile.gettempdir()) / 'susfs-sync-cache')
    p.add_argument('--out', type=Path, default=Path('candidate-output'))
    p.add_argument('--jack-ref', default='')
    p.add_argument('--force', action='store_true')
    p.add_argument('--jack-source')
    p.add_argument('--kernel-source')
    p.add_argument('--bakasu-source')
    args = p.parse_args()
    args.cache = args.cache.resolve()
    args.out = args.out.resolve()
    args.cache.mkdir(parents=True, exist_ok=True)
    try:
        {'check': check, 'generate': generate, 'verify-repository': lambda _: verify_repository()}[args.command](args)
    except (StopSync, subprocess.TimeoutExpired, ValueError, KeyError, OSError, IndexError) as error:
        print(f'STOPPED: {error}', file=sys.stderr, flush=True)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
