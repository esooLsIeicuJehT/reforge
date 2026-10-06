"""Build a native ReForge desktop artifact with Qt for Python's deploy tool."""
from __future__ import annotations

import configparser
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BUILD_ROOT = ROOT / "build" / "native"
GENERATED_SPEC = ROOT / "pysidedeploy.spec"
WORK_SPEC = ROOT / "build" / "pysidedeploy.release.spec"


def _run(cmd: list[str]) -> None:
    print("+", " ".join(cmd), flush=True)
    subprocess.run(cmd, cwd=ROOT, check=True)


def _configure_spec(spec_path: Path) -> None:
    parser = configparser.ConfigParser(interpolation=None)
    parser.read(spec_path, encoding="utf-8")

    for section in ("app", "python", "qt", "nuitka"):
        if not parser.has_section(section):
            parser.add_section(section)

    parser["app"]["title"] = "ReForge"
    parser["app"]["project_dir"] = str(ROOT)
    parser["app"]["input_file"] = str(ROOT / "main.py")
    parser["app"]["project_file"] = str(ROOT / "pyproject.toml")
    parser["app"]["exec_directory"] = str(BUILD_ROOT)

    parser["python"]["python_path"] = sys.executable
    parser["qt"]["modules"] = "Core,Gui,Widgets"

    parser["nuitka"]["mode"] = "standalone"
    parser["nuitka"]["extra_args"] = " ".join(
        [
            "--quiet",
            "--noinclude-qt-translations=True",
            "--include-package=plugins",
            "--include-package=core",
            "--include-package=gui",
            "--include-data-files=gui/dark_theme.qss=gui/dark_theme.qss",
        ]
    )

    WORK_SPEC.parent.mkdir(parents=True, exist_ok=True)
    with WORK_SPEC.open("w", encoding="utf-8") as handle:
        parser.write(handle)


def _discover_outputs() -> list[str]:
    if not BUILD_ROOT.exists():
        return []
    outputs = []
    for path in BUILD_ROOT.iterdir():
        if path.name.endswith(".dist") or path.suffix.lower() in {".app", ".exe", ".bin"}:
            outputs.append(str(path.resolve()))
    return sorted(outputs)


def main() -> int:
    deploy = shutil.which("pyside6-deploy")
    if not deploy:
        raise SystemExit("pyside6-deploy is not available on PATH")

    BUILD_ROOT.mkdir(parents=True, exist_ok=True)
    original_spec = GENERATED_SPEC.read_bytes() if GENERATED_SPEC.exists() else None

    try:
        _run([deploy, str(ROOT / "main.py"), "--init", "-f"])
        if not GENERATED_SPEC.exists():
            raise RuntimeError("pyside6-deploy did not generate pysidedeploy.spec")
        _configure_spec(GENERATED_SPEC)
        _run(
            [
                deploy,
                "-c",
                str(WORK_SPEC),
                "-f",
                "--keep-deployment-files",
                "--name",
                "ReForge",
            ]
        )
    finally:
        if original_spec is None:
            GENERATED_SPEC.unlink(missing_ok=True)
        else:
            GENERATED_SPEC.write_bytes(original_spec)

    outputs = _discover_outputs()
    if not outputs:
        raise RuntimeError(f"No deployed artifact found in {BUILD_ROOT}")

    metadata = {
        "platform": sys.platform,
        "python": sys.version,
        "outputs": outputs,
        "source_date_epoch": os.getenv("SOURCE_DATE_EPOCH", ""),
    }
    metadata_path = ROOT / "build" / "release-build.json"
    metadata_path.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(metadata, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
