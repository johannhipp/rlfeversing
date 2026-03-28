#!/usr/bin/env python3

import subprocess
from pathlib import Path


def main() -> int:
    import unittest

    root = Path(__file__).resolve().parent
    suite = unittest.defaultTestLoader.discover(str(root), pattern="test_server.py")
    result = unittest.TextTestRunner(verbosity=1).run(suite)
    if not result.wasSuccessful():
        return 1

    checks = [
        (["python3", "server.py", "--help"], "server.py --help"),
        (["bash", "-n", "run_capture.sh"], "bash -n run_capture.sh"),
    ]
    for command, label in checks:
        completed = subprocess.run(command, cwd=root, check=False)
        if completed.returncode != 0:
            print(f"offline check failed: {label}")
            return completed.returncode or 1

    print("offline checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
