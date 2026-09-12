"""Public release metadata checks, with no network or user data access."""
import json
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]


class PublicMetadataTests(unittest.TestCase):
    def test_license_and_ci_gate(self):
        self.assertIn('MIT License', (ROOT / 'LICENSE').read_text(encoding='utf-8'))
        package = json.loads((ROOT / 'package.json').read_text(encoding='utf-8'))
        self.assertEqual(package['license'], 'MIT')
        self.assertNotIn('--allow-unlicensed', (ROOT / '.github/workflows/ci.yml').read_text(encoding='utf-8'))

    def test_readme_version_and_public_links(self):
        version = (ROOT / 'VERSION').read_text(encoding='utf-8').strip()
        for name in ('README.md', 'README.en.md'):
            text = (ROOT / name).read_text(encoding='utf-8')
            self.assertIn(version, text)
            self.assertIn('/releases/download/v' + version + '/', text)
            self.assertIn('(LICENSE)', text)

    def test_document_local_links_are_in_distribution(self):
        names = set(json.loads((ROOT / 'release-files.json').read_text(encoding='utf-8')))
        for name in sorted(n for n in names if n.endswith('.md')):
            text = (ROOT / name).read_text(encoding='utf-8')
            for target in re.findall(r'\]\(([^)\s]+)\)', text):
                if re.match(r'[a-zA-Z]+:', target) or target.startswith('#'):
                    continue
                target = target.split('#')[0]
                if not target:
                    continue
                resolved = (ROOT / name).parent.joinpath(target).resolve()
                self.assertTrue(resolved.is_relative_to(ROOT), name)
                self.assertIn(resolved.relative_to(ROOT).as_posix(), names, name)
