#!/usr/bin/env python3
"""Startup script for the Open Notebook surreal-commands worker.

Wraps the stock ``surreal-commands-worker`` entry point so orphaned ``running``
command rows are reaped before the worker starts dispatching.

The reap cannot live in ``commands/__init__.py``: the API imports that package
too (``api/command_service.py``), and reaping from the API process would fail
jobs that a live worker is executing. Only this process — which is about to
become the sole worker — may do it.

CLI flags are handed through untouched, so this stays a drop-in replacement:

    python run_worker.py --import-modules commands
"""

import asyncio
import sys
from pathlib import Path

# Add the current directory to Python path so imports work
current_dir = Path(__file__).parent
sys.path.insert(0, str(current_dir))

from surreal_commands.cli.worker import main as worker_main  # noqa: E402

from commands._reaper import reap_orphaned_commands  # noqa: E402

if __name__ == "__main__":
    asyncio.run(reap_orphaned_commands())
    worker_main()
