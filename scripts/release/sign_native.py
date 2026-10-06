"""Optional native code-signing hook for seller-provided identities.

No signing secrets are stored in the repository. CI calls this script only when
all required platform secrets are configured.
"""
from __future__ import annotations

import base64
import os
import platform
import shutil
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEPLOY_ROOT = ROOT / "deployment"
LEGACY_BUILD_ROOT = ROOT / "build" / "native"


def _run(
    cmd: list[str],
    *,
    env: dict[str, str] | None = None,
    sensitive_values: tuple[str, ...] = (),
) -> None:
    secrets = {value for value in sensitive_values if value}
    printable = ["***" if part in secrets else part for part in cmd]
    print("+", " ".join(printable), flush=True)
    subprocess.run(cmd, check=True, env=env)


def _roots() -> tuple[Path, ...]:
    return tuple(root for root in (DEPLOY_ROOT, LEGACY_BUILD_ROOT) if root.exists())


def _find_signtool() -> Path:
    direct = shutil.which("signtool") or shutil.which("signtool.exe")
    if direct:
        return Path(direct)

    roots = [
        Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"))
        / "Windows Kits"
        / "10"
        / "bin"
    ]
    candidates: list[Path] = []
    for root in roots:
        if root.exists():
            candidates.extend(root.glob("*/x64/signtool.exe"))
    if not candidates:
        raise RuntimeError("signtool.exe was not found")
    return sorted(candidates)[-1]


def _sign_windows() -> None:
    cert_b64 = os.environ["WINDOWS_CERTIFICATE_BASE64"]
    password = os.environ["WINDOWS_CERTIFICATE_PASSWORD"]
    timestamp_url = os.getenv("WINDOWS_TIMESTAMP_URL", "http://timestamp.digicert.com")
    targets = sorted({path.resolve() for root in _roots() for path in root.rglob("*.exe")})
    if not targets:
        raise RuntimeError("No Windows executable found to sign")

    signtool = _find_signtool()
    with tempfile.TemporaryDirectory(prefix="reforge-sign-") as temp_dir:
        cert = Path(temp_dir) / "certificate.pfx"
        cert.write_bytes(base64.b64decode(cert_b64))
        for target in targets:
            _run(
                [
                    str(signtool),
                    "sign",
                    "/fd",
                    "SHA256",
                    "/td",
                    "SHA256",
                    "/tr",
                    timestamp_url,
                    "/f",
                    str(cert),
                    "/p",
                    password,
                    str(target),
                ],
                sensitive_values=(password,),
            )


def _sign_macos() -> None:
    cert_b64 = os.environ["APPLE_CERTIFICATE_BASE64"]
    cert_password = os.environ["APPLE_CERTIFICATE_PASSWORD"]
    identity = os.environ["APPLE_SIGNING_IDENTITY"]
    targets = sorted({path.resolve() for root in _roots() for path in root.glob("*.app")})
    if not targets:
        raise RuntimeError("No macOS .app bundle found to sign")

    with tempfile.TemporaryDirectory(prefix="reforge-sign-") as temp_dir:
        temp = Path(temp_dir)
        cert = temp / "certificate.p12"
        keychain = temp / "signing.keychain-db"
        keychain_password = base64.urlsafe_b64encode(os.urandom(24)).decode("ascii")
        cert.write_bytes(base64.b64decode(cert_b64))
        keychain_secret = (keychain_password,)

        _run(
            ["security", "create-keychain", "-p", keychain_password, str(keychain)],
            sensitive_values=keychain_secret,
        )
        _run(["security", "set-keychain-settings", "-lut", "21600", str(keychain)])
        _run(
            ["security", "unlock-keychain", "-p", keychain_password, str(keychain)],
            sensitive_values=keychain_secret,
        )
        _run(
            [
                "security",
                "import",
                str(cert),
                "-P",
                cert_password,
                "-A",
                "-t",
                "cert",
                "-f",
                "pkcs12",
                "-k",
                str(keychain),
            ],
            sensitive_values=(cert_password,),
        )
        _run(
            [
                "security",
                "set-key-partition-list",
                "-S",
                "apple-tool:,apple:,codesign:",
                "-s",
                "-k",
                keychain_password,
                str(keychain),
            ],
            sensitive_values=keychain_secret,
        )

        env = os.environ.copy()
        existing = subprocess.run(
            ["security", "list-keychains", "-d", "user"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.replace('"', "").split()
        _run(["security", "list-keychains", "-d", "user", "-s", str(keychain), *existing])

        for target in targets:
            _run(
                [
                    "codesign",
                    "--force",
                    "--deep",
                    "--options",
                    "runtime",
                    "--timestamp",
                    "--keychain",
                    str(keychain),
                    "--sign",
                    identity,
                    str(target),
                ],
                env=env,
            )
            _run(["codesign", "--verify", "--deep", "--strict", "--verbose=2", str(target)])


def main() -> int:
    system = platform.system()
    if system == "Windows":
        _sign_windows()
    elif system == "Darwin":
        _sign_macos()
    else:
        raise SystemExit("Native signing hook is only applicable to Windows and macOS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
