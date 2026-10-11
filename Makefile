.PHONY: up down test lint format

up:
	docker compose up --build -d

down:
	docker compose down

test:
	cd backend && python -m pytest
	python -m pytest tests

lint:
	cd backend && ruff check . && black --check .

format:
	cd backend && ruff check . --fix && black .
