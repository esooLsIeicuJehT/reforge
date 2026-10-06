"""Smoke-test an extracted native ReForge release artifact."""
from __future__ import annotations

import os
import platform
import subprocess
import sys
from pathlib import Path


def _find_executable(root: Path) -> Path:
    system = platform.system()
    if system == "Windows":
        matches = sorted(root.rglob("ReForge.exe"))
    elif system == "Darwin":
        matches = sorted(root.rglob("ReForge.app/Contents/MacOS/ReForge"))
    else:
        matches = sorted(root.rglob("ReForge.bin"))
    if not matches:
        raise RuntimeError(f"No ReForge executable found under {root}")
    return matches[0]


def main() -> int:
    if len(sys.argv) != 2:
        raise SystemExit("usage: smoke_artifact.py <extracted-artifact-root>")

    root = Path(sys.argv[1]).resolve()
    executable = _find_executable(root)
    env = os.environ.copy()
    if platform.system() == "Linux":
        env.setdefault("QT_QPA_PLATFORM", "offscreen")

    print(f"Launching smoke test: {executable}", flush=True)
    result = subprocess.run(
        [str(executable), "--smoke-test"],
        env=env,
        timeout=45,
        check=False,
    )
    if result.returncode != 0:
        raise SystemExit(f"Packaged application smoke test failed with {result.returncode}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
