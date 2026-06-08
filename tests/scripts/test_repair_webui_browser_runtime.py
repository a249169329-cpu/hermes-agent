from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import sys


SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "runtime" / "repair_webui_browser_runtime.py"
spec = importlib.util.spec_from_file_location("repair_webui_browser_runtime", SCRIPT)
repair = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = repair
assert spec.loader is not None
spec.loader.exec_module(repair)


def _runtime_fixture(root: Path) -> None:
    (root / "etc" / "fonts").mkdir(parents=True)
    (root / "etc" / "fonts" / "fonts.conf").write_text("<fontconfig/>", encoding="utf-8")
    (root / "usr" / "share" / "fonts" / "truetype" / "wqy").mkdir(parents=True)
    (root / "usr" / "share" / "fonts" / "truetype" / "wqy" / "wqy-microhei.ttc").write_bytes(b"font")
    libdir = root / "usr" / "lib" / "x86_64-linux-gnu"
    libdir.mkdir(parents=True)
    for name in (
        "libnss3.so",
        "libnspr4.so",
        "libfontconfig.so.1",
        "libgbm.so.1",
        "libxkbcommon.so.0",
        "libasound.so.2",
        "libatk-1.0.so.0",
        "libatk-bridge-2.0.so.0",
        "libatspi.so.0",
        "libcairo.so.2",
        "libcups.so.2",
        "libdrm.so.2",
        "libgio-2.0.so.0",
        "libglib-2.0.so.0",
        "libgobject-2.0.so.0",
        "libgtk-3.so.0",
        "libgdk-3.so.0",
        "libpango-1.0.so.0",
        "libpangocairo-1.0.so.0",
        "libX11.so.6",
        "libxcb.so.1",
        "libXcomposite.so.1",
        "libXdamage.so.1",
        "libXext.so.6",
        "libXfixes.so.3",
        "libXrandr.so.2",
    ):
        (libdir / name).write_bytes(b"lib")


def _chrome(home: Path, version: str = "chrome-149.0.7827.22") -> Path:
    chrome_dir = home / ".agent-browser" / "browsers" / version
    chrome_dir.mkdir(parents=True)
    return chrome_dir / "chrome"


def test_default_paths_use_hermes_home_and_newest_agent_browser_chrome(tmp_path, monkeypatch):
    hermes_home = tmp_path / "hermes"
    home = tmp_path / "home"
    old = _chrome(home, "chrome-100.0.0")
    new = _chrome(home, "chrome-149.0.7827.22")
    old.write_bytes(b"\x7fELFold")
    new.write_bytes(b"\x7fELFnew")

    monkeypatch.setenv("HERMES_HOME", str(hermes_home))
    monkeypatch.setattr(repair.Path, "home", lambda: home)

    assert repair.default_runtime_base() == hermes_home / "browser-runtime-libs"
    assert repair.default_package_root(hermes_home / "browser-runtime-libs") == hermes_home / "browser-runtime-libs" / "root"
    assert repair.default_chrome_path() == new


def test_check_mode_does_not_create_missing_runtime_or_repair_chrome(tmp_path):
    runtime_base = tmp_path / "browser-runtime-libs"
    package_root = runtime_base / "root"
    chrome = _chrome(tmp_path / "home")
    chrome.write_bytes(b"\x7fELFfake")

    result = repair.run_check(runtime_base, package_root, chrome)

    assert not result.ok
    assert not runtime_base.exists()
    assert not chrome.with_name("chrome.real").exists()
    assert chrome.read_bytes() == b"\x7fELFfake"
    assert {finding.code for finding in result.findings} >= {
        "runtime_base_missing",
        "package_root_missing",
        "chrome_elf_needs_preserve",
    }


def test_repair_preserves_elf_as_chrome_real_and_writes_idempotent_wrapper(tmp_path):
    runtime_base = tmp_path / "browser-runtime-libs"
    package_root = runtime_base / "root"
    runtime_base.mkdir()
    os.chmod(runtime_base, 0o777)
    _runtime_fixture(package_root)
    chrome = _chrome(tmp_path / "home")
    chrome.write_bytes(b"\x7fELFfake")

    first = repair.run_repair(runtime_base, package_root, chrome, allow_download=False)
    wrapper_once = chrome.read_text(encoding="utf-8")
    second = repair.run_repair(runtime_base, package_root, chrome, allow_download=False)

    assert first.ok
    assert second.ok
    assert chrome.with_name("chrome.real").read_bytes() == b"\x7fELFfake"
    assert chrome.read_text(encoding="utf-8") == wrapper_once
    assert "HERMES_BROWSER_RUNTIME_WRAPPER=1" in wrapper_once
    assert f'HERMES_BROWSER_LIB_ROOT="{package_root}"' in wrapper_once
    for exported in (
        "LD_LIBRARY_PATH",
        "FONTCONFIG_PATH",
        "FONTCONFIG_FILE",
        "XDG_DATA_DIRS",
        "GSETTINGS_SCHEMA_DIR",
    ):
        assert exported in wrapper_once
    assert oct(runtime_base.stat().st_mode & 0o777) == "0o700"


def test_repair_recreates_wrapper_when_agent_browser_overwrites_chrome(tmp_path):
    runtime_base = tmp_path / "browser-runtime-libs"
    package_root = runtime_base / "root"
    runtime_base.mkdir(mode=0o700)
    _runtime_fixture(package_root)
    chrome = _chrome(tmp_path / "home")
    chrome_real = chrome.with_name("chrome.real")
    chrome_real.write_bytes(b"\x7fELForiginal")
    chrome.write_bytes(b"\x7fELFoverwritten")

    result = repair.run_repair(runtime_base, package_root, chrome, allow_download=False)

    assert result.ok
    assert chrome_real.read_bytes() == b"\x7fELForiginal"
    assert chrome.with_name("chrome.overwritten").read_bytes() == b"\x7fELFoverwritten"
    assert repair.is_wrapper_ok(chrome, package_root)
    assert not repair._is_elf(chrome)


def test_missing_non_minimal_chrome_library_is_not_considered_ok(tmp_path):
    runtime_base = tmp_path / "browser-runtime-libs"
    package_root = runtime_base / "root"
    runtime_base.mkdir(mode=0o700)
    _runtime_fixture(package_root)
    (package_root / "usr" / "lib" / "x86_64-linux-gnu" / "libgtk-3.so.0").unlink()

    result = repair.check_package_root(package_root)

    assert not result.ok
    assert any(finding.code == "lib:usr/lib/**/libgtk-3.so.*" and not finding.ok for finding in result.findings)


def test_existing_legacy_live_wrapper_is_accepted_without_marker(tmp_path):
    runtime_base = tmp_path / "browser-runtime-libs"
    package_root = runtime_base / "root"
    runtime_base.mkdir(mode=0o700)
    _runtime_fixture(package_root)
    chrome = _chrome(tmp_path / "home")
    chrome.with_name("chrome.real").write_bytes(b"\x7fELForiginal")
    chrome.write_text(
        f"""#!/bin/sh
HERMES_BROWSER_LIB_ROOT='{package_root}'
export LD_LIBRARY_PATH="$HERMES_BROWSER_LIB_ROOT/usr/lib/x86_64-linux-gnu:$HERMES_BROWSER_LIB_ROOT/usr/lib:${{LD_LIBRARY_PATH:-}}"
export FONTCONFIG_PATH="$HERMES_BROWSER_LIB_ROOT/etc/fonts"
export FONTCONFIG_FILE="$HERMES_BROWSER_LIB_ROOT/etc/fonts/fonts.conf"
export XDG_DATA_DIRS="$HERMES_BROWSER_LIB_ROOT/usr/share:${{XDG_DATA_DIRS:-/usr/local/share:/usr/share}}"
export GSETTINGS_SCHEMA_DIR="$HERMES_BROWSER_LIB_ROOT/usr/share/glib-2.0/schemas"
exec '{chrome.with_name('chrome.real')}' "$@"
""",
        encoding="utf-8",
    )

    before = chrome.read_text(encoding="utf-8")
    result = repair.run_repair(runtime_base, package_root, chrome, allow_download=False)

    assert result.ok
    assert chrome.read_text(encoding="utf-8") == before
    assert repair.is_wrapper_ok(chrome, package_root)


def test_repair_no_download_reports_missing_dependencies_without_network(tmp_path):
    runtime_base = tmp_path / "browser-runtime-libs"
    package_root = runtime_base / "root"
    chrome = _chrome(tmp_path / "home")
    chrome.write_bytes(b"\x7fELFfake")

    result = repair.run_repair(runtime_base, package_root, chrome, allow_download=False)

    assert not result.ok
    assert runtime_base.exists()
    assert package_root.exists()
    assert "download_skipped" in result.actions
    assert any(finding.code == "fontconfig_conf" and not finding.ok for finding in result.findings)
