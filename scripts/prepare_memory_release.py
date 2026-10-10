"""Create a local source manifest/archive, never including Git-ignored secrets/runtime files."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import zipfile
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from scripts.memory_private_paths import is_private_path, require_private_git_clear

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = 'docs/evidence/20261006-memory-local-closeout/source-manifest.json'


def candidates():
    raw = subprocess.check_output(['git', 'ls-files', '--cached', '--others', '--exclude-standard', '-z'], cwd=ROOT)
    names = sorted(set(raw.decode('utf-8').split('\0')) - {''})
    paths = []
    for name in names:
        path = ROOT / name
        if is_private_path(name):
            continue
        if name == MANIFEST:
            continue
        if (path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(ROOT)
                or name.startswith(('releases/', '.git/', '.test-', '.venv/', '.cache/'))
                or (path.name.startswith('.env') and path.name not in ('.env.example', '.env.memory.example'))
                or path.suffix in ('.whl', '.pyc')):
            raise ValueError('unexpected source candidate: ' + name)
        paths.append((name, path))
    for name in ('.env', '.env.memory'):
        subprocess.run(['git', 'check-ignore', '--no-index', '--quiet', name], cwd=ROOT, check=True)
    return paths


def scan(paths):
    patterns = [('provider_key', re.compile(r'\bsk-[A-Za-z0-9_.-]{24,}')),
                ('private_key', re.compile(r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----')),
                ('url_password', re.compile(r'(?:postgres(?:ql)?|https?)://[^\s/:]+:([^\s/@]{8,})@'))]
    findings = []
    placeholders = 0
    for name, path in paths:
        try:
            content = path.read_text(encoding='utf-8')
        except UnicodeError:
            continue
        for kind, pattern in patterns:
            for match in pattern.finditer(content):
                if kind == 'url_password' and (match.group(1) == 'replace_with_local_password'
                                               or re.fullmatch(r'\$\{[A-Z_]+\}', match.group(1))):
                    placeholders += 1
                    continue
                findings.append(dict(path=name, line=content.count('\n', 0, match.start()) + 1, kind=kind))
    # Only paths/line numbers are reported; matching credentials are never echoed.
    if findings:
        raise ValueError(json.dumps(findings, ensure_ascii=False))
    return dict(findings=[],known_placeholder_matches=placeholders,
                scope='Pattern check over export candidates, not a guarantee against every possible secret')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--archive', action='store_true')
    args = parser.parse_args()
    private_git=require_private_git_clear(ROOT)
    paths = candidates()
    security = scan(paths)
    files = {name: dict(sha256=hashlib.sha256(path.read_bytes()).hexdigest(), bytes=path.stat().st_size)
             for name, path in paths}
    report = dict(system='我的记忆系统', internal_name='TraceMemory', candidate='v0-vector-local',
                  purpose='Local review snapshot, not a published or accepted competition version',
                  manifest_self_excluded=True, security=security, private_git=private_git, files=files)
    target = ROOT / MANIFEST
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    if args.archive:
        archive = ROOT / 'releases/my-memory-system-v0-local.zip'
        archive.parent.mkdir(exist_ok=True)
        with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_DEFLATED) as output:
            for name, path in paths:
                output.write(path, name)
            output.write(target, MANIFEST)
        with zipfile.ZipFile(archive) as output:
            assert set(output.namelist()) == set(files) | {MANIFEST}
            assert output.testzip() is None
            for name, item in files.items():
                assert hashlib.sha256(output.read(name)).hexdigest() == item['sha256'], name
        commit = subprocess.run(['git', 'rev-parse', '--verify', 'HEAD'], cwd=ROOT, capture_output=True, text=True)
        status = subprocess.check_output(['git', 'status', '--porcelain'], cwd=ROOT, text=True)
        info = dict(archive=str(archive), source_files=len(files), archive_bytes=archive.stat().st_size,
                    archive_sha256=hashlib.sha256(archive.read_bytes()).hexdigest(), security=security,
                    git_head=commit.stdout.strip() if commit.returncode == 0 else None, git_worktree_clean=not status.strip())
        (archive.parent/'release-info.json').write_text(json.dumps(info,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps(info, ensure_ascii=False))
    else:
        print(json.dumps(dict(manifest=str(target), source_files=len(files), security=security), ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
