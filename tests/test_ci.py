"""Static checks on the GitHub Actions workflow and README badges."""

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
WORKFLOW = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8"))
JOBS = WORKFLOW["jobs"]


def _run_steps(job: str) -> str:
    return "\n".join(s.get("run", "") for s in JOBS[job]["steps"])


def test_triggers_on_push_and_pull_request():
    triggers = WORKFLOW.get("on", WORKFLOW.get(True))
    assert "push" in triggers and "pull_request" in triggers


def test_expected_jobs_exist():
    assert {"backend", "frontend", "compose"} <= set(JOBS)


def test_backend_job_has_postgres_and_redis_services():
    assert {"postgres", "redis"} <= set(JOBS["backend"]["services"])


def test_backend_job_runs_lint_and_tests_with_coverage():
    runs = _run_steps("backend")
    assert "ruff check" in runs
    assert "black --check" in runs
    assert "pytest" in runs and "--cov" in runs


def test_frontend_job_runs_lint_test_build():
    runs = _run_steps("frontend")
    assert "npm run lint" in runs
    assert "npm test" in runs
    assert "npm run build" in runs


def test_compose_job_validates_config():
    assert "docker compose" in _run_steps("compose")
    assert "config" in _run_steps("compose")


def test_readme_has_ci_badge():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "actions/workflows/ci.yml/badge.svg" in readme
