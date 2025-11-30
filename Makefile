.PHONY: help install install-dev test test-cov lint format clean build upload docs serve-docs
.DEFAULT_GOAL := help

help: ## Show this help message
	@echo "Available commands:"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

install: ## Install the package in development mode
	uv sync

install-dev: ## Install with development dependencies
	uv sync --dev

test: ## Run tests
	uv run pytest

test-cov: ## Run tests with coverage
	uv run pytest --cov=src/malla --cov-report=html --cov-report=term

lint: ## Run linting tools
	uv run ruff check src tests
	uv run basedpyright src

format: ## Format code
	uv run ruff format src tests
	uv run ruff check --fix src tests

clean: ## Clean build artifacts
	rm -rf build/
	rm -rf dist/
	rm -rf *.egg-info/
	rm -rf .pytest_cache/
	rm -rf .coverage
	rm -rf htmlcov/
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete

build: clean ## Build the package
	uv build

upload: build ## Upload to PyPI (requires authentication)
	uv publish

docs: ## Build documentation
	@echo "Documentation build not yet configured"

serve-docs: ## Serve documentation locally
	@echo "Documentation serving not yet configured"

run-web: ## Run the web UI
	./malla-web

run-capture: ## Run the MQTT capture tool
	./malla-capture

dev-setup: install-dev ## Set up development environment
	uv run pre-commit install

check: lint test ## Run all checks (lint + test)

ci: install-dev check ## Run CI pipeline locally

dev-up: ## Start PostgreSQL and run both capture and web services
	@echo "Starting Malla development environment..."
	@echo "1. Starting PostgreSQL..."
	@docker compose up -d postgres || echo "PostgreSQL already running or Docker not available"
	@sleep 2
	@echo "2. Starting capture service (metrics on port 9100)..."
	@uv run malla-capture & echo $$! > .capture.pid
	@sleep 2
	@echo "3. Starting web UI (http://localhost:5001)..."
	@uv run malla-web & echo $$! > .web.pid
	@echo ""
	@echo "Services started! Use 'make dev-stop' to stop them."
	@echo "View logs: tail -f .capture.log .web.log (if logging to files)"

dev-all: dev-up ## Alias for dev-up

dev-stop: ## Stop background services
	@echo "Stopping Malla services..."
	@if [ -f .capture.pid ]; then kill `cat .capture.pid` 2>/dev/null || true; rm .capture.pid; fi
	@if [ -f .web.pid ]; then kill `cat .web.pid` 2>/dev/null || true; rm .web.pid; fi
	@echo "Services stopped."

metrics: ## View Prometheus metrics from capture
	curl -s http://localhost:9100/metrics

metrics-web: ## View Prometheus metrics from web UI
	curl -s http://localhost:5001/metrics
