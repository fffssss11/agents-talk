"""Portable source release, installer and security checks. No real client or board mutations."""
import hashlib
import http.client
import importlib.util
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('release_builder', ROOT / 'scripts/build_release.py')
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)


class DistributionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='agents-talk-distribution-')
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.project = self.base / 'fresh source 空格'
        self.project.mkdir()
        for name, content in release.inventory(ROOT).items():
            p = self.project / name
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(content)
        self.env = {k: v for k, v in os.environ.items() if not k.startswith('AGENTS_TALK_')}
        self.env.update(PYTHONUTF8='1', PYTHONDONTWRITEBYTECODE='1', AGENTS_TALK_PYTHON=sys.executable)

    def run_cli(self, *args, expected=0):
        result = subprocess.run([sys.executable, str(self.project / 'hub.py'), *args],
                                cwd=self.base, env=self.env, capture_output=True, encoding='utf-8', timeout=20)
        self.assertEqual(result.returncode, expected, result.stderr + result.stdout)
        return result

    def install(self, *args, expected=0):
        result = subprocess.run([sys.executable, str(self.project / 'scripts/install_skills.py'),
                                 '--clients', 'codex', 'claude',
                                 '--target', 'codex=' + str(self.base / 'codex skills'),
                                 '--target', 'claude=' + str(self.base / 'claude skills'), *args],
                                cwd=self.base, env=self.env, capture_output=True, encoding='utf-8', timeout=20)
        self.assertEqual(result.returncode, expected, result.stderr + result.stdout)
        return result

    def test_doctor_is_read_only_and_works_without_local_config(self):
        before = {p.relative_to(self.project) for p in self.project.rglob('*')}
        result = json.loads(self.run_cli('doctor').stdout)
        self.assertTrue(result['ok'])
        self.assertEqual(result['checks'][-1]['detail']['events'], 0)
        self.assertEqual(before, {p.relative_to(self.project) for p in self.project.rglob('*')})
        self.assertFalse((self.project / 'config.json').exists())

    def test_init_never_overwrites_local_config_or_history(self):
        self.run_cli('init')
        config = self.project / 'config.json'
        cfg = json.loads(config.read_text(encoding='utf-8')); cfg['lead'] = 'codex'
        config.write_text(json.dumps(cfg))
        self.run_cli('post', '--session', 'main', '--from', 'codex', '--type', 'say', '--body', 'isolated fixture')
        old = (self.project / 'board.jsonl').read_bytes()
        self.run_cli('init')
        self.assertEqual(json.loads(config.read_text(encoding='utf-8'))['lead'], 'codex')
        self.assertEqual((self.project / 'board.jsonl').read_bytes(), old)

    def test_bad_config_rejected_without_overwriting(self):
        config = self.project / 'config.json'
        for value in [[], {}, {'agents': None}, {'lead': 'phantom'}]:
            config.write_text(json.dumps(value))
            result = json.loads(self.run_cli('doctor', expected=2).stdout)
            self.assertFalse(result['ok'])
            self.assertEqual(json.loads(config.read_text(encoding='utf-8')), value)
        self.run_cli('--config', str(self.base / 'missing.json'), 'sessions', expected=2)

    def test_cli_data_and_config_are_explicit_and_separate(self):
        state = self.base / 'private state'
        cfg = self.base / 'other-config.json'
        data = json.loads((self.project / 'config.example.json').read_text(encoding='utf-8')); data['lead'] = 'codex'
        cfg.write_text(json.dumps(data))
        prefix = ['--data-dir', str(state), '--config', str(cfg)]
        self.run_cli(*prefix, 'post', '--session', 'main', '--from', 'codex', '--type', 'say', '--body', 'isolated')
        result = json.loads(self.run_cli(*prefix, 'read', '--agent', 'codex', '--session', 'main').stdout)
        self.assertEqual(result['session']['lead'], 'codex')
        self.assertEqual(len(result['messages']), 1)
        self.assertFalse((self.project / 'board.jsonl').exists())

    def test_install_preview_idempotency_backups_and_source_portability(self):
        original = (self.project / 'skills/agents-talk/location.md').read_bytes()
        preview = json.loads(self.install().stdout)
        self.assertFalse(preview['applied'])
        self.assertFalse((self.base / 'codex skills').exists())
        self.install('--apply')
        target = self.base / 'codex skills/agents-talk/SKILL.md'
        self.assertTrue(target.exists())
        self.assertEqual((self.project / 'skills/agents-talk/location.md').read_bytes(), original)
        self.install('--apply')
        self.assertFalse((self.project / '.backups').exists())
        target.write_text('user modified content')
        self.install('--apply')
        backups = list((self.project / '.backups').rglob('SKILL.md'))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_text(encoding='utf-8'), 'user modified content')

    def test_custom_data_prefix_and_claude_hook_only_in_execute_skill(self):
        state = self.base / 'separate state'
        cfg = self.project / 'config.example.json'
        self.install('--apply', '--data-dir', str(state), '--config', str(cfg))
        folder = self.base / 'claude skills/agents-talk'
        location = (folder / 'location.md').read_text(encoding='utf-8')
        execute = (folder / 'SKILL.md').read_text(encoding='utf-8')
        self.assertIn(str(state), location)
        self.assertIn('--data-dir', execute)
        self.assertIn('--config', execute)
        self.assertIn('${CLAUDE_SESSION_ID}', execute)
        self.assertIn('\nhooks:', execute)
        self.assertNotIn('\nhooks:', (self.base / 'codex skills/agents-talk/SKILL.md').read_text(encoding='utf-8'))
        self.assertNotIn('\nhooks:', (self.base / 'claude skills/agents-talk-plan/SKILL.md').read_text(encoding='utf-8'))

    def test_uninstall_preserves_modified_unrelated_and_unmanaged_files(self):
        self.install('--apply')
        folder = self.base / 'codex skills/agents-talk'
        (folder / 'SKILL.md').write_text('my edits')
        (folder / 'personal.txt').write_text('keep me')
        self.install('--uninstall')
        self.assertTrue((folder / 'location.md').exists())
        self.install('--uninstall', '--apply')
        self.assertEqual((folder / 'SKILL.md').read_text(encoding='utf-8'), 'my edits')
        self.assertTrue((folder / 'personal.txt').exists())
        self.assertFalse((folder / 'location.md').exists())
        self.assertFalse((self.base / 'claude skills/agents-talk').exists())
        result = self.install('--uninstall', '--apply')
        self.assertIn('skip_unmanaged', result.stdout)

    def test_installer_refuses_other_project_ownership_and_source_target(self):
        self.install('--apply')
        marker = self.base / 'codex skills/agents-talk/.agents-talk-install.json'
        data = json.loads(marker.read_text(encoding='utf-8')); data['project'] = 'another project'
        marker.write_text(json.dumps(data))
        self.install('--apply', expected=2)
        self.install('--uninstall', '--apply', expected=2)
        self.install('--apply', '--target', 'codex=' + str(self.project / 'skills'), expected=2)

    def test_release_reproducible_checksums_and_private_files_excluded(self):
        for name in ['board.jsonl', 'config.json', 'uploads/private.txt', '.backups/private.txt', 'scripts/python-path.txt']:
            path = self.project / name; path.parent.mkdir(exist_ok=True, parents=True); path.write_text('PRIVATE' + '_SENTINEL')
        a, b = self.base / 'a.zip', self.base / 'b.zip'
        release.build(self.project, a, True); release.build(self.project, b, True)
        self.assertEqual(a.read_bytes(), b.read_bytes())
        self.assertIn(hashlib.sha256(a.read_bytes()).hexdigest(), a.with_name('a.zip.sha256').read_text(encoding='utf-8'))
        with zipfile.ZipFile(a) as z:
            names = z.namelist()
            self.assertFalse(any(n.endswith('/board.jsonl') or '/uploads/' in n for n in names))
            self.assertFalse(any((b'PRIVATE' + b'_SENTINEL') in z.read(n) for n in names))
            manifest = json.loads(z.read(next(n for n in names if n.endswith('SOURCE-MANIFEST.json'))))
            for row in manifest['files']:
                self.assertEqual(hashlib.sha256(z.read('agents-talk-' + manifest['version'] + '/' + row['path'])).hexdigest(), row['sha256'])
        with self.assertRaises(ValueError): release.build(self.project, a, True)

    def test_release_blocks_private_paths_and_suspicious_credentials(self):
        path = self.project / 'README.md'
        for bad in [str(Path.home() / 'private'), 'gh' + 'p_' + 'A' * 40]:
            path.write_text(bad)
            with self.assertRaises(ValueError): release.inventory(self.project)
        path.write_text('public text')
        manifest = self.project / 'release-files.json'
        entries = json.loads(manifest.read_text(encoding='utf-8')); entries.append('board.jsonl')
        manifest.write_text(json.dumps(entries))
        with self.assertRaises(ValueError): release.inventory(self.project)

    def test_release_license_gate(self):
        self.assertEqual(release.build(self.project)['license_status'], 'included')
        manifest = self.project / 'release-files.json'
        manifest.write_text(json.dumps([p for p in json.loads(manifest.read_text(encoding='utf-8')) if p != 'LICENSE']))
        with self.assertRaisesRegex(ValueError, 'No LICENSE'): release.build(self.project)
        self.assertEqual(release.build(self.project, allow_unlicensed=True)['license_status'], 'pending_owner_choice')

    def test_release_rejects_inconsistent_license_metadata(self):
        lock = self.project / 'package-lock.json'
        data = json.loads(lock.read_text(encoding='utf-8'))
        data['packages']['']['license'] = 'UNLICENSED'
        lock.write_text(json.dumps(data), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'license metadata must agree'):
            release.build(self.project)

    def test_release_rejects_inconsistent_version_metadata(self):
        package = self.project / 'package.json'
        data = json.loads(package.read_text(encoding='utf-8')); data['version'] = '9.9.9'
        package.write_text(json.dumps(data), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'versions must agree'): release.build(self.project, allow_unlicensed=True)

    def test_installer_rejects_invalid_manifest_before_writing(self):
        self.install('--apply')
        folder = self.base / 'codex skills/agents-talk'
        before = (folder / 'SKILL.md').read_bytes()
        (folder / '.agents-talk-install.json').write_text('[]', encoding='utf-8')
        self.install('--apply', expected=2)
        self.install('--uninstall', '--apply', expected=2)
        self.assertEqual((folder / 'SKILL.md').read_bytes(), before)

    def test_release_rejects_symlink_source(self):
        link = self.project / 'linked.txt'
        try: link.symlink_to(self.project / 'VERSION')
        except OSError: self.skipTest('Symlink creation unavailable')
        manifest = self.project / 'release-files.json'
        manifest.write_text(json.dumps([*json.loads(manifest.read_text(encoding='utf-8')), 'linked.txt']))
        with self.assertRaises(ValueError): release.inventory(self.project)

    def start_fresh(self):
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0)); port = sock.getsockname()[1]
        proc = subprocess.Popen([sys.executable, str(self.project / 'hub.py'), 'serve', '--port', str(port), '--no-open'],
                                env=self.env, cwd=self.base, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.addCleanup(lambda: (proc.terminate(), proc.wait(timeout=10)) if proc.poll() is None else None)
        base = f'http://127.0.0.1:{port}'
        for _ in range(100):
            if proc.poll() is not None: self.fail('Fresh server exited')
            try:
                with urllib.request.urlopen(base + '/api/health', timeout=1) as response: json.load(response)
                return base
            except OSError: time.sleep(.05)
        self.fail('Fresh server did not become ready')

    def test_fresh_http_empty_board_health_and_request_boundaries(self):
        base = self.start_fresh()
        with urllib.request.urlopen(base + '/api/health') as r: health = json.load(r)
        self.assertNotIn('csrf', health)
        self.assertEqual(health['root'], str(self.project))
        with urllib.request.urlopen(base + '/api/state') as r: state = json.load(r)
        self.assertEqual(state['messages'], []); self.assertEqual(state['tasks'], [])
        with urllib.request.urlopen(base + '/api/skills') as r: guides = json.load(r)
        self.assertIn('--data-dir', guides['codex'])
        self.assertIn(str(self.project), guides['codex'])
        for headers in [{'Host': 'evil.invalid'}, {'Origin': 'https://evil.invalid'}, {'Sec-Fetch-Site': 'cross-site'}]:
            with self.subTest(headers=headers):
                connection = http.client.HTTPConnection('127.0.0.1', int(base.rsplit(':', 1)[1]), timeout=5)
                try:
                    connection.request('GET', '/api/state', headers=headers)
                    response = connection.getresponse()
                    self.assertEqual(response.status, 400)
                    response.read()
                finally: connection.close()

    def test_versions_match_locked_package(self):
        version = (self.project / 'VERSION').read_text(encoding='utf-8').strip()
        self.assertEqual(version, json.loads((self.project / 'package.json').read_text(encoding='utf-8'))['version'])
        self.assertEqual(version, json.loads((self.project / 'package-lock.json').read_text(encoding='utf-8'))['version'])
        self.assertIn(version, self.run_cli('--version').stdout)

    def test_public_cli_outputs_utf8_under_legacy_windows_encoding(self):
        env = {**self.env, 'PYTHONUTF8': '0', 'PYTHONIOENCODING': 'cp1252:strict'}
        commands = [
            ['build_release.py', '--check', '--allow-unlicensed'],
            ['install_skills.py', '--clients', 'codex', '--target', 'codex=' + str(self.base / '技能目录')],
            ['audit_public.py', '--source', str(self.project)],
        ]
        for script, *args in commands:
            with self.subTest(script=script):
                result = subprocess.run([sys.executable, str(self.project / 'scripts' / script), *args],
                                        cwd=self.base, env=env, capture_output=True, timeout=20)
                self.assertEqual(result.returncode, 0, result.stderr.decode('utf-8'))
                self.assertIsInstance(json.loads(result.stdout.decode('utf-8')), dict)
        self.assertFalse((self.base / '技能目录').exists())

    def test_archive_extracts_to_a_working_empty_project(self):
        archive = self.base / 'release.zip'
        result = release.build(self.project, archive, True)
        destination = self.base / 'extracted copy'
        with zipfile.ZipFile(archive) as z: z.extractall(destination)
        self.project = destination / ('agents-talk-' + result['version'])
        self.assertTrue(json.loads(self.run_cli('doctor').stdout)['ok'])
        base = self.start_fresh()
        with urllib.request.urlopen(base + '/api/state') as r: state = json.load(r)
        self.assertEqual(state['total'], 0)
        self.assertEqual(state['tasks'], [])
        self.assertTrue(all(not a['online'] for a in state['agents'].values()))

    @unittest.skipUnless(os.name == 'nt', 'Windows background launcher')
    def test_windows_launch_reuse_and_stop_identity_guard(self):
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0)); port = sock.getsockname()[1]
        def ps(script, *args, expected=0):
            # Background Start-Process may inherit anonymous pipe handles on Windows.
            # File-backed diagnostics let the launching shell exit independently.
            # Allow the launcher's mutex/startup deadlines plus shared-runner startup.
            log = self.base / 'powershell-test.log'
            with log.open('wb') as output:
                result = subprocess.run(['powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File',
                                         str(self.project / 'scripts' / script), '-Port', str(port), *args],
                                        env=self.env, cwd=self.base, stdout=output, stderr=output, timeout=90)
            self.assertEqual(result.returncode, expected, log.read_text(encoding='utf-8', errors='replace'))
            return result
        ps('launch.ps1', '-NoOpen')
        pid_file = self.project / '.runtime' / f'server-{port}.pid'
        saved = pid_file.read_bytes()
        try:
            ps('launch.ps1', '-NoOpen')
            self.assertEqual(pid_file.read_bytes(), saved)
            # A stale/mismatched PID must never terminate an unrelated process.
            pid_file.write_text(str(os.getpid()), encoding='utf-8')
            ps('stop.ps1', expected=1)
            with urllib.request.urlopen(f'http://127.0.0.1:{port}/api/health') as r:
                self.assertEqual(json.load(r)['status'], 'ok')
        finally:
            pid_file.write_bytes(saved)
            ps('stop.ps1')

    @unittest.skipUnless(os.name == 'nt', 'Windows interpreter discovery')
    def test_windows_explicit_python_skips_fallback_launchers(self):
        script = self.base / 'interpreter-priority.ps1'
        script.write_text(". (Join-Path $env:AGENTS_TALK_PROJECT_TEST 'scripts/python.ps1')\n"
                          "function Get-Command { throw 'Unexpected fallback discovery' }\n"
                          "Find-AgentsTalkPython\n", encoding='utf-8-sig')
        result = subprocess.run(['powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', str(script)],
                                env={**self.env, 'AGENTS_TALK_PROJECT_TEST': str(self.project)},
                                capture_output=True, encoding='utf-8', timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(Path(result.stdout.strip()).resolve(), Path(sys.executable).resolve())


if __name__ == '__main__':
    unittest.main()
