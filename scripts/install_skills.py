#!/usr/bin/env python3
"""Explicit, reversible skill installation. Standard library; preview unless --apply."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import uuid

ROOT = Path(__file__).resolve().parents[1]
CLIENTS = ('codex', 'claude', 'reasonix', 'zcode')
SKILLS = {'agents-talk': ('SKILL.md',), 'agents-talk-plan': ('SKILL.md', 'prompt-format.md')}
MARKER = '.agents-talk-install.json'


def digest(data):
    return hashlib.sha256(data).hexdigest()


def command_text(parts):
    return subprocess.list2cmdline(parts) if os.name == 'nt' else shlex.join(parts)


def default_targets():
    home = Path.home()
    targets = {'codex': Path(os.environ.get('CODEX_HOME', str(home / '.codex'))) / 'skills',
               'claude': home / '.claude' / 'skills', 'zcode': home / '.zcode' / 'skills'}
    # Reasonix location is configurable. Only Windows has a verified local convention here.
    if os.name == 'nt' and os.environ.get('APPDATA'):
        targets['reasonix'] = Path(os.environ['APPDATA']) / 'reasonix' / 'skills'
    return targets


def resources(project, client, data_dir, config_path):
    command = [sys.executable, str(project / 'hub.py'), '--data-dir', str(data_dir), '--config', str(config_path)]
    location = ('# Local Agents Talk location\n\n'
                f'Project: {project}\nPython: {sys.executable}\nData: {data_dir}\n'
                f'Config: {config_path}\nProtocol: {project / "PROTOCOL.md"}\n\n'
                'Append the subcommand and its arguments to this exact command prefix:\n\n'
                f'```text\n{command_text(command)}\n```\n'
                'Keep data/config arguments in every read, post, listen and bind call.\n')
    result = {}
    for name, files in SKILLS.items():
        texts = {f: (project / 'skills' / name / f).read_text(encoding='utf-8-sig') for f in files}
        if client == 'claude' and name == 'agents-talk':
            text = texts['SKILL.md']
            end = text.index('\n---', 3)
            hook = command_text([*command, 'stop-hook'])
            text = text[:end] + ('\nhooks:\n  Stop:\n    - hooks:\n        - type: command\n'
                                '          command: ' + json.dumps(hook, ensure_ascii=False) +
                                '\n          timeout: 10') + text[end:]
            text += ('\n## Claude 原生窗口绑定\n\n'
                     '当前原生会话 ID：`${CLAUDE_SESSION_ID}`。报到后使用 location 中的命令前缀，'
                     '执行 `bind --agent <本窗口Claude实例ID> --session <看板会话> --client-session <此原生ID>`。'
                     '只绑定当前窗口；变量未展开时报告无法绑定，不填写猜测值。退出按协议 leave，解除绑定加 --detach。\n')
            texts['SKILL.md'] = text
        texts['location.md'] = location
        result[name] = {f: t.encode('utf-8') for f, t in texts.items()}
    return result


def install(project, client, target, data_dir, config_path, apply=False, uninstall=False, replace_project=False):
    project, target = project.resolve(), target.resolve()
    # Never install into or remove the maintained source folders.
    if target == project / 'skills' or target.is_relative_to(project / 'skills'):
        raise ValueError('Target must not be the maintained project skills directory')
    desired = {} if uninstall else resources(project, client, data_dir, config_path)
    report = []
    for name in SKILLS:
        folder = target / name
        if folder.is_symlink() or (folder.exists() and folder.resolve() != folder):
            raise ValueError(f'Refusing linked skill folder: {folder}')
        marker = folder / MARKER
        if marker.is_symlink(): raise ValueError(f'Refusing linked installation manifest: {marker}')
        previous = json.loads(marker.read_text(encoding='utf-8')) if marker.exists() else None
        if previous is not None and (not isinstance(previous, dict) or previous.get('schema') != 1 or not isinstance(previous.get('files'), dict)):
            raise ValueError(f'Invalid installation manifest: {marker}')
        if previous and (previous.get('project') != str(project) or previous.get('client') != client):
            if uninstall or not replace_project: raise ValueError(f'{folder} belongs to another project/client; inspect it before --replace-project')
        if uninstall:
            if not previous:
                report.append({'skill': name, 'action': 'skip_unmanaged', 'path': str(folder)})
                continue
            remaining = {}
            for filename, expected in previous['files'].items():
                if filename not in (*SKILLS[name], 'location.md'): raise ValueError('Invalid installation manifest file')
                path = folder / filename
                if not path.exists(): continue
                if path.is_symlink() or digest(path.read_bytes()) != expected:
                    remaining[filename] = expected
                    report.append({'path': str(path), 'action': 'keep_modified'})
                else:
                    report.append({'path': str(path), 'action': 'remove_owned'})
                    if apply: path.unlink()
            if apply:
                if remaining:
                    previous['files'] = remaining
                    marker.write_text(json.dumps(previous, ensure_ascii=False, indent=2), encoding='utf-8')
                else:
                    marker.unlink()
                    if not any(folder.iterdir()): folder.rmdir()
            continue
        hashes = {}
        backup = project / '.backups' / 'skills' / (datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S') + '-' + uuid.uuid4().hex[:8]) / client / name
        for filename, content in desired[name].items():
            path = folder / filename
            if path.is_symlink(): raise ValueError(f'Refusing linked skill resource: {path}')
            hashes[filename] = digest(content)
            old = path.read_bytes() if path.exists() else None
            action = 'unchanged' if old == content else 'backup_and_update' if old is not None else 'create'
            report.append({'path': str(path), 'action': action})
            if apply and old != content:
                if old is not None:
                    backup.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(path, backup / filename)
                folder.mkdir(parents=True, exist_ok=True)
                path.write_bytes(content)
        if apply:
            manifest = {'schema': 1, 'project': str(project), 'client': client, 'files': hashes}
            marker.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    return report


def main():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'): stream.reconfigure(encoding='utf-8', errors='backslashreplace')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--clients', nargs='+', choices=CLIENTS, required=True)
    parser.add_argument('--target', action='append', default=[], metavar='CLIENT=SKILL_ROOT')
    parser.add_argument('--data-dir', type=Path, default=Path(os.environ.get('AGENTS_TALK_DATA', str(ROOT))))
    parser.add_argument('--config', type=Path, default=Path(os.environ.get('AGENTS_TALK_CONFIG', str(ROOT / 'config.json'))))
    parser.add_argument('--apply', action='store_true', help='Actually write; omitted means preview only')
    parser.add_argument('--uninstall', action='store_true', help='Only remove unmodified files owned by this installation')
    parser.add_argument('--replace-project', action='store_true', help='Rebind these skill names to this project after inspecting the old installation')
    args = parser.parse_args()
    try:
        targets = default_targets()
        for value in args.target:
            client, sep, path = value.partition('=')
            if not sep or client not in args.clients or not path: raise ValueError('Use --target CLIENT=SKILL_ROOT for a selected client')
            targets[client] = Path(path)
        selected = list(dict.fromkeys(args.clients))
        for client in selected:
            if client not in targets: raise ValueError(f'Provide --target {client}=<your skill root> on this platform')
        if len({os.path.normcase(str(targets[c].resolve())) for c in selected}) != len(selected):
            raise ValueError('Each client needs its own skill root')
        cfg = args.config.resolve()
        if cfg == ROOT / 'config.json' and not cfg.exists(): cfg = ROOT / 'config.example.json'
        if not args.uninstall and not cfg.is_file(): raise ValueError('Custom config file does not exist')
        # Complete validation/preview of every selected target before any write.
        reports = {c: install(ROOT, c, targets[c], args.data_dir.resolve(), cfg, False,
                              args.uninstall, args.replace_project) for c in selected}
        if args.apply:
            reports = {c: install(ROOT, c, targets[c], args.data_dir.resolve(), cfg, True,
                                  args.uninstall, args.replace_project) for c in selected}
        print(json.dumps({'applied': args.apply, 'clients': reports,
                          'note': 'File installation does not verify discovery or execution inside native clients.'}, ensure_ascii=False, indent=2))
        return 0
    except (OSError, ValueError, KeyError, TypeError) as e:
        print('Skill installation failed: ' + str(e), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
