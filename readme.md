# ReForge

ReForge is a modular PyQt6 desktop framework for **authorized reverse-engineering and device-analysis workflows**. It provides a dockable GUI, lifecycle-managed plugins, structured logging, an event bus, ADB/Fastboot integration, archive tooling, analysis-library browsing, and optional dynamic-instrumentation integrations.

## Production-hardening baseline

The repository now includes a first release-engineering baseline:

- per-user configuration with atomic writes and corrupt-config recovery
- corrected event subscription/unsubscription semantics and priority handling
- installable Python package metadata and a `reforge` console entry point
- GitHub Actions gates for dependency checks, compilation, and unit tests
- repository hygiene for Python caches, build output, logs, and working files
- a security reporting policy and explicit release-readiness checklist

## Requirements

- Python 3.10+
- Java for Java-based external tools you choose to use
- ADB/Fastboot for Android device workflows
- 7-Zip (`7z` or `7za`) for archive workflows
- Optional external tools required by individual plugins

## Install

```bash
git clone https://github.com/esooLsIeicuJehT/reforge.git
cd reforge
python -m venv .venv
```

Activate the virtual environment, then install:

```bash
python -m pip install --upgrade pip
python -m pip install -e .
```

For development and tests:

```bash
python -m pip install -e ".[dev]"
pytest
```

## Run

```bash
reforge
```

or:

```bash
python main.py
```

User settings live under `~/.reforge/`.

## CI

Pull requests run dependency validation, source compilation, and unit tests. A green CI run is a required engineering gate, but it does not by itself establish commercial redistribution readiness.

## Release status

**Do not treat the current repository as commercially redistributable yet.** Before a sale or public binary release, verify the provenance, exact versions, licenses, and redistribution terms for every bundled JAR/binary and select a project license. See [`docs/RELEASE_CHECKLIST.md`](docs/RELEASE_CHECKLIST.md).

Unfinished plugins should be removed from a release build or completed and backed by reproducible tests before being advertised as production features.

## Security and authorized use

Use ReForge only on software, devices, and environments you own or are explicitly authorized to assess. Security issues in ReForge itself should be reported through GitHub's private vulnerability-reporting flow when available. See [`SECURITY.md`](SECURITY.md).
