.PHONY: up down test lint format

up:
	docker compose up --build -d

down:
	docker compose down

test:
	cd backend && python -m pytest
	python -m pytest tests
	cd frontend && npm test

lint:
	cd backend && ruff check . && black --check .
	cd frontend && npm run lint && npm run format:check

format:
	cd backend && ruff check . --fix && black .
	cd frontend && npm run format
