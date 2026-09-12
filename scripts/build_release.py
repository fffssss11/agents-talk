#!/usr/bin/env python3
"""Build a source-only release using an exact, reviewed allowlist. Never traverse runtime data."""
import argparse
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import re
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN = {'config.json', 'board.jsonl', '.hub.lock', '.seen', '.presence', '.listeners',
             '.bindings', 'uploads', 'workspace', '.runtime', '.backups', 'dist', 'node_modules',
             '__pycache__', '.git', '.env', 'python-path.txt', '.agents-talk-install.json'}


def inventory(root):
    root = root.resolve()
    paths = json.loads((root / 'release-files.json').read_text(encoding='utf-8'))
    if not isinstance(paths, list) or not paths or len(paths) != len(set(paths)):
        raise ValueError('Release allowlist must be a nonempty array of unique relative paths')
    entries = {}
    for name in sorted(paths):
        relative = PurePosixPath(name)
        if not isinstance(name, str) or relative.is_absolute() or '..' in relative.parts or '\\' in name or ':' in name or str(relative) != name:
            raise ValueError('Unsafe release path: ' + str(name))
        if any(p in FORBIDDEN or p.startswith('.env.') for p in relative.parts):
            raise ValueError('Private/runtime file in allowlist: ' + name)
        path = root / name
        if not path.is_file() or path.resolve() != path:
            raise ValueError('Missing or linked source: ' + name)
        content = path.read_bytes()
        if path.suffix.lower() not in ('.png', '.jpg'):
            text = content.decode('utf-8-sig')
            personal = [str(Path.home()), str(root)]
            normalized = text.replace('\\', '/').lower()
            if any(str(p).replace('\\', '/').lower() in normalized for p in personal):
                raise ValueError('Local absolute path in source: ' + name)
            user_component = r"[^/\\\s<>()\[\]'\"|$%]+"
            home_pattern = r"(?:[A-Za-z]:/Users/|/Users/|/home/)" + user_component + r"/"
            if re.search(home_pattern, re.sub(r'/+', '/', text.replace('\\', '/')), re.IGNORECASE):
                raise ValueError('Personal home path in source: ' + name)
            if re.search(r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----|\bgh[pousr]_[A-Za-z0-9]{30,}|\bsk-[A-Za-z0-9_-]{30,}', text):
                raise ValueError('Possible credential in source: ' + name)
        entries[name] = content
    return entries


def build(root, output=None, allow_unlicensed=False):
    entries = inventory(root)
    version = entries['VERSION'].decode().strip()
    if not re.fullmatch(r'\d+\.\d+\.\d+(?:-[a-z0-9.]+)?', version): raise ValueError('Invalid VERSION')
    package = json.loads(entries['package.json'])
    lockfile = json.loads(entries['package-lock.json'])
    if package['version'] != version or lockfile['version'] != version or lockfile['packages']['']['version'] != version:
        raise ValueError('VERSION, package.json and lockfile versions must agree')
    licensed = 'LICENSE' in entries
    if licensed and (len(entries['LICENSE'].strip()) < 100 or package.get('license') in (None, '', 'UNLICENSED')):
        raise ValueError('Complete LICENSE and consistent package license metadata are required')
    if licensed and lockfile['packages'][''].get('license') != package.get('license'):
        raise ValueError('Package and lockfile license metadata must agree')
    if not licensed and not allow_unlicensed:
        raise ValueError('No LICENSE selected. Confirm it before publishing; --allow-unlicensed creates a private review candidate only.')
    files = [{'path': p, 'bytes': len(b), 'sha256': hashlib.sha256(b).hexdigest()} for p, b in entries.items()]
    manifest = {'version': version, 'license_status': 'included' if licensed else 'pending_owner_choice', 'files': files}
    if output is None: return manifest
    output = Path(output).resolve()
    checksum = output.with_name(output.name + '.sha256')
    if output.exists() or checksum.exists(): raise ValueError('Refusing to overwrite an existing release or checksum')
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        all_entries = {**entries, 'SOURCE-MANIFEST.json': (json.dumps(manifest, ensure_ascii=False, indent=2) + '\n').encode()}
        for name, content in sorted(all_entries.items()):
            info = zipfile.ZipInfo('agents-talk-' + version + '/' + name, date_time=(2020, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            archive.writestr(info, content)
    payload = buffer.getvalue()
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open('xb') as f: f.write(payload)
    with checksum.open('x', encoding='utf-8') as f: f.write(hashlib.sha256(payload).hexdigest() + '  ' + output.name + '\n')
    return {**manifest, 'archive': str(output), 'bytes': len(payload), 'checksum': str(checksum)}


def main():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'): stream.reconfigure(encoding='utf-8', errors='backslashreplace')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--check', action='store_true', help='Validate the exact source allowlist without writing an archive')
    parser.add_argument('--allow-unlicensed', action='store_true', help='Private candidate only; cannot be represented as an open-source release')
    args = parser.parse_args()
    try:
        version = (ROOT / 'VERSION').read_text().strip()
        out = None if args.check else args.output or ROOT / 'dist' / ('agents-talk-' + version + '.zip')
        result = build(ROOT, out, args.allow_unlicensed)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (OSError, ValueError, KeyError, TypeError) as e:
        print('Release rejected: ' + str(e), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
