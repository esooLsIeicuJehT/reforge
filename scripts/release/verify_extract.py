"""Verify a release archive checksum and extract it for smoke testing."""
from __future__ import annotations

import hashlib
import shutil
import sys
import tarfile
import zipfile
from pathlib import Path


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    if len(sys.argv) != 3:
        raise SystemExit("usage: verify_extract.py <download-dir> <output-dir>")

    source = Path(sys.argv[1]).resolve()
    output = Path(sys.argv[2]).resolve()
    checksums = sorted(source.glob("*.sha256"))
    if len(checksums) != 1:
        raise RuntimeError(f"Expected one .sha256 file in {source}, found {len(checksums)}")

    checksum_file = checksums[0]
    expected, archive_name = checksum_file.read_text(encoding="utf-8").strip().split(maxsplit=1)
    archive = source / archive_name
    actual = _sha256(archive)
    if actual != expected:
        raise RuntimeError(f"SHA-256 mismatch for {archive.name}: expected {expected}, got {actual}")

    if output.exists():
        shutil.rmtree(output)
    output.mkdir(parents=True)

    if archive.suffix == ".zip":
        with zipfile.ZipFile(archive) as zf:
            zf.extractall(output)
    elif archive.name.endswith(".tar.gz"):
        with tarfile.open(archive, "r:gz") as tf:
            tf.extractall(output, filter="data")
    else:
        raise RuntimeError(f"Unsupported release archive: {archive}")

    print(f"Verified {archive.name}: {actual}")
    print(f"Extracted to {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
