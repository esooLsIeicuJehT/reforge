from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOTS = [PROJECT_ROOT / "core", PROJECT_ROOT / "gui", PROJECT_ROOT / "plugins"]


def _python_sources():
    yield PROJECT_ROOT / "main.py"
    for root in SOURCE_ROOTS:
        yield from root.rglob("*.py")


def test_no_pyqt6_or_shell_true_in_production_sources():
    violations = []
    for path in _python_sources():
        text = path.read_text(encoding="utf-8")
        if "PyQt6" in text:
            violations.append(f"{path.relative_to(PROJECT_ROOT)} imports PyQt6")
        compact = text.replace(" ", "")
        if "shell=True" in compact:
            violations.append(f"{path.relative_to(PROJECT_ROOT)} uses shell=True")
    assert violations == []


def test_no_bundled_jar_files():
    jars = sorted(path.relative_to(PROJECT_ROOT) for path in PROJECT_ROOT.rglob("*.jar"))
    assert jars == []


def test_retired_plugins_are_not_shipped():
    retired = ["apk_patcher", "exe_patcher", "re_toolkit"]
    present = [name for name in retired if (PROJECT_ROOT / "plugins" / name).exists()]
    assert present == []


def test_frida_templates_exclude_bypass_presets():
    source = (PROJECT_ROOT / "plugins" / "frida_tools" / "plugin.py").read_text(
        encoding="utf-8"
    )
    forbidden = ["SSL Unpin", "Root Detection Bypass"]
    assert [term for term in forbidden if term in source] == []
