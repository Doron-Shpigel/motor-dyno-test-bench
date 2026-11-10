#!/usr/bin/env python3
"""
Release Packaging Script for Motor Dyno Test Bench.

Creates cross-platform distribution archives ready for GitHub Releases:
- dist/motor-dyno-test-bench-{version}-linux.tar.gz
- dist/motor-dyno-test-bench-{version}-windows.zip
- dist/sha256sums.txt

Usage:
    python scripts/package_release.py [--version v2.0.0] [--output-dir dist]
"""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import os
import shutil
import stat
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Primary files and directories to package
INCLUDED_FILES = [
    "main.py",
    "tui.py",
    "install.sh",
    "install.bat",
    "run.sh",
    "run.bat",
    "run_tui.sh",
    "run_tui.bat",
    "requirements.txt",
    "environment.yml",
    "pytest.ini",
    "LICENSE",
    "README.md",
]

INCLUDED_DIRS = [
    "modules",
    "gui",
    "assets",
    "arduino",
    "tests",
    "scripts",
]

# Patterns and directory names to strictly exclude
EXCLUDED_DIR_NAMES = {
    ".git",
    ".github",
    ".env",
    ".venv",
    "env",
    "venv",
    "__pycache__",
    ".pytest_cache",
    "dist",
    "build",
    ".agents",
    "htmlcov",
    ".tox",
    ".nox",
    ".vscode",
    ".idea",
}

EXCLUDED_FILE_PATTERNS = [
    "*.pyc",
    "*.pyo",
    "*.pyd",
    "*.cover",
    ".coverage*",
    "temp_run.csv",
    "temp_*.csv",
    "*.log",
    ".DS_Store",
    "Thumbs.db",
    "*.swp",
    "*.swo",
    "*~",
    "*.tar.gz",
    "*.zip",
]

# Executable file extensions/names (for setting 0755 mode in tar/zip)
EXECUTABLE_TARGETS = {
    "install.sh",
    "run.sh",
    "run_tui.sh",
    "main.py",
    "tui.py",
    "package_release.py",
}


def detect_version(cli_version: str | None) -> str:
    """Resolve release version from CLI, env var, git tag, or fallback."""
    if cli_version:
        ver = cli_version.strip()
        return ver if ver.startswith("v") else f"v{ver}"

    env_ver = os.environ.get("RELEASE_VERSION", "").strip()
    if env_ver:
        return env_ver if env_ver.startswith("v") else f"v{env_ver}"

    # Try git describe / git tag
    try:
        git_desc = subprocess.check_output(
            ["git", "describe", "--tags", "--exact-match"],
            cwd=str(PROJECT_ROOT),
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
        if git_desc:
            return git_desc if git_desc.startswith("v") else f"v{git_desc}"
    except Exception:
        pass

    return "v2.0.0"


def should_exclude(rel_path: Path) -> bool:
    """Check if a file or directory relative path should be excluded."""
    # Check directory parts against EXCLUDED_DIR_NAMES
    for part in rel_path.parts:
        if part in EXCLUDED_DIR_NAMES:
            return True

    filename = rel_path.name
    for pattern in EXCLUDED_FILE_PATTERNS:
        if fnmatch.fnmatch(filename, pattern):
            return True

    return False


def collect_release_files(root: Path) -> list[Path]:
    """Collect all files to include in release, relative to root."""
    collected: list[Path] = []

    # 1. Top-level individual files
    for fname in INCLUDED_FILES:
        target = root / fname
        if target.is_file():
            rel = target.relative_to(root)
            if not should_exclude(rel):
                collected.append(rel)

    # 2. Files inside included directories
    for dname in INCLUDED_DIRS:
        dir_path = root / dname
        if not dir_path.is_dir():
            continue
        for current_root, dirs, files in os.walk(dir_path):
            current_path = Path(current_root)
            # Filter subdirs in-place to avoid descending into excluded dirs
            dirs[:] = [d for d in dirs if d not in EXCLUDED_DIR_NAMES]

            for f in files:
                abs_f = current_path / f
                rel_f = abs_f.relative_to(root)
                if not should_exclude(rel_f):
                    collected.append(rel_f)

    # Sort for deterministic archive contents
    collected.sort()
    return collected


def is_executable(rel_path: Path) -> bool:
    """Determine if a file should have executable permissions."""
    if rel_path.name in EXECUTABLE_TARGETS or rel_path.suffix == ".sh":
        return True
    return False


def create_tar_gz(
    source_root: Path,
    rel_files: list[Path],
    dest_path: Path,
    archive_prefix: str,
) -> None:
    """Create a gzipped tar archive with proper POSIX file permissions."""
    print(f"Creating {dest_path.name}...")
    with tarfile.open(dest_path, "w:gz") as tar:
        for rel in rel_files:
            abs_path = source_root / rel
            arcname = f"{archive_prefix}/{rel.as_posix()}"
            tarinfo = tar.gettarinfo(str(abs_path), arcname=arcname)
            tarinfo.uid = 1000
            tarinfo.gid = 1000
            tarinfo.uname = "dyno"
            tarinfo.gname = "dyno"

            if is_executable(rel):
                tarinfo.mode = 0o755
            else:
                tarinfo.mode = 0o644

            with open(abs_path, "rb") as f:
                tar.addfile(tarinfo, f)


def create_zip(
    source_root: Path,
    rel_files: list[Path],
    dest_path: Path,
    archive_prefix: str,
) -> None:
    """Create a zip archive with executable permission metadata."""
    print(f"Creating {dest_path.name}...")
    with zipfile.ZipFile(dest_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for rel in rel_files:
            abs_path = source_root / rel
            arcname = f"{archive_prefix}/{rel.as_posix()}"
            zinfo = zipfile.ZipInfo.from_file(abs_path, arcname=arcname)

            # Preserve unix file permissions
            if is_executable(rel):
                # 0755 permissions in Unix attribute high 16 bits
                zinfo.external_attr = (stat.S_IFREG | 0o755) << 16
            else:
                zinfo.external_attr = (stat.S_IFREG | 0o644) << 16

            with open(abs_path, "rb") as f:
                zf.writestr(zinfo, f.read())


def compute_sha256(path: Path) -> str:
    """Compute SHA-256 hexadecimal digest of a file."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description="Package Motor Dyno Test Bench Release")
    parser.add_argument("--version", help="Release version (e.g. v2.0.0)")
    parser.add_argument("--output-dir", default="dist", help="Output directory (default: dist)")
    parser.add_argument("--no-clean", action="store_true", help="Do not clean output dir")
    args = parser.parse_args()

    version = detect_version(args.version)
    out_dir = PROJECT_ROOT / args.output_dir
    archive_prefix = f"motor-dyno-test-bench-{version}"

    print(f"=== Packaging Motor Dyno Test Bench {version} ===")
    print(f"Project root: {PROJECT_ROOT}")
    print(f"Output directory: {out_dir}")

    if not args.no_clean and out_dir.exists():
        print(f"Cleaning {out_dir}...")
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    files_to_pack = collect_release_files(PROJECT_ROOT)
    print(f"Collected {len(files_to_pack)} release files.")

    # 1. Create Linux tar.gz
    tar_name = f"motor-dyno-test-bench-{version}-linux.tar.gz"
    tar_path = out_dir / tar_name
    create_tar_gz(PROJECT_ROOT, files_to_pack, tar_path, archive_prefix)

    # 2. Create Windows zip
    zip_name = f"motor-dyno-test-bench-{version}-windows.zip"
    zip_path = out_dir / zip_name
    create_zip(PROJECT_ROOT, files_to_pack, zip_path, archive_prefix)

    # 3. Compute SHA256 checksums
    checksum_lines: list[str] = []
    print("\n--- Checksums (SHA-256) ---")
    for artifact_path in [tar_path, zip_path]:
        sha = compute_sha256(artifact_path)
        size_mb = artifact_path.stat().st_size / (1024 * 1024)
        print(f"{sha}  {artifact_path.name} ({size_mb:.2f} MB)")
        checksum_lines.append(f"{sha}  {artifact_path.name}\n")

    checksum_file = out_dir / "sha256sums.txt"
    checksum_file.write_text("".join(checksum_lines), encoding="utf-8")
    print(f"Wrote checksums to {checksum_file.name}")

    print("\n✓ Release packaging complete!")


if __name__ == "__main__":
    main()
