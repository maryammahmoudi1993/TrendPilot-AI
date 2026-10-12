"""Tests for the pre-commit helper scripts (forbidden content, commit messages)."""

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
ALLOWED = "mahmoodi.maryam1993@gmail.com"

# Assembled from fragments so this file never contains the words literally.
WORD_A = "cla" + "ude"
WORD_B = "anthr" + "opic"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


forbidden = _load("check_forbidden")
commit_msg = _load("check_commit_msg")


def test_allowed_email_passes(tmp_path):
    f = tmp_path / "a.txt"
    f.write_text(f"contact {ALLOWED}\n", encoding="utf-8")
    assert forbidden.check_file(f) == []


def test_example_com_placeholder_passes(tmp_path):
    f = tmp_path / "a.txt"
    f.write_text("user@example.com\n", encoding="utf-8")
    assert forbidden.check_file(f) == []


def test_other_email_fails(tmp_path):
    f = tmp_path / "a.txt"
    f.write_text("someone@other-domain.org\n", encoding="utf-8")
    problems = forbidden.check_file(f)
    assert problems and "email" in problems[0]


@pytest.mark.parametrize("word", [WORD_A, WORD_B, WORD_A.upper()])
def test_forbidden_words_fail(tmp_path, word):
    f = tmp_path / "a.txt"
    f.write_text(f"made with {word} tooling\n", encoding="utf-8")
    assert forbidden.check_file(f)


def test_binary_file_is_skipped(tmp_path):
    f = tmp_path / "a.bin"
    f.write_bytes(b"\x00\xff\xfe\x01")
    assert forbidden.check_file(f) == []


def test_main_returns_nonzero_on_problem(tmp_path):
    f = tmp_path / "a.txt"
    f.write_text("x@bad.org\n", encoding="utf-8")
    assert forbidden.main([str(f)]) == 1


def test_main_returns_zero_when_clean(tmp_path):
    f = tmp_path / "a.txt"
    f.write_text("nothing to see\n", encoding="utf-8")
    assert forbidden.main([str(f)]) == 0


@pytest.mark.parametrize(
    "message",
    [
        "feat: add forecast endpoint",
        "fix(api): handle empty dataset",
        "test: cover health check",
        "chore: bump dependencies",
        "docs: describe setup",
        "ci: add backend job",
        "refactor: split settings",
        "merge: phase-0/step-5 tooling",
    ],
)
def test_valid_commit_messages(message):
    assert commit_msg.validate(message) == []


@pytest.mark.parametrize(
    "message",
    ["wip", "update", "fix stuff", "Feat: capitalised", "feat:no space", "feat: "],
)
def test_invalid_commit_messages(message):
    assert commit_msg.validate(message)


def test_subject_over_72_chars_is_rejected():
    assert commit_msg.validate("feat: " + "x" * 80)


def test_attribution_trailers_are_rejected():
    trailer = "Co-Authored-By: Someone <a@example.com>"
    assert commit_msg.validate(f"feat: add thing\n\n{trailer}")


def test_pre_commit_config_wires_hooks():
    text = (ROOT / ".pre-commit-config.yaml").read_text(encoding="utf-8")
    for hook in (
        "ruff",
        "black",
        "end-of-file-fixer",
        "trailing-whitespace",
        "check-yaml",
        "check-forbidden",
        "check-commit-msg",
    ):
        assert hook in text
    assert "commit-msg" in text
