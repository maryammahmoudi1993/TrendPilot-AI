#!/usr/bin/env python3
"""Fail if a file contains a disallowed email address or a disallowed tool name."""

import re
import sys
from pathlib import Path

ALLOWED_EMAIL = "mahmoodi.maryam1993@gmail.com"
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+")
# Built from fragments so this script does not trip its own check.
FORBIDDEN_WORD_RE = re.compile("cla" + "ude|anthr" + "opic", re.IGNORECASE)


def check_file(path: Path) -> list[str]:
    try:
        text = Path(path).read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return []
    problems = []
    for email in sorted(set(EMAIL_RE.findall(text))):
        lowered = email.lower()
        if lowered != ALLOWED_EMAIL and not lowered.endswith("@example.com"):
            problems.append(f"{path}: disallowed email {email}")
    if FORBIDDEN_WORD_RE.search(text):
        problems.append(f"{path}: contains a forbidden tool name")
    return problems


def main(argv: list[str]) -> int:
    problems = [p for name in argv for p in check_file(Path(name))]
    for problem in problems:
        print(problem, file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
