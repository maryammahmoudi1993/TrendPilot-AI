# TrendPilot AI

[![CI](https://github.com/maryammahmoudi1993/trendpilot-ai/actions/workflows/ci.yml/badge.svg)](https://github.com/maryammahmoudi1993/trendpilot-ai/actions/workflows/ci.yml)
![License](https://img.shields.io/badge/license-MIT-blue.svg)
![Python](https://img.shields.io/badge/python-3.11-blue.svg)

Forecasting and anomaly detection for small businesses: sales, demand, energy
and web traffic.

**Status:** Phase 0 complete (project scaffold). Forecasting features arrive in
later phases.

Demo data: uses public data.

## Stack

Django 5 + DRF, PostgreSQL, Celery + Redis, JWT (installed, no auth logic yet);
React + TypeScript (Vite); Docker Compose; GitHub Actions; pytest and Vitest.
Planned: pandas, statsmodels, XGBoost, PyTorch, SHAP, WeasyPrint.

## Quick start

```bash
docker compose up --build -d      # or: make up
curl localhost:8000/api/health/   # API health JSON
open http://localhost:5173        # frontend, shows the API status
docker compose down               # or: make down
```

Optional: copy `.env.example` to `.env` to override defaults.

### Run the tests locally

```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r backend/requirements/dev.txt
(cd backend && pytest)       # backend tests (SQLite unless POSTGRES_HOST is set)
pytest                       # repository-level tests
(cd frontend && npm ci && npm test)
pre-commit install && pre-commit run --all-files
```

## Project structure

```
backend/      Django project (config/ settings split, apps/core health + Celery ping)
frontend/     Vite + React + TypeScript app, nginx image with /api proxy
tests/        Repository-level tests (hygiene, compose, tooling, CI)
scripts/      Helper scripts used by pre-commit hooks
docs/         Documentation
.github/      CI workflow
docker-compose.yml, Makefile, .env.example, .pre-commit-config.yaml
```

## License

MIT, see [LICENSE](LICENSE).
