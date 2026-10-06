# Third-party notices

ReForge keeps third-party executables out of the source distribution whenever
possible. External command-line tools such as ADB, Fastboot, 7-Zip, JEB, and
Frida targets are expected to be installed or licensed separately unless a
future release explicitly states otherwise.

## Qt for Python / PySide6

ReForge uses **PySide6**, the official Qt for Python bindings. The community
edition is offered under LGPLv3/GPLv3 terms, with commercial Qt licensing also
available.

Upstream licensing documentation:

- https://doc.qt.io/qtforpython-6/
- https://doc.qt.io/qt-6/licensing.html
- https://doc.qt.io/qtforpython-6/licenses.html

A distributor choosing the LGPL path is responsible for satisfying all
applicable LGPLv3 obligations and any notices for Qt/PySide third-party
components actually shipped in the distribution. A distributor using a Qt
commercial license must follow the applicable commercial agreement instead.

## Optional Frida tools

Frida support is an optional ReForge integration. `frida-tools` is not a
required ReForge dependency and is not bundled in this repository. Users may
install an appropriate Frida toolchain separately for authorized dynamic
instrumentation workflows.

## External tools

ReForge may interoperate with separately installed tools such as:

- Android Debug Bridge (ADB) and Fastboot
- 7-Zip / 7za
- JEB, when separately licensed and configured by the user

Those products are not part of ReForge and remain subject to their respective
licenses and distribution terms.

Before creating a standalone installer, re-audit the exact files included in
the installer and add every notice or license text required by those files.
