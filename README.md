# TrendPilot AI

[![CI](https://github.com/maryammahmoudi1993/trendpilot-ai/actions/workflows/ci.yml/badge.svg)](https://github.com/maryammahmoudi1993/trendpilot-ai/actions/workflows/ci.yml)
![License](https://img.shields.io/badge/license-MIT-blue.svg)
![Python](https://img.shields.io/badge/python-3.11-blue.svg)

Forecasting and anomaly detection for small businesses: sales, demand, energy
and web traffic.

**Status:** Phase 1 complete (authentication, workspaces and roles). Dataset
upload, forecasting and anomaly detection arrive in later phases. The login UI
arrives with the dashboard in Phase 9; until then the API is used directly.

Demo data: uses public data.

## Stack

Django 5 + DRF, PostgreSQL, Celery + Redis, JWT auth (simplejwt);
React + TypeScript (Vite); Docker Compose; GitHub Actions; pytest and Vitest.
Planned: pandas, statsmodels, XGBoost, PyTorch, SHAP, WeasyPrint.

## Authentication and workspaces

1. `POST /api/auth/register/` creates an account (email is the login, case-insensitive)
   and returns the user plus an access and a refresh token.
2. `POST /api/auth/login/` returns `{access, refresh}`. Send
   `Authorization: Bearer <access>` on every request. Access tokens live 10 minutes;
   `POST /api/auth/refresh/` rotates the refresh token (the old one is blacklisted) and
   `POST /api/auth/logout/` blacklists it. Login and register are throttled per IP and
   login failures never reveal whether an email exists.
3. `POST /api/workspaces/` creates a workspace; the creator becomes its **Owner**. All
   data of later phases lives under `/api/workspaces/{workspace_id}/...`.

Every workspace member has one role:

| Action | Owner | Analyst | Viewer |
| --- | --- | --- | --- |
| View data and members | yes | yes | yes |
| Upload, create, edit, delete data | yes | yes | no |
| Rename workspace | yes | no | no |
| Manage members, delete workspace | yes | no | no |
| Read the audit log | yes | no | no |

Non-members get **404** on a workspace and everything in it (so its existence is not
leaked); members whose role lacks the action get **403**; anonymous callers get **401**.
A workspace always keeps at least one Owner. Details and the building blocks for new
apps: [docs/permissions.md](docs/permissions.md); accounts and errors:
[docs/accounts.md](docs/accounts.md).

### API overview

| Area | Endpoints |
| --- | --- |
| Auth | `POST /api/auth/register/ login/ refresh/ logout/ change-password/`, `GET/PATCH /api/auth/me/` |
| Workspaces | `GET/POST /api/workspaces/`, `GET/PATCH/DELETE /api/workspaces/{id}/` |
| Members | `GET/POST /api/workspaces/{id}/members/`, `PATCH/DELETE .../members/{membership_id}/`, `POST .../members/leave/` |
| Audit | `GET /api/workspaces/{id}/audit/` (Owners; `?action=` filter) |
| Health | `GET /api/health/` |
| Docs | `GET /api/docs/` (Swagger UI), `GET /api/schema/` (OpenAPI 3) |

Errors always look like `{"error": {"code", "message", "details?"}}`. List endpoints are
paginated (`count`, `next`, `previous`, `results`).

**Upgrading a Phase 0 database:** Phase 1 introduced a custom user model, so recreate
the development database once: `docker compose down -v && docker compose up --build -d`.

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
(cd backend && pytest)       # backend tests (SQLite unless POSTGRES_HOST is set;
                             # the concurrency tests need PostgreSQL and run in CI)
pytest                       # repository-level tests
(cd frontend && npm ci && npm test)
pre-commit install && pre-commit run --all-files
```

## Project structure

```
backend/      Django project: config/ (settings split), apps/core (health, errors),
              apps/accounts (users, JWT), apps/workspaces (workspaces, roles, scoping),
              apps/audit (audit log)
frontend/     Vite + React + TypeScript app, nginx image with /api proxy
tests/        Repository-level tests (hygiene, compose, tooling, CI)
scripts/      Helper scripts used by pre-commit hooks
docs/         Documentation
.github/      CI workflow
docker-compose.yml, Makefile, .env.example, .pre-commit-config.yaml
```

## License

MIT, see [LICENSE](LICENSE).
