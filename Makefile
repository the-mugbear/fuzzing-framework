.PHONY: help install dev test clean docker-build docker-up docker-down run-core run-agent run-target

help:
	@echo "Fuzzer MVP - Available Commands"
	@echo "================================"
	@echo "Development:"
	@echo "  make install       - Install dependencies"
	@echo "  make dev           - Install development dependencies"
	@echo "  make run-core      - Run Core API server"
	@echo "  make run-agent     - Run agent"
	@echo "  make run-target    - Run test target server"
	@echo ""
	@echo "Docker:"
	@echo "  make docker-build  - Build Docker images"
	@echo "  make docker-up     - Start all services"
	@echo "  make docker-down   - Stop all services"
	@echo "  make docker-logs   - View logs"
	@echo ""
	@echo "Testing:"
	@echo "  make test          - Run tests"
	@echo "  make test-target   - Test connection to target"
	@echo ""
	@echo "Cleanup:"
	@echo "  make clean         - Clean temporary files"
	@echo "  make clean-data    - Clean corpus and crash data"

install:
	pip install -r requirements.txt

dev:
	pip install -r requirements.txt
	pip install pytest pytest-asyncio black ruff

run-core:
	python -m core.api.server

run-agent:
	python -m agent.main --core-url http://localhost:8000 --target-host localhost --target-port 9999

run-target:
	python tests/simple_tcp_server.py

docker-build:
	docker-compose build

docker-up:
	docker-compose up -d
	@echo ""
	@echo "Fuzzer Core API: http://localhost:8000"
	@echo "Web UI: http://localhost:8000"
	@echo "Target Server: localhost:9999"
	@echo ""
	@echo "View logs: make docker-logs"

docker-down:
	docker-compose down

docker-logs:
	docker-compose logs -f

test:
	pytest tests/ -v

test-target:
	@echo "Testing connection to target..."
	@python -c "import socket; s = socket.socket(); s.connect(('localhost', 9999)); s.send(b'STCP\x00\x00\x00\x05\x01HELLO'); print('Response:', s.recv(1024)); s.close()" || echo "Target not reachable"

clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete
	find . -type f -name "*.pyo" -delete
	find . -type d -name "*.egg-info" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true

clean-data:
	rm -rf data/corpus/* data/crashes/* data/logs/*
	rm -rf core/corpus/* core/crashes/*
