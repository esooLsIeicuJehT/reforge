"""Stage legal metadata, SBOMs, checksums, and archive a native ReForge build."""
from __future__ import annotations

import gzip
import hashlib
import importlib.metadata as metadata
import json
import os
import platform
import shutil
import stat
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEPLOY_ROOT = ROOT / "deployment"
LEGACY_BUILD_ROOT = ROOT / "build" / "native"
RELEASE_ROOT = ROOT / "release"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _find_deployed_output() -> Path:
    roots = (DEPLOY_ROOT, LEGACY_BUILD_ROOT)
    # Prefer a complete standalone directory or app bundle. Nuitka may also
    # leave a launcher executable beside the .dist directory; packaging that
    # executable alone would omit its runtime dependencies.
    for patterns in (("*.dist", "*.app"), ("*.exe", "*.bin")):
        candidates: set[Path] = set()
        for root in roots:
            if not root.exists():
                continue
            for pattern in patterns:
                candidates.update(path.resolve() for path in root.glob(pattern))
        if candidates:
            return sorted(candidates)[0]

    raise RuntimeError(
        f"No native deployment output found in {DEPLOY_ROOT} or {LEGACY_BUILD_ROOT}"
    )


def _distribution_license_metadata(dist: metadata.Distribution) -> str:
    """Serialize license evidence carried by an installed Python distribution."""
    message = dist.metadata
    fields = (
        "Name",
        "Version",
        "License",
        "License-Expression",
        "Home-page",
        "Project-URL",
    )
    lines: list[str] = []
    for field in fields:
        values = message.get_all(field) or []
        for value in values:
            if value:
                lines.append(f"{field}: {value}")

    classifiers = [
        value
        for value in (message.get_all("Classifier") or [])
        if "License ::" in value
    ]
    for classifier in classifiers:
        lines.append(f"Classifier: {classifier}")

    return "\n".join(lines) + "\n"


def _copy_release_material(stage: Path) -> None:
    for name in ("LICENSE", "THIRD_PARTY_NOTICES.md"):
        source = ROOT / name
        if not source.exists():
            raise RuntimeError(f"Required legal file missing: {name}")
        shutil.copy2(source, stage / name)

    checklist = ROOT / "docs" / "RELEASE_CHECKLIST.md"
    if not checklist.exists():
        raise RuntimeError("Required release checklist is missing")
    shutil.copy2(checklist, stage / "RELEASE_CHECKLIST.md")

    build_metadata = ROOT / "build" / "release-build.json"
    if not build_metadata.exists():
        raise RuntimeError("Native build metadata is missing")
    payload = json.loads(build_metadata.read_text(encoding="utf-8"))
    payload["packaged_platform"] = platform.platform()
    payload["packaged_machine"] = platform.machine()
    payload["github_run_id"] = os.getenv("GITHUB_RUN_ID", "")
    payload["github_run_attempt"] = os.getenv("GITHUB_RUN_ATTEMPT", "")
    (stage / "BUILD-INFO.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    license_root = stage / "licenses" / "qt-for-python"
    recorded_distributions = 0
    copied_files = 0
    for dist_name in ("PySide6", "PySide6_Essentials", "PySide6_Addons", "shiboken6"):
        try:
            dist = metadata.distribution(dist_name)
        except metadata.PackageNotFoundError:
            continue

        recorded_distributions += 1
        canonical_name = dist.metadata.get("Name") or dist_name
        target_root = license_root / canonical_name
        target_root.mkdir(parents=True, exist_ok=True)

        # Some current Qt for Python wheels expose their licensing terms in
        # wheel METADATA without shipping a standalone LICENSE file. Preserve
        # that exact installed-distribution evidence in every release candidate.
        (target_root / "DISTRIBUTION-LICENSE-METADATA.txt").write_text(
            _distribution_license_metadata(dist),
            encoding="utf-8",
        )

        for entry in dist.files or []:
            parts = [part.lower() for part in entry.parts]
            filename = entry.name.lower()
            if not (
                "licenses" in parts
                or "license" in parts
                or filename.startswith("license")
                or filename.startswith("copying")
                or filename.startswith("notice")
            ):
                continue
            source = Path(dist.locate_file(entry))
            if not source.is_file():
                continue
            relative = Path(*entry.parts[-2:]) if len(entry.parts) >= 2 else Path(entry.name)
            destination = target_root / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
            copied_files += 1

    if recorded_distributions == 0:
        raise RuntimeError("No installed Qt for Python distributions were found")

    summary = {
        "distributions_recorded": recorded_distributions,
        "standalone_license_files_copied": copied_files,
        "note": (
            "Some Qt for Python wheels may carry license declarations only in "
            "distribution METADATA. The exact release licensing path and any "
            "additional notice/text obligations remain governed by the release checklist."
        ),
    }
    license_root.mkdir(parents=True, exist_ok=True)
    (license_root / "LICENSE-MATERIAL-SUMMARY.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _write_dependency_metadata(stage: Path) -> None:
    freeze = subprocess.run(
        [sys.executable, "-m", "pip", "freeze", "--all"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    (stage / "DEPENDENCIES.txt").write_text(freeze, encoding="utf-8")

    sbom = stage / "SBOM.cdx.json"
    subprocess.run(
        [
            "cyclonedx-py",
            "environment",
            "--output-reproducible",
            "--output-format",
            "JSON",
            "--output-file",
            str(sbom),
        ],
        cwd=ROOT,
        check=True,
    )


def _write_checksums(stage: Path) -> None:
    lines: list[str] = []
    for path in sorted(stage.rglob("*")):
        rel = path.relative_to(stage).as_posix()
        if rel == "SHA256SUMS.txt":
            continue
        if path.is_symlink():
            lines.append(f"SYMLINK  {rel} -> {os.readlink(path)}")
        elif path.is_file():
            lines.append(f"{_sha256(path)}  {rel}")
    (stage / "SHA256SUMS.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _normalized_epoch() -> int:
    raw = os.getenv("SOURCE_DATE_EPOCH", "1704067200")
    try:
        return max(int(raw), 315532800)
    except ValueError:
        return 1704067200


def _zip_stage(stage: Path, archive: Path, epoch: int) -> None:
    import datetime

    timestamp = datetime.datetime.fromtimestamp(epoch, tz=datetime.timezone.utc)
    date_time = (
        timestamp.year,
        timestamp.month,
        timestamp.day,
        timestamp.hour,
        timestamp.minute,
        timestamp.second,
    )

    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for path in sorted(stage.rglob("*")):
            arcname = f"{stage.name}/{path.relative_to(stage).as_posix()}"
            if path.is_dir():
                continue
            info = zipfile.ZipInfo(arcname, date_time=date_time)
            mode = stat.S_IMODE(path.lstat().st_mode)
            info.external_attr = mode << 16
            if path.is_symlink():
                info.external_attr = (stat.S_IFLNK | mode) << 16
                zf.writestr(info, os.readlink(path).encode("utf-8"))
            else:
                zf.writestr(
                    info,
                    path.read_bytes(),
                    compress_type=zipfile.ZIP_DEFLATED,
                    compresslevel=9,
                )


def _tar_stage(stage: Path, archive: Path, epoch: int) -> None:
    with archive.open("wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=epoch, compresslevel=9) as gz:
            with tarfile.open(fileobj=gz, mode="w", dereference=False) as tf:

                def normalize(info: tarfile.TarInfo) -> tarfile.TarInfo:
                    info.uid = 0
                    info.gid = 0
                    info.uname = "root"
                    info.gname = "root"
                    info.mtime = epoch
                    return info

                tf.add(stage, arcname=stage.name, recursive=True, filter=normalize)


def main() -> int:
    source = _find_deployed_output()
    system = platform.system().lower()
    machine = platform.machine().lower().replace(" ", "-")
    label = f"ReForge-{system}-{machine}"

    staging_root = RELEASE_ROOT / "staging"
    stage = staging_root / label
    if stage.exists():
        shutil.rmtree(stage)
    stage.mkdir(parents=True, exist_ok=True)

    destination = stage / source.name
    if source.is_dir():
        shutil.copytree(source, destination, symlinks=True)
    else:
        shutil.copy2(source, destination)

    _copy_release_material(stage)
    _write_dependency_metadata(stage)
    _write_checksums(stage)

    RELEASE_ROOT.mkdir(parents=True, exist_ok=True)
    epoch = _normalized_epoch()
    if platform.system() == "Windows":
        archive = RELEASE_ROOT / f"{label}.zip"
        _zip_stage(stage, archive, epoch)
    else:
        archive = RELEASE_ROOT / f"{label}.tar.gz"
        _tar_stage(stage, archive, epoch)

    checksum_file = archive.with_name(archive.name + ".sha256")
    checksum_file.write_text(f"{_sha256(archive)}  {archive.name}\n", encoding="utf-8")

    print(f"artifact={archive}")
    print(f"checksum={checksum_file}")
    github_output = os.getenv("GITHUB_OUTPUT")
    if github_output:
        with Path(github_output).open("a", encoding="utf-8") as handle:
            handle.write(f"artifact={archive}\n")
            handle.write(f"checksum={checksum_file}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
