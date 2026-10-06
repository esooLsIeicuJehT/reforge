# ReForge release checklist

This checklist separates code readiness from commercial/legal readiness. It is an engineering checklist, not legal advice.

## Automated gates

- [ ] GitHub Actions CI is green for the exact release commit.
- [ ] `python -m pip check` passes.
- [ ] `python -m compileall -q core gui plugins main.py` passes.
- [ ] `pytest` passes, including the offscreen GUI/plugin smoke test.

## Desktop/runtime smoke test

Run on every supported operating system included in the release matrix:

- [ ] Application launches from a clean virtual environment.
- [ ] Missing optional external tools fail gracefully instead of crashing startup.
- [ ] Plugin load failures are visible in logs and do not prevent healthy plugins from loading.
- [ ] Closing the app stops plugin timers/workers and exits cleanly.
- [ ] ADB device refresh works with no device, one device, and an unavailable ADB binary.
- [ ] Archive list/extract/pack handles paths containing spaces and shell metacharacters safely.
- [ ] Frida UI remains usable when Frida is absent and runs only explicitly requested scripts when installed.

## Distribution and licensing

- [x] Remove unverified bundled JAR/native executables from the production source tree.
- [x] Remove unsupported legacy/circumvention-specific plugins from the production baseline.
- [x] Add a project-level proprietary license notice.
- [x] Replace PyQt6 with PySide6 so Qt licensing can follow an explicit Qt for Python licensing path.
- [x] Add a third-party notices document describing external and optional integrations.
- [ ] Decide for each commercial release whether Qt/PySide6 is distributed under LGPLv3 compliance or an applicable Qt commercial license.
- [ ] If distributing PySide6/Qt binaries, include all license texts, notices, and relinking/replacement mechanisms required by the selected licensing path.
- [ ] Re-audit every exact third-party file added to a standalone installer. Do not rely only on a project name or upstream license family.
- [ ] Add customer-facing purchase/EULA terms reviewed for the actual seller and distribution model.
- [ ] Create signed release artifacts and publish cryptographic checksums.
- [ ] Produce an SBOM or equivalent dependency manifest for the exact release artifact.

## Functional scope

- [x] Remove unfinished EXE patcher and duplicate legacy toolkit from the maintained baseline.
- [x] Remove the APK circumvention patcher from the maintained production baseline.
- [x] Remove SSL-unpin/root-bypass templates from the maintained Frida plugin.
- [ ] Test each supported plugin against controlled, authorized fixtures.
- [ ] Do not advertise features that have not passed reproducible tests.

## Release packaging

- [ ] Build reproducible Windows and Linux release artifacts from CI.
- [ ] Smoke-test those artifacts on clean machines or clean VMs.
- [ ] Verify no development files, secrets, private paths, temporary scripts, or unlicensed binaries are included.
- [ ] Sign release binaries/installers using the seller's code-signing identity where applicable.
- [ ] Archive the source commit, build metadata, dependency lock/manifest, checksums, and notices for each released version.

A release should not be called production-ready or commercially redistributable until the applicable unchecked items above have been completed for that exact release artifact.
