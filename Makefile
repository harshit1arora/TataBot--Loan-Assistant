.DEFAULT_GOAL := help
PY := python3

help: ## show this help
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}'

install: ## install both services and the web app
	$(PY) -m pip install -r services/core/requirements-dev.txt -r services/conversation/requirements-dev.txt
	cd apps/web && npm ci

test: test-core test-conversation test-platform test-web ## run every suite

test-platform: ## crm, offermart, mcp tools and the agent graph
	cd services/mock-crm && $(PY) -m pytest
	cd services/mock-offermart && $(PY) -m pytest
	cd services/mcp-server && $(PY) -m pytest
	cd services/agents && $(PY) -m pytest

test-core: ## core service tests
	cd services/core && $(PY) -m pytest

test-conversation: ## conversation tests (drive the real core app in-process)
	cd services/conversation && PYTHONPATH=.:../core $(PY) -m pytest

test-web: ## web unit tests
	cd apps/web && npm test

lint: ## ruff + eslint
	ruff check services scripts api
	cd apps/web && npm run lint

typecheck: ## mypy + tsc
	mypy services/core/core_service services/conversation/conversation_service
	cd apps/web && npm run typecheck

smoke: ## end-to-end smoke test against a running stack
	$(PY) scripts/smoke_test.py

run-core: ## core service on :8000
	cd services/core && uvicorn core_service.main:app --reload --port 8000

run-conversation: ## conversation service on :8001
	cd services/conversation && uvicorn conversation_service.main:app --reload --port 8001

run-agents: ## LangGraph agent service on :8004
	cd services/agents && uvicorn agents.main:app --reload --port 8004

run-mcp: ## MCP tool server over stdio (an MCP client spawns this)
	cd services/mcp-server && $(PY) -m mcp_server

run-mcp-http: ## MCP tool server over streamable HTTP on :8765
	cd services/mcp-server && $(PY) -m mcp_server --http --port 8765

run-mocks: ## MockCRM :8002 and OfferMart :8003
	cd services/mock-crm && uvicorn mock_crm.main:app --port 8002 &
	cd services/mock-offermart && uvicorn mock_offermart.main:app --port 8003

run-worker: ## extraction worker (queue retries and scans)
	cd services/core && $(PY) -m core_service.worker

run-web: ## vite dev server on :8080 (proxies both services)
	cd apps/web && npm run dev

up: ## whole stack in docker (postgres included)
	docker compose up --build

down: ## stop the stack
	docker compose down
