# ReForge

ReForge is a modular **PySide6** desktop framework for authorized reverse-engineering, device-management, archive, and dynamic-instrumentation workflows.

## Supported production baseline

The maintained baseline includes:

- **ADB / Fastboot** device management with argument-safe subprocess execution and confirmation for destructive lock/unlock actions
- **Archive tooling** for list, extract, and pack workflows through a separately installed 7-Zip-compatible executable
- **Analysis library browser** for local TypeLib/SigLib assets, with optional integration for a separately licensed JEB installation
- **Frida integration** for authorized process discovery, user-authored scripts, method tracing, and intent logging
- lifecycle-managed plugins, an in-process event bus, rotating per-user logs, and atomic configuration persistence

Legacy duplicate tooling, unfinished plugins, circumvention-specific patchers, and unverified bundled JAR files are intentionally excluded from the production baseline.

## Release engineering

ReForge includes:

- installable package metadata and a `reforge` console entry point
- GitHub Actions gates for dependency checks, compilation, and tests
- corruption-resistant settings under `~/.reforge/`
- plugin activation/initialization/shutdown failure isolation
- repository hygiene for caches, logs, work files, and build artifacts
- security and commercial-release checklists

## Requirements

- Python **3.10 through 3.14**
- ADB/Fastboot for Android device workflows that use those tools
- 7-Zip (`7z` or `7za`) for archive workflows
- optional external tools required by the workflow you choose to use

No third-party JAR or native executable is bundled in the production source distribution.

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

For optional Frida CLI integration:

```bash
python -m pip install -e ".[frida]"
```

## Run

```bash
reforge
```

or:

```bash
python main.py
```

## External integrations

ReForge does not redistribute JEB, Android platform tools, 7-Zip, or Frida server binaries. Install and license those products separately when a workflow requires them.

Optional integrations must fail gracefully when their external tool is unavailable; missing optional software must not prevent ReForge itself from starting.

## Licensing and commercial distribution

ReForge itself is distributed under the proprietary notice in [`LICENSE`](LICENSE). Third-party components retain their own licenses; see [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md).

The GUI uses **PySide6 / Qt for Python** rather than PyQt6. A commercial distributor must choose and comply with an applicable Qt licensing path, such as the open-source LGPLv3 path when its obligations can be satisfied or an appropriate Qt commercial license.

A green CI run establishes an engineering gate, not legal approval. Before shipping a standalone paid installer, complete [`docs/RELEASE_CHECKLIST.md`](docs/RELEASE_CHECKLIST.md), including the exact-file license audit, notices, platform smoke tests, code signing, and release checksums.

## Security and authorized use

Use ReForge only on software, devices, and environments you own or are explicitly authorized to assess. Security issues in ReForge itself should be reported through GitHub's private vulnerability-reporting flow when available. See [`SECURITY.md`](SECURITY.md).
