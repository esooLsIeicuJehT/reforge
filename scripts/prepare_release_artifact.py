"""Validate a pyside6-deploy standalone build and package release metadata."""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import platform
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
RELEASE_DIR = PROJECT_ROOT / "release-artifacts"


def _ignored(path: Path) -> bool:
    ignored_parts = {".git", ".venv", "venv", "release-artifacts", "__pycache__"}
    return any(part in ignored_parts for part in path.parts)


def find_build_root() -> Path:
    """Locate the standalone directory or macOS app produced by pyside6-deploy."""
    candidates: list[Path] = []
    for pattern in ("*.dist", "*.app"):
        for path in PROJECT_ROOT.rglob(pattern):
            if path.is_dir() and not _ignored(path.relative_to(PROJECT_ROOT)):
                candidates.append(path)

    if not candidates:
        raise RuntimeError("No pyside6-deploy standalone output (.dist/.app) was found")

    candidates.sort(key=lambda path: path.stat().st_mtime, reverse=True)
    return candidates[0]


def find_executable(build_root: Path) -> Path:
    """Find the application launcher inside a standalone output."""
    if build_root.suffix == ".app":
        macos_dir = build_root / "Contents" / "MacOS"
        if not macos_dir.is_dir():
            raise RuntimeError(f"Malformed app bundle: {build_root}")
        candidates = [path for path in macos_dir.iterdir() if path.is_file()]
    else:
        preferred = [
            build_root / "ReForge.exe",
            build_root / "main.exe",
            build_root / "ReForge.bin",
            build_root / "main.bin",
            build_root / "ReForge",
            build_root / "main",
        ]
        candidates = [path for path in preferred if path.is_file()]
        if not candidates:
            candidates = [
                path
                for path in build_root.iterdir()
                if path.is_file()
                and path.suffix.lower() not in {".dll", ".so", ".dylib", ".json", ".txt"}
            ]

    if not candidates:
        raise RuntimeError(f"No application executable found under {build_root}")

    def score(path: Path) -> tuple[int, str]:
        name = path.name.casefold()
        priority = 0
        if "reforge" in name:
            priority += 20
        if name.startswith("main"):
            priority += 10
        if path.suffix.lower() in {".exe", ".bin"}:
            priority += 5
        return (-priority, name)

    candidates.sort(key=score)
    return candidates[0]


def smoke_test(executable: Path) -> None:
    """Launch the frozen application and require its built-in smoke mode to exit cleanly."""
    env = os.environ.copy()
    if sys.platform.startswith("linux"):
        env.setdefault("QT_QPA_PLATFORM", "offscreen")

    if os.name != "nt":
        executable.chmod(executable.stat().st_mode | stat.S_IXUSR)

    result = subprocess.run(
        [str(executable), "--smoke-test"],
        cwd=executable.parent,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        timeout=45,
        check=False,
    )
    print(result.stdout)
    if result.returncode != 0:
        raise RuntimeError(
            f"Frozen application smoke test failed with exit code {result.returncode}"
        )


def _safe_component(value: str) -> str:
    return "".join(char if char.isalnum() or char in "-_." else "_" for char in value)


def collect_python_licenses(destination: Path) -> list[str]:
    """Copy license files shipped by the Qt/PySide Python distributions."""
    copied: list[str] = []
    target_dists = {"pyside6", "pyside6-essentials", "pyside6-addons", "shiboken6"}

    for dist in importlib.metadata.distributions():
        raw_name = dist.metadata.get("Name", "")
        normalized = raw_name.casefold().replace("_", "-")
        if normalized not in target_dists:
            continue

        for relative in dist.files or []:
            parts = [part.casefold() for part in relative.parts]
            filename = relative.name.casefold()
            if not (
                any(part in {"license", "licenses"} for part in parts)
                or filename.startswith("license")
                or filename.startswith("copying")
                or filename.startswith("notice")
            ):
                continue

            source = dist.locate_file(relative)
            if not source.is_file():
                continue

            out = destination / _safe_component(raw_name) / Path(*relative.parts)
            out.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, out)
            copied.append(str(out.relative_to(destination)))

    return sorted(copied)


def dependency_manifest() -> list[dict[str, str]]:
    """Capture the exact Python environment used to create the frozen artifact."""
    rows: list[dict[str, str]] = []
    for dist in importlib.metadata.distributions():
        name = dist.metadata.get("Name") or "unknown"
        rows.append({"name": name, "version": dist.version})
    rows.sort(key=lambda row: row["name"].casefold())
    return rows


def hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_file_manifest(root: Path, output: Path) -> None:
    rows: list[str] = []
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        rows.append(f"{hash_file(path)}  {path.relative_to(root).as_posix()}")
    output.write_text("\n".join(rows) + "\n", encoding="utf-8")


def stage_build(build_root: Path, platform_label: str) -> Path:
    RELEASE_DIR.mkdir(parents=True, exist_ok=True)
    machine = _safe_component(platform.machine() or "unknown")
    stage_name = f"ReForge-{_safe_component(platform_label)}-{machine}"
    stage = RELEASE_DIR / stage_name
    if stage.exists():
        shutil.rmtree(stage)
    stage.mkdir(parents=True)

    app_destination = stage / build_root.name
    shutil.copytree(build_root, app_destination, symlinks=True)

    notices = stage / "NOTICES"
    notices.mkdir()
    for source_name in ("LICENSE", "THIRD_PARTY_NOTICES.md"):
        shutil.copy2(PROJECT_ROOT / source_name, notices / source_name)
    shutil.copy2(
        PROJECT_ROOT / "docs" / "RELEASE_CHECKLIST.md",
        notices / "RELEASE_CHECKLIST.md",
    )

    qt_license_files = collect_python_licenses(notices / "python-licenses")
    if not qt_license_files:
        raise RuntimeError("No PySide6/Qt Python license files were discovered in the build environment")

    build_info = {
        "application": "ReForge",
        "application_version": "0.2.0",
        "source_commit": os.environ.get("GITHUB_SHA", "local"),
        "built_at_utc": datetime.now(timezone.utc).isoformat(),
        "platform": platform.platform(),
        "machine": platform.machine(),
        "python": platform.python_version(),
        "qt_license_files": qt_license_files,
    }
    (notices / "BUILD-INFO.json").write_text(
        json.dumps(build_info, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (notices / "PYTHON-DEPENDENCIES.json").write_text(
        json.dumps(dependency_manifest(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    write_file_manifest(stage, notices / "ARTIFACT-FILES.sha256")
    return stage


def archive_stage(stage: Path) -> Path:
    if os.name == "nt":
        archive = RELEASE_DIR / f"{stage.name}.zip"
        with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for path in sorted(stage.rglob("*")):
                if path.is_file():
                    zf.write(path, path.relative_to(RELEASE_DIR))
        return archive

    archive = RELEASE_DIR / f"{stage.name}.tar.gz"
    with tarfile.open(archive, "w:gz", dereference=False) as tf:
        tf.add(stage, arcname=stage.name, recursive=True)
    return archive


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--platform", required=True, help="Human-readable CI platform label")
    parser.add_argument("--skip-smoke", action="store_true")
    args = parser.parse_args()

    build_root = find_build_root()
    executable = find_executable(build_root)
    print(f"Standalone build: {build_root}")
    print(f"Executable: {executable}")

    if not args.skip_smoke:
        smoke_test(executable)

    stage = stage_build(build_root, args.platform)
    archive = archive_stage(stage)
    checksum = hash_file(archive)
    checksum_file = RELEASE_DIR / "SHA256SUMS.txt"
    checksum_file.write_text(f"{checksum}  {archive.name}\n", encoding="utf-8")
    print(f"Release archive: {archive}")
    print(f"SHA-256: {checksum}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
