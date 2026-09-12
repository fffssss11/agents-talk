"""Read-only local diagnostics. No network requests, writes, or agent heartbeats."""
import os
from pathlib import Path
import sys


def diagnose(hub):
    checks = []
    def check(name, fn):
        try:
            detail = fn()
            checks.append({'name': name, 'ok': True, 'detail': detail})
        except (OSError, ValueError, KeyError, TypeError, AttributeError) as e:
            checks.append({'name': name, 'ok': False, 'detail': str(e)})

    def python_version():
        if sys.version_info < (3, 10): raise ValueError('Requires Python 3.10 or newer')
        return sys.version.split()[0]

    def resources():
        required = ['web/index.html', 'web/app.js', 'web/style.css', 'web/observatory.css',
                    'PROTOCOL.md', 'config.example.json', 'skills/agents-talk/SKILL.md',
                    'skills/agents-talk-plan/SKILL.md']
        missing = [p for p in required if not (hub.ROOT / p).is_file()]
        if missing: raise ValueError('Missing: ' + ', '.join(missing))
        return 'All required runtime resources present'

    def history():
        # One immutable read; never creates the normal transaction/heartbeat files.
        msgs = hub.load()
        cfg = hub.config()
        sessions = hub.sessions(msgs, cfg)
        for sid in sessions: hub.derive(msgs, cfg, sid)
        return {'events': len(msgs), 'sessions': len(sessions)}

    def directory():
        p = hub.DATA
        while not p.exists() and p != p.parent: p = p.parent
        if not p.is_dir() or not os.access(p, os.W_OK): raise ValueError('Data directory ancestor is not writable')
        return 'Permission precheck only; the filesystem may still reject a later write'

    check('python', python_version)
    check('configuration', lambda: {'lead': hub.config()['lead']})
    check('resources', resources)
    check('data_directory', directory)
    check('event_log', history)
    return {'ok': all(c['ok'] for c in checks), 'app_version': hub.VERSION,
            'python': sys.executable, 'root': str(hub.ROOT), 'data': str(hub.DATA),
            'config': str(hub.CONFIG), 'checks': checks,
            'notes': ['Local paths are included; redact before sharing.',
                      'This does not verify native client skill discovery, model access, or media tools.',
                      'Stop writers before diagnosing a potentially damaged event log.']}
