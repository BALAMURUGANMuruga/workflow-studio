.PHONY: help backend-install frontend-install backend frontend lint clean docker-up docker-down

help:
	@echo "Workflow Studio"
	@echo ""
	@echo "  make backend-install   Install Python dependencies"
	@echo "  make frontend-install  Install Node dependencies"
	@echo "  make backend           Start FastAPI (port 8000)"
	@echo "  make frontend          Start Angular (port 4200)"
	@echo "  make docker-up         Start with docker-compose"
	@echo "  make docker-down       Stop docker-compose"
	@echo "  make clean             Remove caches and build artifacts"

backend-install:
	cd backend && python -m venv .venv && . .venv/bin/activate && pip install -r requirements.txt

frontend-install:
	cd frontend && npm install

backend:
	cd backend && . .venv/bin/activate && uvicorn app.main:app --reload --host 127.0.0.1 --port 8000

frontend:
	cd frontend && npm start

docker-up:
	docker compose up --build -d

docker-down:
	docker compose down

clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	rm -rf frontend/dist frontend/.angular backend/.pytest_cache
