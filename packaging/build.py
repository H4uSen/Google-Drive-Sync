#!/usr/bin/env python3
"""Build script for Obsidian GDrive Sync standalone executable."""
import sys
import subprocess
from pathlib import Path
import argparse

ROOT_DIR = Path(__file__).resolve().parent.parent
PACKAGING_DIR = ROOT_DIR / "packaging"
SPEC_FILE = PACKAGING_DIR / "obsidian-gdrive-sync.spec"

def run_build(clean: bool = True, distpath: str | None = None, workpath: str | None = None) -> int:
    cmd = [sys.executable, "-m", "PyInstaller"]
    if clean:
        cmd.append("--clean")
    if distpath:
        cmd.extend(["--distpath", distpath])
    if workpath:
        cmd.extend(["--workpath", workpath])
    cmd.append(str(SPEC_FILE))

    print(f"Executing: {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=str(ROOT_DIR))
    return result.returncode

def main():
    parser = argparse.ArgumentParser(description="Build standalone binary for Obsidian GDrive Sync")
    parser.add_argument("--clean", action="store_true", default=True, help="Clean cache before building")
    parser.add_argument("--distpath", type=str, default=str(ROOT_DIR / "dist"), help="Where to output binary")
    parser.add_argument("--workpath", type=str, default=str(ROOT_DIR / "build"), help="Where to put temp files")
    args = parser.parse_args()

    ret = run_build(clean=args.clean, distpath=args.distpath, workpath=args.workpath)
    if ret == 0:
        print(f"\nBuild complete! Executable located in: {args.distpath}")
    else:
        print(f"\nBuild failed with exit code: {ret}", file=sys.stderr)
    sys.exit(ret)

if __name__ == "__main__":
    main()
