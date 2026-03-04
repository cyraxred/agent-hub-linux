.PHONY: dev dev-backend dev-frontend install typegen lint typecheck test build-frontend appimage deb clean

install:
	pip install -e ".[dev]"
	cd frontend && npm install

typegen:
	python -m agent_hub.typegen.export > frontend/src/types/generated.ts

dev-backend:
	uvicorn agent_hub.api.app:create_app --factory --reload --port 18080

dev-frontend:
	cd frontend && npm run dev

dev:
	$(MAKE) dev-backend &
	$(MAKE) dev-frontend

lint:
	ruff check src/ tests/
	ruff format --check src/ tests/

typecheck:
	pyright --strict src/
	cd frontend && npx tsc --noEmit

test:
	pytest tests/ -v --tb=short

build-frontend:
	cd frontend && npm run build

run:
	python -m agent_hub.main

appimage:
	@echo "Building AppImage..."
	# TODO: implement AppImage build

deb:
	@echo "Building .deb package..."
	# TODO: implement .deb build

clean:
	rm -rf build/dist frontend/dist .pytest_cache
	find . -type d -name __pycache__ -exec rm -rf {} +
