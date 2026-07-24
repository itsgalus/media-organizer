.PHONY: install test lint format format-check check clean

install:
	.venv/bin/python -m pip install -e ".[dev]"

test:
	.venv/bin/python -m pytest -v

lint:
	.venv/bin/python -m ruff check .

format:
	.venv/bin/python -m ruff format .
	.venv/bin/python -m ruff check . --fix

format-check:
	.venv/bin/python -m ruff format --check .

check:
	make lint
	make format-check
	make test

clean:
	find . -path ./.git -prune -o -path ./.venv -prune -o -type d -name __pycache__ -exec rm -rf {} +
	find . -path ./.git -prune -o -path ./.venv -prune -o -type d -name '*.egg-info' -exec rm -rf {} +
	find . -path ./.git -prune -o -path ./.venv -prune -o -type d \( -name build -o -name dist \) -exec rm -rf {} +
	find . -path ./.git -prune -o -path ./.venv -prune -o -type f -name '*.pyc' -delete
	rm -rf .pytest_cache

