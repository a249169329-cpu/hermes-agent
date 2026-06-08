#!/usr/bin/env python3
"""Check or repair the Hermes WebUI local browser runtime overlay.

This script is intentionally a short-term, idempotent operational repair for
slim WebUI/container installs where agent-browser's managed Chrome exists but
its shared-library/font dependencies, Fontconfig tree, or Chrome wrapper were
lost or overwritten. It does not restart WebUI and does not change Dockerfiles.
"""

from __future__ import annotations

import argparse
import glob
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field

RUNTIME_MARKER = "HERMES_BROWSER_RUNTIME_WRAPPER=1"

DEFAULT_PACKAGES = (
    "fontconfig",
    "fonts-noto-cjk",
    "fonts-wqy-microhei",
    "fonts-wqy-zenhei",
    "gsettings-desktop-schemas",
    "libasound2",
    "libatk-bridge2.0-0",
    "libatk1.0-0",
    "libatspi2.0-0",
    "libcairo2",
    "libcups2",
    "libdrm2",
    "libfontconfig1",
    "libgbm1",
    "libglib2.0-0",
    "libgtk-3-0",
    "libnspr4",
    "libnss3",
    "libpango-1.0-0",
    "libx11-6",
    "libxcb1",
    "libxcomposite1",
    "libxdamage1",
    "libxext6",
    "libxfixes3",
    "libxkbcommon0",
    "libxrandr2",
)

# Debian/Ubuntu package names differ across releases. Verification is file-based
# so either package name is acceptable when the files are already present.
PACKAGE_ALIASES = {
    "libasound2": ("libasound2", "libasound2t64"),
    "libglib2.0-0": ("libglib2.0-0", "libglib2.0-0t64"),
    "libgtk-3-0": ("libgtk-3-0", "libgtk-3-0t64"),
}

KEY_LIB_PATTERNS = (
    "usr/lib/**/libnss3.so",
    "usr/lib/**/libnspr4.so",
    "usr/lib/**/libfontconfig.so.*",
    "usr/lib/**/libgbm.so.*",
    "usr/lib/**/libxkbcommon.so.*",
    "usr/lib/**/libasound.so.*",
    "usr/lib/**/libatk-1.0.so.*",
    "usr/lib/**/libatk-bridge-2.0.so.*",
    "usr/lib/**/libatspi.so.*",
    "usr/lib/**/libcairo.so.*",
    "usr/lib/**/libcups.so.*",
    "usr/lib/**/libdrm.so.*",
    "usr/lib/**/libgio-2.0.so.*",
    "usr/lib/**/libglib-2.0.so.*",
    "usr/lib/**/libgobject-2.0.so.*",
    "usr/lib/**/libgtk-3.so.*",
    "usr/lib/**/libgdk-3.so.*",
    "usr/lib/**/libpango-1.0.so.*",
    "usr/lib/**/libpangocairo-1.0.so.*",
    "usr/lib/**/libX11.so.*",
    "usr/lib/**/libxcb.so.*",
    "usr/lib/**/libXcomposite.so.*",
    "usr/lib/**/libXdamage.so.*",
    "usr/lib/**/libXext.so.*",
    "usr/lib/**/libXfixes.so.*",
    "usr/lib/**/libXrandr.so.*",
)

CJK_FONT_PATTERNS = (
    "usr/share/fonts/**/NotoSansCJK*.ttc",
    "usr/share/fonts/**/NotoSansCJK*.otf",
    "usr/share/fonts/**/NotoSerifCJK*.ttc",
    "usr/share/fonts/**/NotoSerifCJK*.otf",
    "usr/share/fonts/**/wqy-*.ttc",
    "usr/share/fonts/**/wqy-*.ttf",
    "usr/share/fonts/**/uming*.ttc",
    "usr/share/fonts/**/ukai*.ttc",
)

STATIC_LIBRARY_DIRS = (
    "usr/lib/x86_64-linux-gnu",
    "usr/lib",
    "lib/x86_64-linux-gnu",
    "lib",
)


@dataclass
class Finding:
    ok: bool
    code: str
    message: str


@dataclass
class CheckResult:
    ok: bool
    findings: list[Finding] = field(default_factory=list)
    actions: list[str] = field(default_factory=list)

    def add(self, ok: bool, code: str, message: str) -> None:
        self.findings.append(Finding(ok=ok, code=code, message=message))
        self.ok = self.ok and ok

    def merge(self, other: "CheckResult") -> None:
        self.ok = self.ok and other.ok
        self.findings.extend(other.findings)
        self.actions.extend(other.actions)


def _default_hermes_home(env: dict[str, str] | None = None) -> Path:
    env = env or os.environ
    return Path(env.get("HERMES_HOME") or Path.home() / ".hermes").expanduser()


def default_runtime_base(env: dict[str, str] | None = None) -> Path:
    env = env or os.environ
    override = env.get("HERMES_BROWSER_RUNTIME_LIBS")
    if override:
        return Path(override).expanduser()
    return _default_hermes_home(env) / "browser-runtime-libs"


def default_package_root(runtime_base: Path) -> Path:
    return runtime_base / "root"


def _version_key(name: str) -> tuple[int | str, ...]:
    parts: list[int | str] = []
    for part in re.split(r"([0-9]+)", name):
        if part:
            parts.append(int(part) if part.isdigit() else part)
    return tuple(parts)


def default_chrome_path(home: Path | None = None) -> Path | None:
    home = home.expanduser() if home else Path.home()
    browser_root = home / ".agent-browser" / "browsers"
    candidates = [
        path / "chrome"
        for path in browser_root.glob("chrome-*")
        if path.is_dir() and (path / "chrome").exists()
    ]
    if not candidates:
        return None
    return sorted(candidates, key=lambda path: _version_key(path.parent.name))[-1]


def _is_elf(path: Path) -> bool:
    try:
        with path.open("rb") as fp:
            return fp.read(4) == b"\x7fELF"
    except OSError:
        return False


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def is_wrapper_ok(chrome: Path, package_root: Path) -> bool:
    if not chrome.is_file():
        return False
    chrome_real = chrome.with_name("chrome.real")
    text = _read_text(chrome)
    required_exports = (
        "LD_LIBRARY_PATH",
        "FONTCONFIG_PATH",
        "FONTCONFIG_FILE",
        "XDG_DATA_DIRS",
        "GSETTINGS_SCHEMA_DIR",
    )
    # Accept both wrappers produced by this script and the earlier live emergency
    # wrapper. The marker is useful for future repair runs, but requiring it would
    # overwrite a known-good live wrapper unnecessarily.
    return (
        all(item in text for item in required_exports)
        and "chrome.real" in text
        and str(package_root) in text
        and chrome_real.is_file()
    )


def _glob_any(root: Path, patterns: tuple[str, ...]) -> bool:
    for pattern in patterns:
        if glob.glob(str(root / pattern), recursive=True):
            return True
    return False


def _static_library_path(package_root: Path) -> str:
    return ":".join(str(package_root / item) for item in STATIC_LIBRARY_DIRS)


def wrapper_text(package_root: Path) -> str:
    root = str(package_root)
    return f"""#!/bin/sh
# {RUNTIME_MARKER}
set -eu
HERE="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
CHROME_REAL="$HERE/chrome.real"
HERMES_BROWSER_LIB_ROOT="{root}"
export LD_LIBRARY_PATH="{_static_library_path(package_root)}${{LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}}"
export FONTCONFIG_PATH="$HERMES_BROWSER_LIB_ROOT/etc/fonts"
export FONTCONFIG_FILE="$HERMES_BROWSER_LIB_ROOT/etc/fonts/fonts.conf"
export XDG_DATA_DIRS="$HERMES_BROWSER_LIB_ROOT/usr/share:${{XDG_DATA_DIRS:-/usr/local/share:/usr/share}}"
export GSETTINGS_SCHEMA_DIR="$HERMES_BROWSER_LIB_ROOT/usr/share/glib-2.0/schemas"
exec "$CHROME_REAL" "$@"
"""


def check_runtime_base(runtime_base: Path) -> CheckResult:
    result = CheckResult(ok=True)
    if not runtime_base.exists():
        result.add(False, "runtime_base_missing", f"Runtime base directory missing: {runtime_base}")
        return result
    if not runtime_base.is_dir():
        result.add(False, "runtime_base_not_dir", f"Runtime base path is not a directory: {runtime_base}")
        return result
    mode = stat.S_IMODE(runtime_base.stat().st_mode)
    result.add(
        mode & 0o077 == 0,
        "runtime_base_permissions",
        f"Runtime base permissions are {mode:o}; expected no group/other bits",
    )
    return result


def check_package_root(package_root: Path) -> CheckResult:
    result = CheckResult(ok=True)
    if not package_root.exists():
        result.add(False, "package_root_missing", f"Extracted package root missing: {package_root}")
        return result
    if not package_root.is_dir():
        result.add(False, "package_root_not_dir", f"Extracted package root is not a directory: {package_root}")
        return result
    result.add(
        (package_root / "etc" / "fonts" / "fonts.conf").is_file(),
        "fontconfig_conf",
        "Fontconfig configuration etc/fonts/fonts.conf is present",
    )
    result.add(
        _glob_any(package_root, CJK_FONT_PATTERNS),
        "cjk_fonts",
        "At least one CJK font file is present",
    )
    for pattern in KEY_LIB_PATTERNS:
        result.add(
            bool(glob.glob(str(package_root / pattern), recursive=True)),
            f"lib:{pattern}",
            f"Required shared library pattern present: {pattern}",
        )
    return result


def check_chrome_wrapper(chrome: Path | None, package_root: Path) -> CheckResult:
    result = CheckResult(ok=True)
    if chrome is None:
        result.add(False, "chrome_missing", "No agent-browser Chrome launcher found")
        return result
    chrome_real = chrome.with_name("chrome.real")
    if is_wrapper_ok(chrome, package_root):
        result.add(True, "wrapper_ok", f"Chrome wrapper already OK: {chrome}")
        return result
    if _is_elf(chrome):
        if chrome_real.exists():
            result.add(False, "wrapper_overwritten", "Chrome wrapper was overwritten by an ELF binary; chrome.real already exists")
        else:
            result.add(False, "chrome_elf_needs_preserve", "Chrome is an ELF binary and needs to be preserved as chrome.real")
        return result
    if chrome_real.is_file():
        result.add(False, "wrapper_needs_repair", "Chrome wrapper is missing or stale; chrome.real exists")
        return result
    result.add(False, "chrome_unusable", f"Chrome launcher is not repairable without chrome.real: {chrome}")
    return result


def extract_packages(package_root: Path, packages: tuple[str, ...] = DEFAULT_PACKAGES) -> list[str]:
    if shutil.which("apt-get") is None:
        raise RuntimeError("apt-get is required to download runtime packages")
    if shutil.which("dpkg-deb") is None:
        raise RuntimeError("dpkg-deb is required to extract runtime packages")

    extracted: list[str] = []
    with tempfile.TemporaryDirectory(prefix="hermes-browser-runtime-") as tmp:
        tmp_path = Path(tmp)
        for package in packages:
            names = PACKAGE_ALIASES.get(package, (package,))
            deb_path: Path | None = None
            errors: list[str] = []
            for name in names:
                proc = subprocess.run(
                    ["apt-get", "download", name],
                    cwd=tmp_path,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE,
                    text=True,
                    check=False,
                )
                if proc.returncode == 0:
                    matches = sorted(tmp_path.glob(f"{name}_*.deb"))
                    if matches:
                        deb_path = matches[-1]
                        break
                if proc.stderr:
                    errors.append(proc.stderr.strip().splitlines()[-1])
            if deb_path is None:
                detail = "; ".join(errors)
                raise RuntimeError(f"apt-get download failed for {package}: {detail}")
            subprocess.run(["dpkg-deb", "-x", str(deb_path), str(package_root)], check=True)
            extracted.append(package)
    return extracted


def repair_runtime(runtime_base: Path, package_root: Path, *, allow_download: bool = True) -> CheckResult:
    runtime_base.mkdir(parents=True, exist_ok=True)
    os.chmod(runtime_base, 0o700)
    package_root.mkdir(parents=True, exist_ok=True)
    result = CheckResult(ok=True)
    result.merge(check_runtime_base(runtime_base))
    result.merge(check_package_root(package_root))
    if result.ok:
        return result
    if not allow_download:
        result.actions.append("download_skipped")
        return result
    extracted = extract_packages(package_root)
    result = CheckResult(ok=True)
    result.merge(check_runtime_base(runtime_base))
    result.merge(check_package_root(package_root))
    result.actions.append("extracted:" + ",".join(extracted))
    return result


def _unique_backup_path(path: Path) -> Path:
    base = path.with_name(f"{path.name}.overwritten")
    if not base.exists():
        return base
    for index in range(1, 1000):
        candidate = path.with_name(f"{path.name}.overwritten.{index}")
        if not candidate.exists():
            return candidate
    raise RuntimeError(f"could not allocate backup path for overwritten {path}")


def repair_chrome_wrapper(chrome: Path | None, package_root: Path) -> CheckResult:
    if chrome is None:
        return check_chrome_wrapper(chrome, package_root)
    chrome_real = chrome.with_name("chrome.real")
    actions: list[str] = []
    if is_wrapper_ok(chrome, package_root):
        return check_chrome_wrapper(chrome, package_root)
    if _is_elf(chrome):
        if not chrome_real.exists():
            chrome.rename(chrome_real)
            actions.append("preserved_chrome_real")
        else:
            backup_path = _unique_backup_path(chrome)
            chrome.rename(backup_path)
            actions.append(f"backed_up_overwritten_chrome:{backup_path}")
    elif not chrome_real.is_file():
        return check_chrome_wrapper(chrome, package_root)
    chrome.write_text(wrapper_text(package_root), encoding="utf-8")
    os.chmod(chrome, 0o755)
    result = check_chrome_wrapper(chrome, package_root)
    result.actions.extend(actions)
    if result.ok:
        result.actions.append("wrote_chrome_wrapper")
    return result


def run_check(runtime_base: Path, package_root: Path, chrome: Path | None) -> CheckResult:
    result = CheckResult(ok=True)
    result.merge(check_runtime_base(runtime_base))
    result.merge(check_package_root(package_root))
    result.merge(check_chrome_wrapper(chrome, package_root))
    return result


def run_repair(runtime_base: Path, package_root: Path, chrome: Path | None, *, allow_download: bool = True) -> CheckResult:
    result = CheckResult(ok=True)
    result.merge(repair_runtime(runtime_base, package_root, allow_download=allow_download))
    result.merge(repair_chrome_wrapper(chrome, package_root))
    return result


def print_result(result: CheckResult) -> None:
    for finding in result.findings:
        prefix = "OK" if finding.ok else "MISSING"
        print(f"{prefix} {finding.code}: {finding.message}")
    for action in result.actions:
        print(f"ACTION {action}")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Check or repair Hermes WebUI browser runtime libraries and Chrome wrapper without restarting WebUI."
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="Check only; do not mutate files (default).")
    mode.add_argument("--repair", "--apply", dest="repair", action="store_true", help="Apply idempotent runtime repairs.")
    parser.add_argument("--runtime-libs", type=Path, default=None, help="Runtime base directory. Default: $HERMES_HOME/browser-runtime-libs.")
    parser.add_argument("--package-root", type=Path, default=None, help="Extracted package root. Default: <runtime-libs>/root.")
    parser.add_argument("--chrome", type=Path, default=None, help="Chrome launcher path. Default: newest $HOME/.agent-browser/browsers/chrome-*/chrome.")
    parser.add_argument("--home", type=Path, default=None, help="Home directory used for default Chrome discovery.")
    parser.add_argument("--no-download", action="store_true", help="In repair mode, do not run apt-get download.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    runtime_base = (args.runtime_libs or default_runtime_base()).expanduser()
    package_root = (args.package_root or default_package_root(runtime_base)).expanduser()
    chrome = args.chrome.expanduser() if args.chrome else default_chrome_path(args.home)
    if args.repair:
        result = run_repair(runtime_base, package_root, chrome, allow_download=not args.no_download)
    else:
        result = run_check(runtime_base, package_root, chrome)
    print_result(result)
    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
