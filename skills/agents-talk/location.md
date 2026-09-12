# Project-local location

This source copy is portable. Resolve the project two directories above this file and verify `hub.py` and `PROTOCOL.md` exist there. Use a working Python 3.10+ interpreter.

Installed copies receive absolute paths and an exact command prefix from `scripts/install_skills.py`. Keep its data/config arguments in every command. If the dashboard uses a custom data directory or config and no command prefix is available, ask the user for them before joining; do not silently connect to a different board.
