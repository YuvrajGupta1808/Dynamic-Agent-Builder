.PHONY: dev dev-backend dev-web test test-backend test-web build-web

dev:
	pnpm dev

dev-backend:
	PYTHONPATH=backend/src .venv/bin/python -m uvicorn agent_workbench.main:app --host 127.0.0.1 --port 8787 --reload

dev-web:
	pnpm --dir apps/web dev --host 127.0.0.1 --port 5175 --strictPort

test: test-backend test-web

test-backend:
	PYTHONPATH=backend/src .venv/bin/python -m pytest backend/tests

test-web:
	pnpm --dir apps/web test

build-web:
	pnpm --dir apps/web build
