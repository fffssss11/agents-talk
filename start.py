#!/usr/bin/env python3
"""Portable foreground launcher. Does not install or download dependencies."""
import sys

if sys.version_info < (3, 10):
    raise SystemExit('Agents Talk requires Python 3.10 or newer.')

import argparse
import subprocess
from pathlib import Path

parser = argparse.ArgumentParser(description='Start Agents Talk locally; Ctrl+C stops the server.')
parser.add_argument('--port', type=int, default=8765)
parser.add_argument('--no-open', action='store_true')
parser.add_argument('--data-dir', type=Path)
parser.add_argument('--config', type=Path)
args = parser.parse_args()
command = [sys.executable, str(Path(__file__).resolve().with_name('hub.py'))]
for key in ('data_dir', 'config'):
    if getattr(args, key): command.extend(['--' + key.replace('_', '-'), str(getattr(args, key).resolve())])
command.extend(['serve', '--port', str(args.port)])
if args.no_open: command.append('--no-open')
try:
    raise SystemExit(subprocess.call(command))
except KeyboardInterrupt:
    raise SystemExit(0)
