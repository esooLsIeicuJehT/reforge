"""Smoke-test an extracted native ReForge release artifact."""
from __future__ import annotations

import os
import platform
import subprocess
import sys
from pathlib import Path


def _find_executable(root: Path) -> Path:
    system = platform.system()
    preferred: list[Path] = []

    if system == "Windows":
        for name in ("ReForge.exe", "main.exe"):
            preferred.extend(root.rglob(name))
        if not preferred:
            preferred = [
                path for path in root.rglob("*.exe")
                if not any(part.lower() in {"qt6", "plugins"} for part in path.parts)
            ]
    elif system == "Darwin":
        for bundle_name in ("ReForge.app", "main.app"):
            for bundle in root.rglob(bundle_name):
                macos_dir = bundle / "Contents" / "MacOS"
                if macos_dir.is_dir():
                    preferred.extend(path for path in macos_dir.iterdir() if path.is_file())
        if not preferred:
            preferred = [
                path
                for path in root.rglob("*.app/Contents/MacOS/*")
                if path.is_file()
            ]
    else:
        for name in ("ReForge.bin", "main.bin", "ReForge", "main"):
            preferred.extend(root.rglob(name))
        preferred = [
            path for path in preferred
            if path.is_file() and os.access(path, os.X_OK)
        ]

    matches = sorted({path.resolve() for path in preferred})
    if not matches:
        raise RuntimeError(f"No packaged ReForge executable found under {root}")
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
