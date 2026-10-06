# ReForge release checklist

This checklist separates code readiness from commercial/legal readiness.

## Automated gates

- [ ] GitHub Actions CI is green.
- [ ] `python -m pip check` passes.
- [ ] `python -m compileall -q core gui plugins main.py` passes.
- [ ] `pytest` passes.

## Desktop/runtime smoke test

Run on every supported OS:

- [ ] Application launches from a clean virtual environment.
- [ ] Missing optional external tools fail gracefully instead of crashing startup.
- [ ] Plugin load failures are visible in logs and do not prevent healthy plugins from loading.
- [ ] Closing the app stops plugin timers/workers and exits cleanly.
- [ ] ADB device refresh works with no device, one device, and an unavailable ADB binary.
- [ ] Archive list/extract/pack handles paths containing spaces and shell metacharacters safely.

## Distribution blockers

- [ ] Select and add a project license before commercial redistribution.
- [ ] Verify the provenance, exact versions, licenses, and redistribution terms for every bundled binary/JAR.
- [ ] Add third-party notices required by those dependencies.
- [ ] Replace or remove any bundled binary whose origin/version cannot be verified.
- [ ] Create signed release artifacts and publish checksums.
- [ ] Document supported Python and operating-system versions from tested results.

## Functional scope

- [ ] Remove unfinished plugins from release builds or complete them with real tests.
- [ ] Test each plugin against controlled, authorized fixtures.
- [ ] Do not advertise features that have not passed reproducible tests.

A release should not be called production-ready or commercially redistributable until every distribution blocker above is resolved.
