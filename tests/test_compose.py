"""Static checks on docker-compose.yml and .env.example."""

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
COMPOSE = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
SERVICES = COMPOSE["services"]


def test_five_services_defined():
    assert set(SERVICES) == {"api", "worker", "redis", "db", "web"}


def test_every_service_has_healthcheck():
    for name, svc in SERVICES.items():
        assert "healthcheck" in svc, f"{name} lacks a healthcheck"
        assert svc["healthcheck"].get("test"), f"{name} healthcheck has no test"


def test_named_volumes_declared_and_used():
    volumes = COMPOSE["volumes"]
    assert {"pgdata", "redisdata"} <= set(volumes)
    assert any(v.startswith("pgdata:") for v in SERVICES["db"]["volumes"])
    assert any(v.startswith("redisdata:") for v in SERVICES["redis"]["volumes"])


def test_api_and_worker_env_vars():
    required = {
        "DJANGO_SETTINGS_MODULE",
        "DJANGO_SECRET_KEY",
        "POSTGRES_DB",
        "POSTGRES_USER",
        "POSTGRES_PASSWORD",
        "POSTGRES_HOST",
        "REDIS_URL",
    }
    for name in ("api", "worker"):
        assert required <= set(SERVICES[name]["environment"]), name


def test_api_and_worker_wait_for_healthy_dependencies():
    for name in ("api", "worker"):
        deps = SERVICES[name]["depends_on"]
        assert deps["db"]["condition"] == "service_healthy"
        assert deps["redis"]["condition"] == "service_healthy"


def test_api_publishes_port_8000():
    assert any("8000" in str(p) for p in SERVICES["api"]["ports"])


def test_env_example_has_no_real_secrets_and_covers_vars():
    text = (ROOT / ".env.example").read_text(encoding="utf-8")
    for var in ("DJANGO_SECRET_KEY", "POSTGRES_PASSWORD", "REDIS_URL", "DJANGO_SETTINGS_MODULE"):
        assert f"{var}=" in text
    assert "change-me" in text


def test_backend_dockerfile_uses_non_root_user():
    text = (ROOT / "backend" / "Dockerfile").read_text(encoding="utf-8")
    assert "slim" in text
    assert "USER " in text and "USER root" not in text
