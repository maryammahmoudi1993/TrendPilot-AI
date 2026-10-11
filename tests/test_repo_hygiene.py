"""Repository hygiene checks: required files and email policy."""

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ALLOWED_EMAIL = "mahmoodi.maryam1993@gmail.com"
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+")


def _tracked_files() -> list[Path]:
    out = subprocess.run(
        ["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout.splitlines()
    return [ROOT / p for p in out if (ROOT / p).is_file()]


def test_required_files_exist():
    for name in ("README.md", ".gitignore", "LICENSE"):
        assert (ROOT / name).is_file(), f"missing {name}"
    assert (ROOT / "docs").is_dir()


def test_license_holder():
    assert "Maryam Mahmoudi" in (ROOT / "LICENSE").read_text(encoding="utf-8")


def test_only_allowed_email_in_tracked_files():
    offenders = []
    for path in _tracked_files():
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for email in EMAIL_RE.findall(text):
            if email.lower() != ALLOWED_EMAIL and not email.lower().endswith(
                "@example.com"
            ):
                offenders.append(f"{path.name}: {email}")
    assert not offenders, offenders
