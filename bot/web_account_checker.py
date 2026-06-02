#!/usr/bin/env python3
import sys
import json
import os

sys.path.insert(0, os.path.dirname(__file__))
from gates.account_checkers import run_check, SUPPORTED_CHECKERS


def main():
    if len(sys.argv) < 4:
        print(json.dumps({"status": "error", "message": "Usage: web_account_checker.py <checker> <user> <pass> [proxy]"}))
        return

    checker_type = sys.argv[1].lower()
    user = sys.argv[2]
    password = sys.argv[3]
    proxy = sys.argv[4] if len(sys.argv) > 4 else None

    if checker_type not in SUPPORTED_CHECKERS:
        print(json.dumps({"status": "error", "message": f"Unknown checker. Supported: {', '.join(SUPPORTED_CHECKERS.keys())}"}))
        return

    result = run_check(checker_type, user, password, proxy)
    print(json.dumps(result))


if __name__ == "__main__":
    main()
