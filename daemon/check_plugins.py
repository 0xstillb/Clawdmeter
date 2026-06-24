#!/usr/bin/env python3
"""Run all discovered Clawdmeter plugins and report their status.

Usage:
    python daemon/check_plugins.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

# Add repo root
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from daemon.plugin_runner import PluginRunner


async def main() -> None:
    plugins_dir = _REPO_ROOT / "daemon" / "plugins"
    runner = PluginRunner(plugins_dir)
    discovered = runner.discover()

    print(f"Plugins directory: {plugins_dir}")
    if not plugins_dir.is_dir():
        print("  ⚠  Directory does not exist")
        return

    if not discovered:
        print("  No executable plugins found")
        return

    print(f"\nDiscovered {len(discovered)} plugin(s):\n")
    for name, path in sorted(discovered.items()):
        print(f"  [{name}]")
        print(f"    Path: {path}")
        print(f"    Size: {path.stat().st_size} bytes")
        try:
            resp = await runner.run(name)
            if resp.ok and resp.payload:
                print(f"    Status: ✓ OK (payload provider: {resp.payload.get('p', '?')})")
            else:
                print(f"    Status: ✗ {resp.error}")
                if resp.retry:
                    print(f"             (transient — will retry)")
                else:
                    print(f"             (permanent — needs user action)")
        except Exception as e:
            print(f"    Status: ✗ CRASHED: {e}")
        print()


if __name__ == "__main__":
    asyncio.run(main())
