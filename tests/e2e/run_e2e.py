#!/usr/bin/env python3
"""
Dedicated E2E Test Runner for Obsidian Google Drive Sync.
Executes the 4-tier E2E test suite and outputs structured execution reports.
"""

import sys
import os
import argparse
import subprocess
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description="Run the 4-tier E2E test suite.")
    parser.add_argument("--strict", action="store_true", help="Enforce strict mode (no skips allowed; gate for M5)")
    parser.add_argument("--tier", type=int, choices=[1, 2, 3, 4], help="Run only tests from a specific tier")
    parser.add_argument("-v", "--verbose", action="store_true", help="Verbose pytest output")
    args = parser.parse_args()

    env = os.environ.copy()
    if args.strict:
        env["E2E_STRICT"] = "1"

    repo_root = Path(__file__).resolve().parent.parent.parent
    pytest_bin = repo_root / ".venv" / "bin" / "pytest"
    if not pytest_bin.exists():
        pytest_bin = Path("pytest")

    cmd = [str(pytest_bin)]
    if args.verbose:
        cmd.append("-v")

    if args.tier:
        tier_map = {
            1: "tests/e2e/test_tier1_features.py",
            2: "tests/e2e/test_tier2_boundaries.py",
            3: "tests/e2e/test_tier3_combinations.py",
            4: "tests/e2e/test_tier4_scenarios.py",
        }
        cmd.append(tier_map[args.tier])
    else:
        cmd.append("tests/e2e/")

    print("=" * 70)
    print("OBSIDIAN GOOGLE DRIVE SYNC — E2E TEST RUNNER")
    print(f"Mode: {'STRICT (M5 Hardening)' if args.strict else 'Progressive Verification'}")
    print(f"Target: {'All Tiers (1-4)' if not args.tier else f'Tier {args.tier}'}")
    print("=" * 70)

    result = subprocess.run(cmd, cwd=str(repo_root), env=env)
    return result.returncode


if __name__ == "__main__":
    sys.exit(main())
