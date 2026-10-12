#!/usr/bin/env python3
"""commit-msg hook: enforce Conventional Commits and forbid attribution trailers."""

import re
import sys
from pathlib import Path

TYPES = "feat|fix|test|chore|docs|ci|refactor|merge|perf|build|style|revert"
SUBJECT_RE = re.compile(rf"^({TYPES})(\([a-z0-9._/-]+\))?!?: \S.*$")
MAX_SUBJECT = 72
TRAILER_RE = re.compile(r"^(co-authored-by|generated with)", re.IGNORECASE | re.MULTILINE)


def validate(message: str) -> list[str]:
    lines = message.strip().splitlines()
    if not lines:
        return ["empty commit message"]
    subject = lines[0]
    problems = []
    if not SUBJECT_RE.match(subject):
        problems.append(f"subject must look like '<type>(scope): description', got: {subject!r}")
    if len(subject) > MAX_SUBJECT:
        problems.append(f"subject is {len(subject)} chars, limit is {MAX_SUBJECT}")
    if TRAILER_RE.search(message):
        problems.append("attribution trailers are not allowed")
    return problems


def main(argv: list[str]) -> int:
    message = Path(argv[0]).read_text(encoding="utf-8")
    problems = validate(message)
    for problem in problems:
        print(problem, file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
